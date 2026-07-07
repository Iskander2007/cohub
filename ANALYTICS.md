# 📊 COHUB — Продуктовая аналитика (PostHog)

> Документ-аналог «Confluence: analytics doc» из чеклиста Week 5: таксономия
> событий + определения KPI + текущие числа. Чеклист написан под Flutter-приложение;
> здесь всё адаптировано под **веб** (Django + серверный рендеринг шаблонов).
> Мобильные пункты (APK/adb, android/ios, Flutter-экраны) заменены веб-аналогами.

---

## 1. Как это работает

Аналитика двухсторонняя:

| Сторона | Где живёт | Что шлёт |
|---|---|---|
| **Сервер** | `cohub_app/analytics.py` | Надёжные бизнес-события (регистрация, оплата, задачи…). Их не «срежет» блокировщик рекламы. |
| **Клиент** | `templates/partials/posthog.html` (posthog-js) | `$pageview` (screen flow), `identify`, `platform=web`, UI-события. |

**Главное свойство — graceful no-op.** Если `POSTHOG_API_KEY` пустой (или библиотека
`posthog` не установлена), вся аналитика превращается в безопасные пустышки: ни одного
внешнего запроса, приложение работает ровно как раньше. Достаточно прописать ключ —
и события полетят без единой правки кода.

### Как включить

1. Заведите бесплатный проект на <https://posthog.com> (ЕС-регион: <https://eu.posthog.com>).
2. **Project Settings → Project API Key** — это **публичный** ключ вида `phc_...`
   (его и положено отдавать в браузер; это не серверный секрет).
3. Пропишите в `.env`:
   ```env
   POSTHOG_API_KEY=phc_xxxxxxxxxxxxxxxxxxxxxxxxxxxx
   POSTHOG_HOST=https://us.i.posthog.com   # ЕС: https://eu.i.posthog.com
   ```
4. Перезапустите сервер. Зайдите на сайт → в PostHog **Activity → Live Events**
   начнут появляться события в реальном времени.

Настройки кода: `cohub_settings/settings.py` (блок `# --- PostHog ...`).
Зависимость: `requirements.txt` → `posthog==3.7.0`.

---

## 2. Таксономия событий (event taxonomy)

15 серверных типов событий + клиентский `$pageview`. Это **> 10** различных типов
(требование чеклиста). Источник правды в коде — словарь `EVENTS` в
`cohub_app/analytics.py`.

| # | Событие | Когда срабатывает | Где в коде |
|---|---|---|---|
| 1 | `user_signed_up` | Завершена регистрация | `views.py → register_view` |
| 2 | `user_logged_in` | Вход по email | `views.py → login_view` |
| 3 | `room_created` | Создана комната | `views.py → create_room_view` и `RoomViewSet.perform_create` |
| 4 | `room_joined` | Вход в комнату по коду | `views.py → join_room_view` и `RoomViewSet.join_room` |
| 5 | `task_created` | Создана задача | `views.py → TaskViewSet.perform_create` |
| 6 | `task_completed` | Задача завершена | `views.py → TaskViewSet.complete` |
| 7 | `expense_added` | Добавлен расход | `views.py → ExpenseViewSet.perform_create` |
| 8 | `chat_message_sent` | Сообщение в чат | `views.py → ChatMessageViewSet.perform_create` |
| 9 | `loan_created` | Создан ручной долг | `views.py → LoanViewSet.perform_create` |
| 10 | `subscription_viewed` | Открыта страница подписки | `views.py → subscription_view` |
| 11 | `payment_started` | Начат checkout | `payment_views.py → _start_payment` |
| 12 | `payment_completed` | Оплата подтверждена | `payment_views.py → process_callback` |
| 13 | `payment_failed` | Оплата отклонена | `payment_views.py → process_callback` |
| 14 | `subscription_activated` | Активирована PRO | `payment_views.py → _activate_subscription` |
| 15 | `subscription_cancelled` | Отмена подписки | `views.py → SubscriptionViewSet.cancel` |
| — | `$pageview` | Любой переход по страницам (клиент) | `templates/partials/posthog.html` |

### Свойство `platform`

Аналог `android/ios` из мобильного чеклиста. Проставляется **во все** события:
- сервер: `analytics.capture_event(...)` всегда добавляет `platform='web'`;
- клиент: `posthog.register({ platform: 'web' })` в `partials/posthog.html`.

В PostHog по нему можно фильтровать/группировать (Breakdown by `platform`).

Дополнительно к каждому событию приклеивается `plan` (free/trial/pro) и `$set`
с person-свойствами — это держит вкладку **Persons** актуальной.

---

## 3. Идентификация пользователей (Persons)

> Чеклист: «users are identified — Persons tab shows email, name, plan (no orphaned events)».

