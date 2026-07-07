"""PostHog-аналитика COHUB (веб-адаптация Week 5 deliverables).

Единая точка интеграции продуктовой аналитики. Главное свойство модуля —
**graceful no-op**: если `POSTHOG_API_KEY` не задан (или библиотека `posthog`
не установлена), все функции превращаются в безопасные пустышки, и приложение
работает ровно как раньше. Достаточно прописать ключ в .env — и события полетят
в PostHog без единой правки кода.

Чеклист Week 5 написан под Flutter-приложение; здесь те же идеи адаптированы под
веб:
  * users are identified            → identify_user() + клиентский posthog.identify
  * 10+ типов событий с platform    → EVENTS + capture_event(... platform='web')
  * conversion funnel install→pay   → FUNNEL_STEPS (signup → room → pay)
  * screen flow (Insights → Paths)  → $pageview автозахватом posthog-js
  * feature flag без редеплоя       → feature_enabled()

Серверные события (надёжные, их нельзя «срезать» блокировщиком) шлём отсюда.
Клиентские ($pageview, UI-клики, identify) — из templates/partials/posthog.html.
"""

import logging

from django.conf import settings

logger = logging.getLogger('cohub_app')

# Библиотека опциональна: без неё модуль продолжает работать как no-op.
try:
    import posthog as _posthog
except ImportError:  # pragma: no cover - окружение без установленного posthog
    _posthog = None

# Платформа, которую мы проставляем во все серверные события (аналог
# android/ios из мобильного чеклиста). У клиентских событий posthog-js
# проставляет её через register() в partials/posthog.html.
PLATFORM = 'web'


# ---------------------------------------------------------------------------
# Таксономия событий (event taxonomy). Один словарь — единственный источник
# правды и для кода, и для документации ANALYTICS.md.
# ---------------------------------------------------------------------------
EVENTS = {
    'user_signed_up': 'Пользователь завершил регистрацию',
    'user_logged_in': 'Пользователь вошёл в аккаунт',
    'room_created': 'Создана комната',
    'room_joined': 'Пользователь присоединился к комнате по коду',
    'task_created': 'Создана задача',
    'task_completed': 'Задача отмечена выполненной',
    'expense_added': 'Добавлен расход',
    'chat_message_sent': 'Отправлено сообщение в чат комнаты',
    'loan_created': 'Создан ручной долг',
    'subscription_viewed': 'Открыта страница подписки',
    'payment_started': 'Начата оплата (checkout)',
    'payment_completed': 'Оплата подтверждена',
    'payment_failed': 'Оплата отклонена',
    'subscription_activated': 'Активирована PRO-подписка',
    'subscription_cancelled': 'Подписка отменена',
}

# Воронка «как в чеклисте» install → payment, адаптированная под веб
# (install для сайта не существует, поэтому первый шаг — регистрация).
# Эти строки используются в ANALYTICS.md и при построении Funnel в PostHog.
FUNNEL_STEPS = [
    'user_signed_up',
    'room_created',
    'subscription_viewed',
    'payment_started',
    'payment_completed',
]

_initialized = False


def analytics_enabled():
    """True, если библиотека установлена и задан ключ проекта PostHog."""
    return bool(_posthog and getattr(settings, 'POSTHOG_API_KEY', ''))


def _client():
    """Лениво конфигурирует и возвращает модуль posthog, либо None (no-op)."""
    global _initialized
    if not analytics_enabled():
        return None
    if not _initialized:
        # В разных версиях SDK ключ читается из api_key / project_api_key —
        # выставляем оба, чтобы не зависеть от версии.
        _posthog.api_key = settings.POSTHOG_API_KEY
        _posthog.project_api_key = settings.POSTHOG_API_KEY
        _posthog.host = getattr(settings, 'POSTHOG_HOST', 'https://us.i.posthog.com')
        _posthog.disabled = False
        # debug=True помогает в dev: SDK печатает, что и куда отправил.
        _posthog.debug = bool(getattr(settings, 'DEBUG', False))
        _initialized = True
    return _posthog


