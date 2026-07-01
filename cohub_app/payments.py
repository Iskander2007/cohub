"""Платёжные провайдеры COHUB.

Здесь живёт интеграция с песочницами Bereke Bank (PAY-002/PAY-003) и
PayPal (PAY-006). Каждый провайдер умеет:

  * create_payment(order, ...)  — начать оплату, вернуть ссылку на платёжную форму;
  * build_signature(...)        — подписать/проверить данные колбэка;
  * verify_callback(request)    — разобрать входящий вебхук и сказать, оплачено ли.

Режимы работы
-------------
По умолчанию провайдеры работают в *sandbox-симуляции*: реальные деньги и сеть
не нужны, платёжная форма эмулируется внутренней страницей COHUB
(`/payments/pay/<order>/`). Это позволяет прогнать сквозной сценарий и колбэк
локально и через ngrok без ключей банка.

Если в окружении заданы реальные ключи провайдера и выключен sandbox-режим
(`*_SANDBOX=False`), вызываются настоящие HTTP-эндпоинты песочниц банка/PayPal.
HTTP-зависимость (`requests`) импортируется лениво, поэтому симуляция работает,
даже если библиотека не установлена.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from decimal import Decimal

from django.conf import settings
from django.urls import reverse


class PaymentError(Exception):
    """Ошибка на стороне платёжного провайдера."""


# Публичные секреты «по умолчанию» из репозитория/настроек. В боевом режиме
# полагаться на них нельзя — иначе подпись колбэка может подделать кто угодно.
DEFAULT_WEBHOOK_SECRETS = frozenset({'bereke-sandbox-secret', 'paypal-sandbox-secret', ''})


def _abs_url(request, path):
    """Абсолютный URL для return/callback.

    Если задан PAYMENT_PUBLIC_BASE_URL (например, ngrok-адрес из PAY-003) —
    используем его: внешний провайдер должен достучаться до колбэка снаружи.
    Иначе строим адрес от текущего запроса.
    """
    base = (getattr(settings, 'PAYMENT_PUBLIC_BASE_URL', '') or '').strip().rstrip('/')
    if base:
        return f"{base}{path}"
    if request is not None:
        return request.build_absolute_uri(path)
    return path


class BaseProvider:
    name = ''
    currency = 'KZT'

    def __init__(self, request=None):
        self.request = request

    # -- URL-хелперы ---------------------------------------------------------
    def callback_url(self, order):
        return _abs_url(self.request, reverse('payment-callback', args=[self.name]))

    def return_url(self, order):
        return _abs_url(self.request, reverse('payment-return', args=[order.id]))

    def gateway_url(self, order):
        """Внутренняя эмуляция платёжной формы (sandbox-режим)."""
        return _abs_url(self.request, reverse('payment-gateway', args=[order.id]))

    # -- Подпись колбэка -----------------------------------------------------
    def secret(self):
        raise NotImplementedError

    def build_signature(self, payload: dict) -> str:
        """HMAC-SHA256 по отсортированному JSON без поля sign."""
        data = {k: v for k, v in payload.items() if k != 'sign'}
        canonical = json.dumps(data, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
        return hmac.new(self.secret().encode('utf-8'), canonical.encode('utf-8'), hashlib.sha256).hexdigest()

    def verify_signature(self, payload: dict) -> bool:
        provided = (payload or {}).get('sign', '')
        expected = self.build_signature(payload)
        return bool(provided) and hmac.compare_digest(str(provided), expected)

    def has_custom_secret(self) -> bool:
        """True, если секрет колбэка переопределён (а не публичный дефолт)."""
        return self.secret() not in DEFAULT_WEBHOOK_SECRETS

    # -- Переопределяется провайдерами --------------------------------------
    def is_sandbox(self) -> bool:
        raise NotImplementedError

    def uses_real_api(self) -> bool:
        """True, если оплата идёт через настоящий API провайдера, а не эмуляцию."""
        return False

    def create_payment(self, order):
        """Начать оплату. Возвращает {'redirect_url': ..., 'provider_order_id': ...}."""
        raise NotImplementedError

    def verify_callback(self, request):
        """Разобрать вебхук. Возвращает (order_ref, outcome, payload).

        outcome ∈ {'paid', 'failed'}. order_ref — provider_order_id или номер заказа.
        Бросает PaymentError, если подпись неверна.
        """
        raise NotImplementedError

    def build_sandbox_callback(self, order, outcome: str) -> dict:
        """Сформировать подписанный payload так, как его прислал бы провайдер.

        Используется внутренней платёжной формой в sandbox-режиме, чтобы
        прогнать ровно тот же код обработки колбэка, что и в проде.
        """
        raise NotImplementedError


class BerekeProvider(BaseProvider):
    """Bereke Bank ePay (acquiring) — разовые платежи в тенге (PAY-002/PAY-003)."""

    name = 'bereke'
    currency = 'KZT'

    def secret(self):
        return getattr(settings, 'BEREKE_CALLBACK_SECRET', '') or 'bereke-sandbox-secret'

    def is_sandbox(self):
        return bool(getattr(settings, 'BEREKE_SANDBOX', True)) or not getattr(settings, 'BEREKE_CLIENT_SECRET', '')

    def uses_real_api(self):
        # Реальный API Bereke — только когда явно выключен sandbox и заданы ключи.
        return not self.is_sandbox()

    def create_payment(self, order):
        order.provider_order_id = 'BRK-' + uuid.uuid4().hex[:12].upper()

        if not self.uses_real_api():
            # Песочница: платёжную форму эмулирует сам COHUB.
            return {'redirect_url': self.gateway_url(order), 'provider_order_id': order.provider_order_id}

        # Реальная песочница Bereke ePay: получить OAuth-токен и создать инвойс.
        return self._create_real_invoice(order)

    def _create_real_invoice(self, order):  # pragma: no cover - требует ключей банка
        try:
            import requests
        except ImportError as exc:
            raise PaymentError('Для реального режима Bereke нужна библиотека requests') from exc

        base = getattr(settings, 'BEREKE_API_BASE', 'https://testoauth.homebank.kz')
        try:
            token_resp = requests.post(
                f"{base}/epay2/oauth2/token",
                data={
                    'grant_type': 'client_credentials',
                    'scope': 'webapi usermanagement transfers',
                    'client_id': settings.BEREKE_CLIENT_ID,
                    'client_secret': settings.BEREKE_CLIENT_SECRET,
                    'invoiceID': order.provider_order_id,
                    'amount': str(order.amount),
                    'currency': order.currency,
                    'terminal': getattr(settings, 'BEREKE_TERMINAL', ''),
                    'postLink': self.callback_url(order),
                },
                timeout=15,
            )
            token_resp.raise_for_status()
            access_token = token_resp.json().get('access_token')
            if not access_token:
                raise PaymentError('Bereke не вернул access_token')
        except Exception as exc:  # noqa: BLE001
            raise PaymentError(f'Ошибка авторизации в Bereke: {exc}') from exc

        # Реальный ePay отрисовывает форму на стороне банка; ссылку на неё
        # возвращает эндпоинт оплаты. Формируем минимальный payment payload.
        pay_url = (
            f"{base}/payment/api/payment?invoiceId={order.provider_order_id}"
            f"&amount={order.amount}&currency={order.currency}"
        )
        return {'redirect_url': pay_url, 'provider_order_id': order.provider_order_id, 'access_token': access_token}

    def build_sandbox_callback(self, order, outcome):
        payload = {
            'invoiceId': order.provider_order_id,
            'orderNumber': order.number,
            'amount': str(order.amount),
            'currency': order.currency,
            'code': 'ok' if outcome == 'paid' else 'declined',
            'reference': 'BRK-REF-' + uuid.uuid4().hex[:10].upper(),
        }
        payload['sign'] = self.build_signature(payload)
        return payload

    def verify_callback(self, request):
        payload = _parse_body(request)
        # В боевом режиме отказываемся проверять подпись публичным дефолт-секретом:
        # это позволило бы подделать колбэк об оплате.
        if self.uses_real_api() and not self.has_custom_secret():
            raise PaymentError('BEREKE_CALLBACK_SECRET не задан для боевого режима')
        if not self.verify_signature(payload):
            raise PaymentError('Неверная подпись колбэка Bereke')
        outcome = 'paid' if str(payload.get('code', '')).lower() in {'ok', 'success', '0'} else 'failed'
        order_ref = payload.get('invoiceId') or payload.get('orderNumber')
        return order_ref, outcome, payload


class PayPalProvider(BaseProvider):
    """PayPal REST (sandbox) — международные платежи в USD (PAY-006)."""

    name = 'paypal'
    currency = 'USD'

    def secret(self):
        return getattr(settings, 'PAYPAL_WEBHOOK_SECRET', '') or 'paypal-sandbox-secret'

    def is_sandbox(self):
        mode = (getattr(settings, 'PAYPAL_MODE', 'sandbox') or 'sandbox').lower()
        return mode != 'live' or not getattr(settings, 'PAYPAL_CLIENT_SECRET', '')

    def uses_real_api(self):
        # Реальный API PayPal задействуется, как только задан client secret
        # (база URL — sandbox или live — выбирается отдельно в _api_base()).
        return bool(getattr(settings, 'PAYPAL_CLIENT_SECRET', ''))

    def _api_base(self):
        return ('https://api-m.sandbox.paypal.com'
                if self.is_sandbox() else 'https://api-m.paypal.com')

    def _access_token(self, base):  # pragma: no cover - требует ключей PayPal
        import requests
        resp = requests.post(
            f"{base}/v1/oauth2/token",
            auth=(settings.PAYPAL_CLIENT_ID, settings.PAYPAL_CLIENT_SECRET),
            data={'grant_type': 'client_credentials'},
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()['access_token']

    def create_payment(self, order):
        order.provider_order_id = 'PP-' + uuid.uuid4().hex[:12].upper()

        if not self.uses_real_api():
            # Без ключей PayPal эмулируем форму внутренней страницей COHUB.
            return {'redirect_url': self.gateway_url(order), 'provider_order_id': order.provider_order_id}

        return self._create_real_order(order)

    def _create_real_order(self, order):  # pragma: no cover - требует ключей PayPal
        try:
            import requests
        except ImportError as exc:
            raise PaymentError('Для реального режима PayPal нужна библиотека requests') from exc

        base = self._api_base()
        try:
            access_token = self._access_token(base)
            order_resp = requests.post(
                f"{base}/v2/checkout/orders",
                headers={'Authorization': f'Bearer {access_token}', 'Content-Type': 'application/json'},
                json={
                    'intent': 'CAPTURE',
                    'purchase_units': [{
                        'reference_id': order.number,
                        'custom_id': order.number,
                        'amount': {'currency_code': order.currency, 'value': f'{order.amount:.2f}'},
                    }],
                    'application_context': {
                        'return_url': self.return_url(order),
                        'cancel_url': self.return_url(order),
                        'user_action': 'PAY_NOW',
                    },
                },
                timeout=15,
            )
            order_resp.raise_for_status()
            data = order_resp.json()
        except Exception as exc:  # noqa: BLE001
            raise PaymentError(f'Ошибка создания заказа PayPal: {exc}') from exc

        order.provider_order_id = data['id']
        approve = next((l['href'] for l in data.get('links', []) if l.get('rel') == 'approve'), None)
        if not approve:
            raise PaymentError('PayPal не вернул ссылку approve')
        return {'redirect_url': approve, 'provider_order_id': data['id']}

    def capture_order(self, order):  # pragma: no cover - требует ключей PayPal
        """Списать (capture) одобренный пользователем заказ PayPal.

        Вызывается на странице возврата: пользователь подтвердил оплату на сайте
        PayPal, и теперь нужно фактически провести списание. Возвращает
        (outcome, payload), где outcome ∈ {'paid', 'failed'}.
        """
        try:
            import requests
        except ImportError as exc:
            raise PaymentError('Для реального режима PayPal нужна библиотека requests') from exc

        base = self._api_base()
        try:
            access_token = self._access_token(base)
            resp = requests.post(
                f"{base}/v2/checkout/orders/{order.provider_order_id}/capture",
                headers={'Authorization': f'Bearer {access_token}', 'Content-Type': 'application/json'},
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:  # noqa: BLE001
            raise PaymentError(f'Ошибка списания PayPal: {exc}') from exc

        outcome = 'paid' if data.get('status') == 'COMPLETED' else 'failed'
        # Сохраняем id списания (capture id) для сверки/возвратов.
        try:
            capture = data['purchase_units'][0]['payments']['captures'][0]
            order.provider_payment_id = capture.get('id', '')
            order.save(update_fields=['provider_payment_id', 'updated_at'])
        except (KeyError, IndexError):
            pass
        return outcome, data

    def build_sandbox_callback(self, order, outcome):
        payload = {
            'id': 'WH-' + uuid.uuid4().hex[:10].upper(),
            'event_type': 'PAYMENT.CAPTURE.COMPLETED' if outcome == 'paid' else 'PAYMENT.CAPTURE.DENIED',
            'resource': {
                'id': order.provider_order_id,
                'custom_id': order.number,
                'amount': {'currency_code': order.currency, 'value': f'{order.amount:.2f}'},
                'status': 'COMPLETED' if outcome == 'paid' else 'DECLINED',
            },
        }
        payload['sign'] = self.build_signature(payload)
        return payload

    def _verify_real_webhook(self, request, payload) -> bool:  # pragma: no cover - требует ключей PayPal
        """Проверить подпись реального вебхука PayPal через их API.

        PayPal не присылает наш HMAC-`sign`; вместо этого вебхук подписывается
        сертификатом PayPal, а проверяется вызовом
        /v1/notifications/verify-webhook-signature с заголовками PAYPAL-* и
        PAYPAL_WEBHOOK_ID. Без заданного webhook id проверку считаем непройденной.
        """
        webhook_id = getattr(settings, 'PAYPAL_WEBHOOK_ID', '')
        if not webhook_id:
            return False
        try:
            import requests
        except ImportError as exc:
            raise PaymentError('Для проверки вебхука PayPal нужна библиотека requests') from exc

        base = self._api_base()
        try:
            token = self._access_token(base)
            resp = requests.post(
                f"{base}/v1/notifications/verify-webhook-signature",
                headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'},
                json={
                    'auth_algo': request.headers.get('PAYPAL-AUTH-ALGO'),
                    'cert_url': request.headers.get('PAYPAL-CERT-URL'),
                    'transmission_id': request.headers.get('PAYPAL-TRANSMISSION-ID'),
                    'transmission_sig': request.headers.get('PAYPAL-TRANSMISSION-SIG'),
                    'transmission_time': request.headers.get('PAYPAL-TRANSMISSION-TIME'),
                    'webhook_id': webhook_id,
                    'webhook_event': payload,
                },
                timeout=15,
            )
            resp.raise_for_status()
            return resp.json().get('verification_status') == 'SUCCESS'
        except Exception as exc:  # noqa: BLE001
            raise PaymentError(f'Ошибка проверки вебхука PayPal: {exc}') from exc

    def verify_callback(self, request):
        payload = _parse_body(request)
        if self.uses_real_api():
            # Реальный PayPal: проверяем подпись вебхука через PayPal API
            # (самодельного HMAC-поля `sign` PayPal не присылает).
            if not self._verify_real_webhook(request, payload):
                raise PaymentError('Не удалось проверить подпись вебхука PayPal')
        elif not self.verify_signature(payload):
            # Sandbox-эмуляция: проверяем нашу HMAC-подпись.
            raise PaymentError('Неверная подпись вебхука PayPal')
        event_type = payload.get('event_type', '')
        outcome = 'paid' if event_type == 'PAYMENT.CAPTURE.COMPLETED' else 'failed'
        resource = payload.get('resource', {})
        # custom_id у реального вебхука = номер нашего заказа; resource.id для
        # CAPTURE-события — это id списания, поэтому сначала пробуем custom_id.
        order_ref = resource.get('custom_id') or resource.get('id')
        return order_ref, outcome, payload


_PROVIDERS = {
    BerekeProvider.name: BerekeProvider,
    PayPalProvider.name: PayPalProvider,
}


def get_provider(name, request=None) -> BaseProvider:
    cls = _PROVIDERS.get(name)
    if cls is None:
        raise PaymentError(f'Неизвестный платёжный провайдер: {name}')
    return cls(request=request)


def provider_currency(name) -> str:
    cls = _PROVIDERS.get(name)
    return cls.currency if cls else 'KZT'


def price_for(provider_name, months: int) -> Decimal:
    """Стоимость PRO-подписки у конкретного провайдера за `months` месяцев."""
    months = max(1, int(months))
    if provider_name == PayPalProvider.name:
        per_month = Decimal(str(getattr(settings, 'SUBSCRIPTION_PRICE_USD', '9.99')))
    else:
        per_month = Decimal(str(getattr(settings, 'SUBSCRIPTION_PRICE_KZT', '5000')))
    return (per_month * months).quantize(Decimal('0.01'))


def _parse_body(request) -> dict:
    """Достаёт payload из вебхука: JSON-тело или form-encoded."""
    if request is None:
        return {}
    body = getattr(request, 'body', b'') or b''
    if body:
        try:
            return json.loads(body.decode('utf-8'))
        except (ValueError, UnicodeDecodeError):
            pass
    # form-encoded fallback
    if hasattr(request, 'POST') and request.POST:
        data = dict(request.POST.items())
        # вложенный JSON в поле payload (используется sandbox-формой)
        if 'payload' in data:
            try:
                return json.loads(data['payload'])
            except ValueError:
                pass
        return data
    return {}
