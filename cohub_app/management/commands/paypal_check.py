"""Диагностика интеграции с PayPal (Sandbox/Live) без прохождения UI-флоу.

Позволяет убедиться, что заданные PAYPAL_CLIENT_ID/SECRET валидны и что COHUB
может общаться с PayPal REST API, НЕ кликая весь чек-аут в браузере:

    python manage.py paypal_check
        → печатает режим (sandbox/live), какой API base используется, активен ли
          реальный API, и пытается получить OAuth-токен (доказывает валидность
          Client ID/Secret).

    python manage.py paypal_check --create-order
        → дополнительно создаёт тестовый заказ в PayPal и печатает ссылку approve.

    python manage.py paypal_check --create-order --base-url https://xxxx.ngrok-free.app
        → задаёт базовый URL для return_url тестового заказа (по умолчанию
          http://localhost:8000).

Команда НИЧЕГО НЕ СПИСЫВАЕТ: capture (фактическое списание) требует одобрения
покупателем на стороне PayPal, поэтому автоматизировать его нельзя. См.
PAYPAL_QUICKSTART.md / PAYPAL_SETUP.md.
"""

from __future__ import annotations

import uuid

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from cohub_app.payments import PayPalProvider, price_for


class _CheckOrder:
    """Минимальный «заказ» для проверки создания PayPal-ордера (в БД не пишется).

    Дублирует только те поля/метод, к которым обращается
    ``PayPalProvider._create_real_order`` (number, amount, currency, id, save()).
    """

    def __init__(self, amount, currency, months):
        self.id = uuid.uuid4()  # нужен для reverse('payment-return', args=[id])
        self.number = 'CHECK-' + uuid.uuid4().hex[:8].upper()
        self.amount = amount
        self.currency = currency
        self.subscription_months = months
        self.provider_order_id = ''
        self.provider_payment_id = ''

    def save(self, *args, **kwargs):  # провайдер может вызвать save() — гасим no-op'ом
        pass


class Command(BaseCommand):
    help = ('Проверить связь с PayPal (Sandbox/Live): режим, OAuth-токен и, '
            'опционально, создание тестового заказа. Ничего не списывает.')

    def add_arguments(self, parser):
        parser.add_argument(
            '--create-order', action='store_true',
            help='Создать тестовый заказ в PayPal и вывести ссылку approve (без списания).')
        parser.add_argument(
            '--months', type=int, default=1,
            help='Число месяцев для тестового заказа (1–12, по умолчанию 1).')
        parser.add_argument(
            '--base-url', default='http://localhost:8000',
            help='Базовый URL для return_url тестового заказа (по умолчанию http://localhost:8000).')

    def handle(self, *args, **opts):
        provider = PayPalProvider()
        mode = (getattr(settings, 'PAYPAL_MODE', 'sandbox') or 'sandbox').lower()
        has_id = bool(getattr(settings, 'PAYPAL_CLIENT_ID', ''))
        has_secret = bool(getattr(settings, 'PAYPAL_CLIENT_SECRET', ''))
        webhook = getattr(settings, 'PAYPAL_WEBHOOK_ID', '')

        self.stdout.write(self.style.MIGRATE_HEADING('PayPal · проверка конфигурации'))
        self.stdout.write(f'  PAYPAL_MODE          : {mode}')
        self.stdout.write(f'  API base             : {provider._api_base()}')
        self.stdout.write(f'  Client ID задан      : {"да" if has_id else "НЕТ"}')
        self.stdout.write(f'  Client Secret задан  : {"да" if has_secret else "НЕТ"}')
        self.stdout.write(f'  Sandbox              : {"да" if provider.is_sandbox() else "НЕТ — LIVE!"}')
        self.stdout.write(f'  Реальный API активен : '
                          f'{"да" if provider.uses_real_api() else "нет (встроенная эмуляция COHUB)"}')
        self.stdout.write(f'  Webhook ID задан     : '
                          f'{"да" if webhook else "нет (не обязателен — capture идёт на возврате)"}')

        if not provider.uses_real_api():
            raise CommandError(
                'Реальный API PayPal НЕ активен: пустой PAYPAL_CLIENT_SECRET → работает встроенная '
                'эмуляция COHUB. Чтобы включить реальный Sandbox, задайте в .env PAYPAL_CLIENT_ID и '
                'PAYPAL_CLIENT_SECRET (Sandbox-приложение с https://developer.paypal.com), затем '
                'перезапустите проверку. Пошагово — PAYPAL_QUICKSTART.md.')

        # 1) OAuth-токен — доказывает валидность Client ID/Secret.
        base = provider._api_base()
        try:
            token = provider._access_token(base)
        except Exception as exc:  # noqa: BLE001
            raise CommandError(
                f'Не удалось получить OAuth-токен PayPal ({base}): {exc}\n'
                'Проверьте PAYPAL_CLIENT_ID/SECRET и что это креды нужного окружения '
                '(для Sandbox — вкладка Sandbox на developer.paypal.com, приложение типа "Merchant").')
        self.stdout.write(self.style.SUCCESS(
            f'\n✓ OAuth-токен получен (…{token[-6:]}). Client ID/Secret валидны, связь с PayPal есть.'))

        if not opts['create_order']:
            self.stdout.write('\nБазовая проверка пройдена. Полный тест создания заказа:\n'
                              '  python manage.py paypal_check --create-order')
            return

        # 2) Создать тестовый заказ (без списания) — проверяет весь путь create-order.
        months = max(1, min(int(opts['months']), 12))
        amount = price_for(PayPalProvider.name, months)
        # return_url должен быть абсолютным URL (PayPal отвергает относительный путь);
        # выставляем базовый URL только на время этой проверки в текущем процессе.
        settings.PAYMENT_PUBLIC_BASE_URL = (opts['base_url'] or '').rstrip('/')
        order = _CheckOrder(amount=amount, currency=PayPalProvider.currency, months=months)
        try:
            result = provider._create_real_order(order)
        except Exception as exc:  # noqa: BLE001
            raise CommandError(f'Не удалось создать тестовый заказ PayPal: {exc}')

        self.stdout.write(self.style.SUCCESS('✓ Тестовый заказ создан в PayPal Sandbox.'))
        self.stdout.write(f'  PayPal order id : {result["provider_order_id"]}')
        self.stdout.write(f'  Сумма           : {amount} {PayPalProvider.currency} ({months} мес.)')
        self.stdout.write(self.style.HTTP_INFO(f'  Ссылка approve  : {result["redirect_url"]}'))
        self.stdout.write(
            '\nОткройте ссылку approve в браузере, войдите тестовым Sandbox-покупателем и одобрите — '
            'деньги НЕ спишутся (capture выполняет только страница возврата приложения). '
            'Это подтверждает, что создание заказа работает от начала до конца.')