def user_plan(user):
    """Текущий тариф пользователя для свойства person (free / trial / pro).

    Используется и для identify (PostHog Persons), и как property событий —
    чтобы можно было строить воронки и churn в разрезе плана.
    """
    if not user or not getattr(user, 'is_authenticated', False):
        return 'anonymous'
    subscription = getattr(user, 'subscription', None)
    if subscription is None:
        return 'free'
    status = subscription.status
    if status == 'active' and subscription.is_active:
        return 'pro'
    if status == 'trial' and subscription.is_active:
        return 'trial'
    return 'free'


def distinct_id_for(user):
    """Стабильный distinct_id = id пользователя.

    Один и тот же id и на сервере, и на клиенте (posthog.identify) — поэтому
    события логина не «осиротеют»: серверные и клиентские склеятся в одну
    Person в PostHog.
    """
    return str(getattr(user, 'id', '') or '')


def person_properties(user):
    """Свойства Person для вкладки PostHog → Persons (email, имя, план, роль).

    Если settings.POSTHOG_CAPTURE_PII=False — персональные данные (email/имя/
    username) не отправляются, остаются только обезличенные plan/role (GDPR-режим).
    """
    if not user or not getattr(user, 'is_authenticated', False):
        return {}
    profile = getattr(user, 'profile', None)
    props = {
        'plan': user_plan(user),
        'role': getattr(profile, 'role', 'user') if profile else 'user',
        'is_staff': bool(user.is_staff),
    }
    if getattr(settings, 'POSTHOG_CAPTURE_PII', True):
        props['email'] = user.email or user.username
        props['name'] = user.get_full_name() or user.username
        props['username'] = user.username
    return props


def identify_user(user):
    """Связать distinct_id с person-свойствами (email/имя/план).

    Гарантирует, что во вкладке Persons у залогиненного пользователя видны
    email, имя и план — то есть «no orphaned events» из чеклиста.
    """
    client = _client()
    if client is None or not getattr(user, 'is_authenticated', False):
        return
    try:
        client.identify(distinct_id_for(user), person_properties(user))
    except Exception:  # аналитика никогда не должна ронять бизнес-логику
        logger.exception('PostHog identify failed')


def capture_event(user, event, properties=None, distinct_id=None):
    """Отправить серверное событие в PostHog (безопасно, не бросает исключений).

    `event` обязан быть ключом из EVENTS — это защищает от опечаток в названиях
    событий и держит таксономию под контролем. В каждое событие добавляется
    platform='web' и план пользователя.
    """
    client = _client()
    if client is None:
        return
    if event not in EVENTS:
        # Лучше шумно залогировать, чем тихо засорять дашборд «левым» событием.
        logger.warning('Неизвестное событие аналитики: %s', event)

    props = dict(properties or {})
    props.setdefault('platform', PLATFORM)

    did = distinct_id or distinct_id_for(user)
    if not did:
        # Аноним без user.id — используем технический id, чтобы не терять событие.
        did = 'anonymous'

    if getattr(user, 'is_authenticated', False):
        props.setdefault('plan', user_plan(user))
        # $set приклеивает свежие person-свойства к каждому событию — Persons
        # всегда актуальны, даже если identify по какой-то причине не случился.
        props.setdefault('$set', person_properties(user))

    try:
        client.capture(did, event=event, properties=props)
    except Exception:
        logger.exception('PostHog capture failed (event=%s)', event)


def feature_enabled(flag_key, user, default=False):
    """Проверить feature flag PostHog для пользователя.

    Если аналитика выключена или PostHog не вернул значение — берём `default`
    (его можно задать в settings.FEATURE_FLAG_DEFAULTS). Так одну фичу можно
    включать/выключать прямо в интерфейсе PostHog без редеплоя, а при выключенной
    аналитике она управляется значением по умолчанию.
    """
    client = _client()
    if client is None:
        return default
    try:
        result = client.feature_enabled(flag_key, distinct_id_for(user) or 'anonymous')
    except Exception:
        logger.exception('PostHog feature_enabled failed (flag=%s)', flag_key)
        return default
    return default if result is None else bool(result)
