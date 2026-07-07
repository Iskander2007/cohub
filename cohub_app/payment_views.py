"""Платёжный модуль COHUB: checkout, платёжная форма, колбэки, заказы.

Связывает воедино задачи PAY-002…PAY-006:

  * checkout (PAY-005)       — создание заказа с защитой от дублей (идемпотентность);
  * платёжная форма          — sandbox-эмуляция банка/PayPal для сквозного теста (PAY-002);
  * колбэк-эндпоинт (PAY-003)— приём вебхука провайдера, проверка подписи, активация подписки;
  * OrderViewSet             — REST API для статуса заказов и их истории (PAY-004).
"""

import hashlib
import json
import logging
import uuid

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError, transaction
from django.http import JsonResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from rest_framework import status as drf_status
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import Order, Subscription
from . import analytics
from .permissions import IsAuthenticatedUser
from .payments import PaymentError, get_provider, price_for, provider_currency
from .serializers import OrderSerializer
from .logging_utils import payment_logger, metrics, request_context

logger = logging.getLogger(__name__)

# Окно идемпотентности: повторный checkout с теми же параметрами в течение
# этого времени переиспользует уже созданный неоплаченный заказ (PAY-005).
IDEMPOTENCY_WINDOW_SECONDS = 15 * 60