- `distinct_id = str(user.id)` — **одинаковый** на сервере и на клиенте, поэтому
  серверные и клиентские события склеиваются в одну Person (не «осиротеют»).
- При входе/регистрации вызывается `analytics.identify_user(user)`, который пишет
  в Person: `email`, `name`, `username`, `plan`, `role`.
- Клиент дублирует `posthog.identify(distinct_id, {email, name, plan, ...})` в
  `partials/posthog.html`.

Код: `analytics.identify_user`, `analytics.person_properties`, `analytics.distinct_id_for`.

**Где смотреть:** PostHog → **Persons** → у залогиненного пользователя видны email, имя, plan.

---

## 4. Воронка конверсии (conversion funnel)

> Чеклист: «% drop-off at each step from install to payment». Для веба «install»
> не существует, поэтому первый шаг — регистрация.

Шаги (константа `FUNNEL_STEPS` в `analytics.py`):

```
user_signed_up → room_created → subscription_viewed → payment_started → payment_completed
```

**Как построить в PostHog (UI, 2 минуты):**
1. **Product Analytics → New insight → Funnel**.
2. Добавьте 5 шагов в порядке выше.
3. PostHog покажет % drop-off на каждом шаге. Готово.

Код только генерирует события; саму воронку рисуют в интерфейсе PostHog.

---

## 5. Screen flow (Insights → Paths)

> Чеклист: «Insights → Paths shows screen navigation from the app».

posthog-js включён с `capture_pageview: true` → автоматически шлёт `$pageview`
на каждый переход. В PostHog: **Product Analytics → Paths** — увидите граф
переходов между страницами (`/`, `/account/login/`, `/dashboard/`, `/subscription/`,
`/payments/...` и т.д.).

Код: `templates/partials/posthog.html` (`capture_pageview: true`, `capture_pageleave: true`).

---

## 6. Feature flag без редеплоя

> Чеклист: «one screen/feature toggles by flag without a redeploy».

Реализован флаг **`pro-upsell-banner`** — промо-баннер «Перейти на PRO» на дашборде.

- Сервер спрашивает PostHog: `analytics.feature_enabled('pro-upsell-banner', user, default=...)`
  в `views.py → dashboard_view`.
- Шаблон рисует баннер по `show_pro_banner` в `templates/dashboard.html`.
- **Переключение без редеплоя:** в PostHog → **Feature Flags** → создайте флаг с
  ключом `pro-upsell-banner` → включайте/выключайте/раскатывайте на % аудитории.
  Баннер появляется/исчезает без передеплоя приложения.
- Без аналитики (нет ключа) флаг управляется значением по умолчанию
  `settings.FEATURE_FLAG_DEFAULTS['pro-upsell-banner']` (env `FLAG_PRO_UPSELL_BANNER`).

---

## 7. Live Events (real-time)

> Чеклист (мобильный): «install APK via adb, confirm all 10+ event types appear in
> real-time dashboard». Веб-аналог: **никакого APK не нужно.**

1. Включите ключ (раздел 1).
2. Откройте сайт и поделайте действия: зарегистрируйтесь, создайте комнату,
   добавьте задачу/расход, откройте подписку, пройдите sandbox-оплату.
3. В PostHog → **Activity → Live Events** — все 15 типов событий появляются в
   реальном времени с `platform=web`.

---

## 8. KPI-метрики

> Чеклист: «conversion rate, MRR, churn — show the numbers (even if small)».

Считаются из **реальных данных** (модели `Subscription`, `Order`, `User`) функцией
`compute_kpis()` в `cohub_app/views.py`.

| Метрика | Формула | Смысл |
|---|---|---|
| **Conversion rate** | PRO-пользователи / все пользователи × 100% | Доля доведённых до платной подписки |
| **MRR** | Σ(сумма оплаты / месяцев) по оплатам за 30 дней | Месячная регулярная выручка |
| **ARPU** | MRR / число PRO | Средний доход на платящего |
| **Churn rate** | (отменили + истекли) / (PRO + отменили) × 100% | Отток |

> Формулы намеренно простые (snapshot, а не когортный анализ) и задокументированы здесь.

### Где смотреть

- **Веб-дашборд:** `/analytics/kpi/` (только для staff/админа). В коде —
  `views.py → kpi_dashboard_view`, шаблон `templates/kpi_dashboard.html`.
  Ссылка «📊 KPI» в сайдбаре главной появляется у админов.
- **CLI:** `python manage.py kpi_report` (или `--json`, `--days 7`).

### Текущие числа (пример снимка)

```json
{
  "total_users": 4,
  "pro_users": 1,
  "conversion_rate": 25.0,
  "mrr": 15029.97,
  "arpu": 15029.97,
  "churn_rate": 0.0,
  "paid_orders_30d": 6,
  "currency": "KZT"
}
```

*(Числа маленькие — это нормально для учебного проекта; важно, что считается из живых данных.)*

