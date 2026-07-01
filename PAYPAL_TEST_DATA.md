# 🧪 Тестовые данные PayPal для COHUB

## 📋 Конфигурация для локального тестирования

### Вариант 1: БЫСТРЫЙ СТАРТ (без реальной интеграции)

**Скопируйте в .env файл:**
```bash
# Режим: эмуляция платежей (без учетных данных PayPal)
PAYPAL_MODE=sandbox
# Оставьте эти поля ПУСТЫМИ:
PAYPAL_CLIENT_ID=
PAYPAL_CLIENT_SECRET=
PAYPAL_WEBHOOK_ID=
PAYPAL_WEBHOOK_SECRET=paypal-sandbox-secret

# Цена подписки
SUBSCRIPTION_PRICE_USD=9.99

# Для локального тестирования вебхуков (опционально)
PAYMENT_PUBLIC_BASE_URL=
```

**Результат:** Платежная форма будет эмулироваться внутри COHUB
- ✅ Нажимаете "Оплатить картой"
- ✅ Форма подтверждает платеж
- ✅ Подписка активируется мгновенно

---

## 🌐 Вариант 2: С реальным PayPal Sandbox

### Шаг 1: Создайте PayPal Developer Account

1. Перейдите на https://developer.paypal.com
2. Нажмите **Sign Up**
3. Используйте существующий PayPal аккаунт или создайте новый
4. Подтвердите email
5. Логиньтесь в https://developer.paypal.com/dashboard

### Шаг 2: Создайте Sandbox приложение

1. В Dashboard нажмите **Apps & Credentials** (слева)
2. Убедитесь, что выбран **Sandbox** tab (слева)
3. В разделе "REST API apps" нажмите **Create App**
4. Введите имя: `cohub-test`
5. Нажмите **Create App**

### Шаг 3: Копируйте учетные данные

**На странице приложения вы увидите:**

```
CLIENT ID:     <ваш_client_id>
SECRET:        <ваш_secret>
```

### Шаг 4: Добавьте в .env

```bash
PAYPAL_MODE=sandbox
PAYPAL_CLIENT_ID=<ваш_client_id_здесь>
PAYPAL_CLIENT_SECRET=<ваш_secret_здесь>
PAYPAL_WEBHOOK_ID=
PAYPAL_WEBHOOK_SECRET=paypal-sandbox-secret

SUBSCRIPTION_PRICE_USD=9.99
PAYMENT_PUBLIC_BASE_URL=
```

---

## 👤 Тестовые аккаунты PayPal

### Где их найти?

1. Откройте https://developer.paypal.com/dashboard
2. Перейдите на **Accounts** (левое меню, под Sandbox)
3. Вы увидите автоматически созданные тестовые аккаунты

### Обычно есть два аккаунта:

**Покупатель (Buyer):**
```
Email:    sb-xxxxxx@personal.example.com
Password: любой пароль (создадите сами)
```

**Продавец (Merchant/Business):**
```
Email:    sb-xxxxxx@business.example.com
Password: любой пароль
```

### Как их использовать?

1. Нажимаете "Subscribe with PayPal" в COHUB
2. Перенаправляет на paypal.sandbox.com
3. Логиньтесь с email покупателя
4. Подтверждаете платеж
5. Возвращаетесь в COHUB
6. Подписка активируется ✅

---

## 💳 Тестовые номера карт (если нужны)

PayPal автоматически привязывает карты к тестовым аккаунтам.
Но если нужны номера вручную:

### Visa (успешный платеж)
```
Номер:  4532015112830366
Срок:   12/2026
CVV:    123
```

### Mastercard (успешный платеж)
```
Номер:  5425233010103442
Срок:   12/2026
CVV:    456
```

### Amex (успешный платеж)
```
Номер:  374245455400126
Срок:   12/2026
CVV:    1234
```

**Примечание:** PayPal обычно не требует номеров карт для sandbox аккаунтов — они предзагружены.

---

## 🔍 Быстрая проверка

### Проверка 1: Эмуляция работает?

```bash
# В .env оставьте PAYPAL_CLIENT_SECRET пустым
# Запустите:
python manage.py runserver

# Откройте: http://localhost:8000/subscription/
# Нажмите: Subscribe with PayPal
# Должна открыться форма внутри COHUB
```

### Проверка 2: PayPal Sandbox работает?

```bash
# В .env установите:
PAYPAL_MODE=sandbox
PAYPAL_CLIENT_ID=<ваш_id>
PAYPAL_CLIENT_SECRET=<ваш_secret>

# Запустите:
python manage.py runserver

# Откройте: http://localhost:8000/subscription/
# Нажмите: Subscribe with PayPal
# Должны перенаправить на paypal.sandbox.com
```

---

## 🧑‍💻 Для разработчиков: Данные для .env (готовый пример)

### Вариант: Без интеграции (самый простой)
```bash
# .env файл
PAYPAL_MODE=sandbox
# Не устанавливайте PAYPAL_CLIENT_ID и SECRET
SUBSCRIPTION_PRICE_USD=9.99
```