def _derive_idempotency_key(user, provider, months, client_key=None):
    """Ключ идемпотентности заказа.

    Если клиент прислал заголовок Idempotency-Key — берём его (привязав к
    пользователю). Иначе строим ключ из параметров заказа И текущего временно́го
    окна: двойной клик в пределах окна переиспользует заказ, но позже (новое окно)
    тот же тариф можно купить снова. Без временно́й компоненты глобальное
    unique-ограничение на idempotency_key навсегда заблокировало бы повторную
    покупку/продление того же `(provider, months)`.
    """
    if client_key:
        raw = f'{user.id}:{client_key}'
    else:
        bucket = int(timezone.now().timestamp() // IDEMPOTENCY_WINDOW_SECONDS)
        raw = f'{user.id}:{provider}:{months}:{bucket}'
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()[:48]


def _start_payment(order, request):
    """Запросить у провайдера ссылку на оплату и перевести заказ в pending."""
    provider = get_provider(order.provider, request=request)
    result = provider.create_payment(order)
    order.provider_order_id = result.get('provider_order_id', order.provider_order_id)
    order.save(update_fields=['provider_order_id', 'updated_at'])
    order.transition_to(
        Order.STATUS_PENDING,
        message=f'Создан платёж у {order.get_provider_display()}',
        event_type='checkout',
        payload={'provider_order_id': order.provider_order_id, 'sandbox': provider.is_sandbox()},
    )
    
    # Логируем инициацию платежа
    payment_logger.payment_initiated(
        user_id=order.user.id,
        order_id=str(order.id),
        provider=order.provider,
        amount=float(order.amount),
        currency=order.currency,
    )

    # Шаг воронки payment_started (последний шаг перед оплатой).
    analytics.capture_event(order.user, 'payment_started', {
        'order_id': str(order.id),
        'provider': order.provider,
        'amount': float(order.amount),
        'currency': order.currency,
        'months': order.subscription_months,
    })

    return result['redirect_url']


def create_checkout(user, provider_name, months, request=None, client_key=None):
    """Создать заказ и начать оплату с защитой от дублей (PAY-005).

    Возвращает (order, redirect_url, reused: bool). reused=True означает, что
    вернули уже существующий неоплаченный заказ вместо создания нового.
    """
    months = max(1, min(int(months), 12))
    if provider_name not in dict(Order.PROVIDER_CHOICES):
        raise PaymentError('Неизвестный провайдер оплаты')

    idem_key = _derive_idempotency_key(user, provider_name, months, client_key)

    # 1) Уже есть открытый заказ с этим ключом в окне идемпотентности — вернём его.
    window_start = timezone.now() - timezone.timedelta(seconds=IDEMPOTENCY_WINDOW_SECONDS)
    existing = Order.objects.filter(
        idempotency_key=idem_key,
        created_at__gte=window_start,
    ).first()
    if existing and existing.is_open:
        provider = get_provider(existing.provider, request=request)
        # CREATED — оплата ещё не начата; FAILED — повторная попытка после отказа.
        # В обоих случаях переводим заказ в pending (заодно получаем новую ссылку
        # на оплату). Без этого повторная оплата FAILED-заказа упёрлась бы в
        # автомат состояний: переход FAILED → PAID запрещён, только FAILED → PENDING.
        if existing.status in (Order.STATUS_CREATED, Order.STATUS_FAILED):
            redirect_url = _start_payment(existing, request)
        else:
            redirect_url = provider.gateway_url(existing) if provider.is_sandbox() else existing_provider_url(existing)
        return existing, redirect_url, True

    amount = price_for(provider_name, months)
    currency = provider_currency(provider_name)

    try:
        with transaction.atomic():
            order = Order.objects.create(
                user=user,
                purpose=Order.PURPOSE_SUBSCRIPTION,
                description=f'PRO-подписка COHUB, {months} мес.',
                subscription_months=months,
                amount=amount,
                currency=currency,
                provider=provider_name,
                idempotency_key=idem_key,
            )
    except IntegrityError:
        # Заказ с этим ключом уже есть (гонка параллельных запросов или повтор).
        existing = Order.objects.filter(idempotency_key=idem_key).first()
        if existing is not None and existing.is_open:
            provider = get_provider(existing.provider, request=request)
            redirect_url = (provider.gateway_url(existing)
                            if provider.is_sandbox() else existing_provider_url(existing))
            return existing, redirect_url, True
        # Найденный заказ уже терминальный (оплачен/отменён) — он не должен
        # блокировать новую покупку. Создаём свежий заказ с «солёным» ключом.
        order = Order.objects.create(
            user=user,
            purpose=Order.PURPOSE_SUBSCRIPTION,
            description=f'PRO-подписка COHUB, {months} мес.',
            subscription_months=months,
            amount=amount,
            currency=currency,
            provider=provider_name,
            idempotency_key=_derive_idempotency_key(user, provider_name, months, client_key=uuid.uuid4().hex),
        )
        redirect_url = _start_payment(order, request)
        return order, redirect_url, False

    redirect_url = _start_payment(order, request)
    return order, redirect_url, False


def existing_provider_url(order):
    """Запасной URL платёжной формы для уже созданного заказа."""
    return get_provider(order.provider).gateway_url(order)


def process_callback(provider_name, order_ref, outcome, payload, source='callback'):
    """Обработать результат оплаты от провайдера. Идемпотентно (PAY-005).

    Находит заказ по provider_order_id или номеру, переводит статус и при успехе
    активирует PRO-подписку. Повторный колбэк с тем же результатом ничего не ломает.
    """
    order = (Order.objects.filter(provider=provider_name, provider_order_id=order_ref).first()
             or Order.objects.filter(number=order_ref).first())
    if order is None:
        logger.warning('Колбэк %s: заказ %s не найден', provider_name, order_ref)
        raise Http404('Заказ не найден')

    if order.is_paid:
        # Повторный колбэк по уже оплаченному заказу — фиксируем и выходим.
        order.transition_to(order.status, message='Повторный колбэк по оплаченному заказу',
                            payload=payload, event_type='duplicate')
        return order, False

    if outcome == 'paid':
        changed = order.transition_to(Order.STATUS_PAID, message=f'Оплата подтверждена ({source})',
                                     payload=payload, event_type=source)
        if changed:
            # Метрика для Grafana: успешный платёж (учитываем только реальный
            # переход, чтобы повторные колбэки не задваивали счётчик).
            metrics.record_payment(True)
            payment_logger.payment_confirmed(
                user_id=order.user_id, order_id=str(order.id), provider=order.provider,
                provider_order_id=order.provider_order_id, amount=float(order.amount),
                currency=order.currency,
            )
            # Финальный шаг воронки: оплата подтверждена (revenue-событие).
            analytics.capture_event(order.user, 'payment_completed', {
                'order_id': str(order.id),
                'provider': order.provider,
                'amount': float(order.amount),
                'currency': order.currency,
                'months': order.subscription_months,
            })
            if order.purpose == Order.PURPOSE_SUBSCRIPTION:
                _activate_subscription(order)
        return order, changed

    changed = order.transition_to(Order.STATUS_FAILED, message=f'Оплата отклонена ({source})',
                                  payload=payload, event_type=source)
    if changed:
        metrics.record_payment(False)
        payment_logger.payment_failed(
            user_id=order.user_id, order_id=str(order.id), provider=order.provider,
            reason=str(payload.get('code') or payload.get('event_type') or source),
        )
        analytics.capture_event(order.user, 'payment_failed', {
            'order_id': str(order.id),
            'provider': order.provider,
            'reason': str(payload.get('code') or payload.get('event_type') or source),
        })
    return order, changed


def _activate_subscription(order):
    """Активировать PRO-подписку пользователя после успешной оплаты заказа."""
    subscription, _ = Subscription.objects.get_or_create(user=order.user)
    subscription.activate_paid(months=order.subscription_months)
    # Пользователь стал PRO — обновляем Person (plan) и шлём событие.
    analytics.identify_user(order.user)
    analytics.capture_event(order.user, 'subscription_activated', {
        'order_id': str(order.id),
        'months': order.subscription_months,
        'amount': float(order.amount),
    })
    from .models import PaymentEvent
    PaymentEvent.objects.create(
        order=order, event_type='subscription', from_status=order.status, to_status=order.status,
        message=f'PRO-подписка активирована на {order.subscription_months} мес.',
    )


# ---------------------------------------------------------------------------
# REST API: заказы пользователя и запуск оплаты
# ---------------------------------------------------------------------------
class OrderViewSet(viewsets.ReadOnlyModelViewSet):
    """Заказы текущего пользователя + запуск оплаты (PAY-002…PAY-006)."""

    serializer_class = OrderSerializer
    permission_classes = [IsAuthenticatedUser]

    def get_queryset(self):
        return (Order.objects.filter(user=self.request.user)
                .prefetch_related('events').order_by('-created_at'))

    @action(detail=False, methods=['get'])
    def config(self, request):
        """Доступные способы оплаты и цены — для страницы подписки."""
        return Response({
            'providers': [
                {
                    'id': Order.PROVIDER_BEREKE,
                    'name': 'Bereke Bank',
                    'currency': provider_currency(Order.PROVIDER_BEREKE),
                    'price_per_month': float(price_for(Order.PROVIDER_BEREKE, 1)),
                    'sandbox': get_provider(Order.PROVIDER_BEREKE).is_sandbox(),
                },
                {
                    'id': Order.PROVIDER_PAYPAL,
                    'name': 'PayPal',
                    'currency': provider_currency(Order.PROVIDER_PAYPAL),
                    'price_per_month': float(price_for(Order.PROVIDER_PAYPAL, 1)),
                    'sandbox': get_provider(Order.PROVIDER_PAYPAL).is_sandbox(),
                },
            ],
        })

    @action(detail=False, methods=['post'])
    def checkout(self, request):
        """Создать заказ и получить ссылку на оплату (PAY-005: защита от дублей)."""
        provider_name = (request.data.get('provider') or Order.PROVIDER_BEREKE).strip()
        months = request.data.get('months', 1)
        client_key = request.headers.get('Idempotency-Key') or request.data.get('idempotency_key')

        try:
            order, redirect_url, reused = create_checkout(
                request.user, provider_name, months, request=request, client_key=client_key,
            )
        except PaymentError as exc:
            return Response({'error': str(exc)}, status=drf_status.HTTP_400_BAD_REQUEST)

        return Response({
            'order_number': order.number,
            'order_id': str(order.id),
            'status': order.status,
            'amount': float(order.amount),
            'currency': order.currency,
            'redirect_url': redirect_url,
            'reused': reused,
        }, status=drf_status.HTTP_200_OK if reused else drf_status.HTTP_201_CREATED)


# ---------------------------------------------------------------------------
# Страницы: платёжная форма (sandbox), возврат после оплаты
# ---------------------------------------------------------------------------
@login_required
def payment_gateway_view(request, order_id):
    """Эмуляция платёжной формы банка/PayPal для sandbox-режима (PAY-002).

    Реальный провайдер показал бы свою форму; здесь пользователь жмёт «Оплатить»
    или «Отклонить», а COHUB формирует подписанный колбэк — ровно как настоящий
    провайдер, и прогоняет его через тот же обработчик process_callback.
    """
    order = get_object_or_404(Order, id=order_id, user=request.user)
    provider = get_provider(order.provider, request=request)

    if not provider.is_sandbox():
        # В реальном режиме сюда не попадают — оплата идёт на стороне провайдера.
        return redirect(provider.return_url(order))

    is_real_api = hasattr(provider, 'uses_real_api') and provider.uses_real_api()

    return render(request, 'payment_gateway.html', {
        'order': order,
        'provider_name': order.get_provider_display(),
        'is_open': order.is_open,
        'is_real_api': is_real_api,
    })


@login_required
@require_POST
def payment_sandbox_confirm_view(request, order_id):
    """Кнопка «Оплатить/Отклонить» на sandbox-форме.

    Формирует подписанный payload, как прислал бы провайдер, и пропускает его
    через общий обработчик колбэка — затем возвращает пользователя на результат.
    """
    order = get_object_or_404(Order, id=order_id, user=request.user)
    provider = get_provider(order.provider, request=request)
    outcome = 'paid' if request.POST.get('outcome') == 'pay' else 'failed'

    payload = provider.build_sandbox_callback(order, outcome)
    try:
        process_callback(order.provider, order.provider_order_id, outcome, payload, source='sandbox')
    except Http404:
        pass
    return redirect('payment-return', order_id=order.id)


@login_required
def payment_return_view(request, order_id):
    """Страница результата после возврата с платёжной формы.

    Для реального PayPal заказ после одобрения нужно списать (capture) — делаем
    это здесь синхронно, как только пользователь вернулся со страницы PayPal.
    """
    order = get_object_or_404(Order, id=order_id, user=request.user)
    provider = get_provider(order.provider, request=request)

    if order.provider == Order.PROVIDER_PAYPAL and order.is_open and provider.uses_real_api():
        try:
            outcome, payload = provider.capture_order(order)
            process_callback(order.provider, order.provider_order_id, outcome, payload, source='capture')
        except (PaymentError, Http404) as exc:
            logger.warning('Не удалось списать PayPal-заказ %s: %s', order.number, exc)
        order.refresh_from_db()

    return render(request, 'payment_result.html', {'order': order})


# ---------------------------------------------------------------------------
# Колбэк провайдера (PAY-003): server-to-server вебхук, без CSRF
# ---------------------------------------------------------------------------
@csrf_exempt
@require_POST
def payment_callback_view(request, provider):
    """Приём вебхука провайдера об оплате (тестируется через ngrok, PAY-003).

    Проверяет подпись, находит заказ, обновляет статус и активирует подписку.
    Эндпоинт идемпотентен: повторная доставка того же события безопасна.
    """
    try:
        prov = get_provider(provider, request=request)
    except PaymentError:
        return JsonResponse({'error': 'unknown provider'}, status=404)

    try:
        order_ref, outcome, payload = prov.verify_callback(request)
    except PaymentError as exc:
        logger.warning('Колбэк %s отклонён: %s', provider, exc)
        return JsonResponse({'error': str(exc)}, status=400)

    try:
        order, changed = process_callback(provider, order_ref, outcome, payload, source='callback')
    except Http404:
        return JsonResponse({'error': 'order not found'}, status=404)

    return JsonResponse({
        'order_number': order.number,
        'status': order.status,
        'changed': changed,
    })