---

## 8.1. Приватность и данные (GDPR)

С включённым ключом в PostHog уходят персональные данные (email, имя) — это нужно
для пункта «Persons show email/name». Что предусмотрено:

- **`POSTHOG_CAPTURE_PII=False`** — приватный режим: в PostHog уходят только
  обезличенные `plan`/`role`, без email/имени/username (см. `person_properties`).
- **Do-Not-Track** — клиент инициализируется с `respect_dnt: true`: если у
  пользователя включён DNT в браузере, posthog-js его не отслеживает.
- **Регион данных** — для пользователей из ЕС ставьте `POSTHOG_HOST=https://eu.i.posthog.com`,
  чтобы данные хранились в ЕС.
- **Поток данных:** браузер → PostHog (`$pageview`, identify, UI-события);
  сервер Django → PostHog (бизнес-события). Без ключа — никуда (no-op).

> Для продакшена с реальными пользователями из ЕС добавьте баннер согласия
> (cookie consent) и включайте аналитику после согласия — текущая реализация
> уважает DNT и умеет приватный режим, но полноценного consent-gate не содержит.

---

## 9. Соответствие 9 пунктам Week 5

| # | Пункт чеклиста | Статус | Что сделано / что осталось |
|---|---|---|---|
| 1 | Users identified (email/name/plan) | ✅ Код готов | `identify_user`; в PostHog → Persons после входа |
| 2 | 10+ типов событий + platform | ✅ Код готов | 15 серверных событий + `$pageview`, у всех `platform=web` |
| 3 | Conversion funnel install→pay | ✅ События есть / 🖱 воронка в UI | `FUNNEL_STEPS`; собрать Funnel в PostHog (раздел 4) |
| 4 | Screen flow (Paths) | ✅ Код готов / 🖱 смотреть в UI | автозахват `$pageview` → Paths |
| 5 | Feature flag без редеплоя | ✅ Код готов | флаг `pro-upsell-banner` (раздел 6) |
| 6 | Live Events через APK/adb | 🔁 Веб-аналог | APK не нужен; Live Events для веба (раздел 7) |
| 7 | KPI: conversion/MRR/churn | ✅ Код готов | `/analytics/kpi/` + `kpi_report` (раздел 8) |
| 8 | Confluence: analytics doc | ✅ Этот файл | таксономия + KPI с числами |
| 9 | Jira: ANA tickets Done | ⛔ Вне кода | задачи закрываются в Jira со скриншотами дашборда |

Легенда: ✅ готово в коде · 🖱 нужно один раз настроить в интерфейсе PostHog ·
🔁 заменено веб-аналогом · ⛔ внешний инструмент.

---

## 10. Карта файлов

```
cohub_app/analytics.py                      # ядро: EVENTS, capture_event, identify_user, feature_enabled, compute-хелперы
cohub_app/context_processors.py             # analytics_flags → прокидывает ключ/identify в шаблоны (+ XSS-экранирование)
cohub_app/middleware.py                     # CSP расширён под домены PostHog (US+EU)
cohub_app/views.py                          # capture_event в бизнес-вьюхах; compute_kpis; kpi_dashboard_view; feature flag
cohub_app/payment_views.py                  # события оплаты (started/completed/failed/activated)
cohub_app/management/commands/kpi_report.py # KPI в консоль/JSON
cohub_settings/settings.py                  # POSTHOG_API_KEY/HOST, FEATURE_FLAG_DEFAULTS
cohub_settings/urls.py                      # маршрут /analytics/kpi/
templates/partials/posthog.html             # posthog-js: init, identify, register platform, $pageview
templates/base.html                         # подключает partials/posthog.html
templates/dashboard.html                    # баннер под feature flag
templates/kpi_dashboard.html                # страница KPI
.env.example                                # POSTHOG_* переменные
```

---

## 11. Как показать на демо (frontend)

1. **Без ключа** — открой сайт: всё работает, аналитики нет (no-op). Покажи, что
   в исходнике страницы нет `posthog.init` (graceful degradation).
2. **С ключом** — пропиши `POSTHOG_API_KEY`, перезапусти:
   - зарегистрируйся → в PostHog **Live Events** видно `user_signed_up`;
   - создай комнату, задачу, расход, открой подписку, пройди sandbox-оплату →
     события сыпятся в реальном времени, у всех `platform=web`;
   - **Persons** → у тебя email/имя/plan;
   - **Paths** → граф переходов по страницам;
   - собери **Funnel** по `FUNNEL_STEPS` → drop-off по шагам;
   - в **Feature Flags** создай `pro-upsell-banner`, включи → на `/dashboard/`
     появляется промо-баннер; выключи → пропадает (без редеплоя);
   - открой `/analytics/kpi/` (под staff-аккаунтом) → conversion/MRR/churn числами.