### Вариант: С тестовым PayPal (реком. для тестирования)
```bash
# .env файл
PAYPAL_MODE=sandbox
PAYPAL_CLIENT_ID=<скопировано из PayPal Dashboard>
PAYPAL_CLIENT_SECRET=<скопировано из PayPal Dashboard>
SUBSCRIPTION_PRICE_USD=9.99
```

### Вариант: Для локального тестирования вебхуков (продвинутый)
```bash
# Terminal 1: Запустите ngrok
ngrok http 8000
# Скопируйте URL (например: https://xxxx.ngrok-free.app)

# .env файл
PAYPAL_MODE=sandbox
PAYPAL_CLIENT_ID=<ваш_id>
PAYPAL_CLIENT_SECRET=<ваш_secret>
PAYMENT_PUBLIC_BASE_URL=https://xxxx.ngrok-free.app
PAYPAL_WEBHOOK_ID=<если есть, из PayPal Dashboard>
SUBSCRIPTION_PRICE_USD=9.99
```

---

## 🧪 Сценарии тестирования

### Сценарий 1: Успешный платеж (эмуляция)
```
1. Оставьте PAYPAL_CLIENT_SECRET пустым
2. Перейдите на /subscription/
3. Нажмите "Subscribe with PayPal"
4. Откроется эмулированная форма
5. Нажмите "Оплатить картой"
6. Вернетесь на страницу результата
7. ✅ Подписка активирована!
```

### Сценарий 2: Успешный платеж (PayPal Sandbox)
```
1. Установите CLIENT_ID и CLIENT_SECRET
2. Перейдите на /subscription/
3. Нажмите "Subscribe with PayPal"
4. Перенаправляет на paypal.sandbox.com
5. Логиньтесь: sb-xxxxx@personal.example.com
6. Нажимаете "Approve"
7. Вернетесь в COHUB
8. ✅ Подписка активирована!
```

### Сценарий 3: Отклоненный платеж
```
1. На эмулированной форме нажмите "Отклонить"
2. Платеж помечается как failed
3. ✅ Страница показывает: "Оплата отклонена"
4. Можете повторить попытку
```

---

## ⚠️ Типичные ошибки

| Ошибка | Причина | Решение |
|--------|---------|--------|
| "Invalid credentials" | Неправильный Client ID/Secret | Проверьте копию-пасту в PayPal Dashboard |
| Страница не открывается | PAYPAL_CLIENT_ID/SECRET не установлены | Оставьте пустыми для эмуляции ИЛИ установите оба |
| "Перенаправляет на EmptyPage" | Неправильное имя переменной | Убедитесь: `PAYPAL_CLIENT_SECRET=` (не `PASSWORD`) |
| PayPal возвращает ошибку | Неверный режим | Убедитесь: `PAYPAL_MODE=sandbox` для тестирования |

---

## 📊 Таблица вариантов конфигурации

| Что вы хотите | PAYPAL_MODE | CLIENT_ID | CLIENT_SECRET | Результат |
|---------------|-------------|-----------|---------------|-----------|
| Локальное тестирование | sandbox | ❌ пусто | ❌ пусто | Эмулированная форма |
| Тест с реальным PayPal | sandbox | ✅ есть | ✅ есть | Редирект на paypal.sandbox.com |
| Боевой сервер | live | ✅ есть | ✅ есть | Редирект на paypal.com (реальные платежи!) |

---

## 🎯 Рекомендуемая последовательность

### День 1: Тестирование локально
```bash
# .env: Оставьте PAYPAL_CLIENT_SECRET пустым
# Результат: Работает эмуляция, все тесты проходят
```

### День 2: Тестирование с PayPal API
```bash
# 1. Создайте app на https://developer.paypal.com
# 2. Скопируйте CLIENT_ID и SECRET в .env
# 3. Тестируйте с реальным PayPal sandbox
# Результат: Полная интеграция работает
```

### День 3: Подготовка к продакшену
```bash
# 1. Создайте live приложение (если готовы к платежам)
# 2. Скопируйте live CLIENT_ID и SECRET
# 3. Установите PAYPAL_MODE=live
# 4. Убедитесь что HTTPS включен
# 5. Разверните на сервер
# Результат: Реальные платежи начинают приходить
```

---

## 🔗 Быстрые ссылки

- 🌐 **PayPal Developer Dashboard**: https://developer.paypal.com/dashboard
- 📖 **API Documentation**: https://developer.paypal.com/docs/checkout/
- 🆘 **Support**: https://developer.paypal.com/contact

---

## ✅ Чек-лист для быстрого старта

- [ ] Выбрал вариант 1 (эмуляция) или вариант 2 (с PayPal)
- [ ] Обновил .env файл
- [ ] Перезапустил `python manage.py runserver`
- [ ] Открыл http://localhost:8000/subscription/
- [ ] Нажал "Subscribe with PayPal"
- [ ] Завершил платеж
- [ ] Проверил что подписка активирована ✅

**Все готово!** Платежи должны работать. 🚀
