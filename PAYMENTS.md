# Платёжный модуль COHUB (PAY-002…PAY-006)

Разовая оплата PRO-подписки через **Bereke Bank** (тенге) и **PayPal** (доллары),
с автоматом состояний заказа, защитой от дублей и колбэк-эндпоинтом для вебхуков.

## Что где находится

| Файл | Назначение |
|------|-----------|
| `cohub_app/models.py` → `Order`, `PaymentEvent` | Модель жизненного цикла платежа и автомат состояний (PAY-004) + аудит событий |
| `cohub_app/payments.py` | Провайдеры `BerekeProvider`, `PayPalProvider`: создание платежа, подпись и проверка колбэков (PAY-002/PAY-006) |
| `cohub_app/payment_views.py` | Checkout с идемпотентностью (PAY-005), sandbox-форма, колбэк-эндпоинт (PAY-003), `OrderViewSet` |
| `cohub_app/serializers.py` → `OrderSerializer` | REST-представление заказа и истории |
| `templates/payment_gateway.html` | Эмуляция платёжной формы банка (sandbox) |
| `templates/payment_result.html` | Страница результата оплаты |
| `templates/subscription.html` | Кнопка «Перейти к оплате» с выбором провайдера |
| `cohub_app/tests.py` → `PaymentsTests` | Сквозные тесты всех пяти задач |

## Эндпоинты

| Метод | URL | Что делает |
|-------|-----|-----------|
| `GET`  | `/api/orders/config/` | Список провайдеров и цены |
| `POST` | `/api/orders/checkout/` | Создать заказ, вернуть ссылку на оплату (PAY-005) |
| `GET`  | `/api/orders/` | Заказы пользователя |
| `GET`  | `/api/orders/<id>/` | Один заказ + история переходов |
| `GET`  | `/payments/pay/<id>/` | Sandbox-форма оплаты |
| `POST` | `/payments/pay/<id>/confirm/` | Кнопка «Оплатить/Отклонить» в sandbox |
| `GET`  | `/payments/return/<id>/` | Результат оплаты |
| `POST` | `/payments/callback/<provider>/` | **Вебхук провайдера** (server-to-server) |

## Автомат состояний заказа (PAY-004)

```
created ──> pending ──> paid ──> refunded
   │           │  └────> failed ──> pending (повтор)
   │           ├────> cancelled
   └───────────┴────> expired
```

Переходы проверяются в `Order.transition_to()`; недопустимый переход не меняет
статус и пишет событие `rejected`. Терминальные статусы: `paid` (до возврата),
`cancelled`, `expired`, `refunded`.

## Режим работы: sandbox по умолчанию

Без ключей банка/PayPal модуль работает в **sandbox-эмуляции**: платёжную форму
показывает сам COHUB (`/payments/pay/<id>/`), а кнопка «Оплатить» формирует
**подписанный колбэк** и проводит его через тот же `process_callback`, что и
реальный вебхук. Так сквозной сценарий (PAY-002/PAY-006) проверяется локально.

Чтобы включить реальные песочницы банков — заполните ключи в `.env`
(`BEREKE_CLIENT_SECRET`, `PAYPAL_CLIENT_SECRET`) и выставьте `BEREKE_SANDBOX=False`
/ `PAYPAL_MODE=sandbox` с заданным секретом.

### Реальный PayPal (sandbox и live)

Как только задан `PAYPAL_CLIENT_SECRET`, `PayPalProvider` идёт по настоящему REST API:

1. `create_payment` создаёт заказ `POST /v2/checkout/orders` (intent=CAPTURE) и
   возвращает ссылку `approve` — пользователь подтверждает оплату на сайте PayPal.
2. PayPal редиректит обратно на `/payments/return/<id>/`, где
   `capture_order()` вызывает `POST /v2/checkout/orders/{id}/capture` —
   фактическое списание. При статусе `COMPLETED` заказ переходит в `paid`,
   подписка активируется.

База API выбирается по `PAYPAL_MODE`: `sandbox` → `api-m.sandbox.paypal.com`,
`live` → `api-m.paypal.com`. PayPal не поддерживает тенге, поэтому платежи идут
в USD (`SUBSCRIPTION_PRICE_USD`). Для sandbox‑теста ngrok не нужен — браузер сам
возвращается на localhost, а списание сервер делает исходящим запросом.

## Защита от дублей (PAY-005)

- Поле `Order.idempotency_key` — **уникально** в БД.
- Заголовок `Idempotency-Key` (или детерминированный ключ из `user+provider+months`)
  в окне 15 минут переиспользует уже созданный неоплаченный заказ вместо нового.
- Повторный колбэк по оплаченному заказу не активирует подписку второй раз.
- Кнопка на фронте блокируется на время запроса.

## Тестирование колбэка через ngrok (PAY-003)

Реальный провайдер вызывает колбэк по публичному URL. Чтобы протестировать это
локально:

1. Запустите сервер: `py manage.py runserver 8000`
2. Поднимите туннель: `ngrok http 8000`
3. Скопируйте https-адрес (например `https://ab12.ngrok-free.app`) в `.env`:
   ```
   PAYMENT_PUBLIC_BASE_URL=https://ab12.ngrok-free.app
   ```
   Теперь `postLink`/`return_url`, передаваемые провайдеру, указывают на ngrok,
   и банк/PayPal сможет достучаться до `/payments/callback/<provider>/`.
4. Добавьте ngrok-хост в `DJANGO_ALLOWED_HOSTS` и `DJANGO_CSRF_TRUSTED_ORIGINS`.
5. Проведите тестовую оплату — вебхук придёт на ваш локальный сервер.

Колбэк-эндпоинт `@csrf_exempt`, проверяет HMAC-SHA256 подпись и идемпотентен.

## Тесты

```
py manage.py test cohub_app.tests.PaymentsTests
```

Покрывают: сквозную оплату Bereke и PayPal, проверку подписи колбэка,
идемпотентность checkout и колбэка, запрет недопустимых переходов автомата,
отклонённый платёж.
