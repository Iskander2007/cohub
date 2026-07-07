"""
Django settings for cohub project.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


def env_bool(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {'1', 'true', 'yes', 'on'}


def env_list(name, default=None):
    value = os.environ.get(name)
    if value is None:
        return default or []
    return [item.strip() for item in value.split(',') if item.strip()]

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent


# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = env_bool('DJANGO_DEBUG', default=False)

# SECURITY WARNING: keep the secret key used in production secret!
# Pull from environment variable for safety, default to the insecure string for dev.
SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', 'django-insecure-your-secret-key-change-in-production')

# Explicit host allow-list prevents host header abuse in production.
# `host.docker.internal` в дефолте нужен для локального стека мониторинга:
# Prometheus в контейнере скрейпит приложение на хосте по этому имени, и без него
# Django вернул бы 400 DisallowedHost на каждый scrape. В проде список задаётся
# через DJANGO_ALLOWED_HOSTS (render.yaml) и этого имени не содержит.
ALLOWED_HOSTS = env_list('DJANGO_ALLOWED_HOSTS', ['localhost', '127.0.0.1', 'host.docker.internal'])
CSRF_TRUSTED_ORIGINS = env_list(
    'DJANGO_CSRF_TRUSTED_ORIGINS',
    ['http://localhost:8000', 'http://127.0.0.1:8000'],
)



# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'cohub_app',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    # WhiteNoise should be placed after SecurityMiddleware but before all other middlewares.
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    # Доп. заголовки безопасности: CSP, Permissions-Policy, nosniff.
    'cohub_app.middleware.SecurityHeadersMiddleware',
    # Мониторинг метрик и логирование
    'cohub_app.metrics_middleware.MetricsMiddleware',
]

ROOT_URLCONF = 'cohub_settings.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [os.path.join(BASE_DIR, 'templates')],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'cohub_app.context_processors.oauth_flags',
                # Прокидывает в шаблоны флаги PostHog (ключ, host, identify-данные).
                'cohub_app.context_processors.analytics_flags',
            ],
        },
    },
]

WSGI_APPLICATION = 'cohub_settings.wsgi.application'


# Database

# On platforms like Railway a DATABASE_URL environment variable will be provided.
# We use dj-database-url to parse it; fall back to SQLite for local development.
import dj_database_url

DATABASES = {
    'default': dj_database_url.config(
        default=f"sqlite:///{os.path.join(BASE_DIR, 'db.sqlite3')}"
    )
}

DATABASES['default']['CONN_MAX_AGE'] = int(os.environ.get('DJANGO_DB_CONN_MAX_AGE', '60'))


# Cache
REDIS_URL = os.environ.get('REDIS_URL')
if REDIS_URL:
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.redis.RedisCache',
            'LOCATION': REDIS_URL,
        }
    }
else:
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
            'LOCATION': 'cohub-local-cache',
        }
    }


# Celery: фоновые задачи через брокер Redis.
# Брокер и backend по умолчанию берут REDIS_URL; если Redis нет — включаем
# EAGER-режим (задачи выполняются синхронно), чтобы локальная разработка и
# тесты работали без брокера.
CELERY_BROKER_URL = os.environ.get('CELERY_BROKER_URL', REDIS_URL or 'memory://')
CELERY_RESULT_BACKEND = os.environ.get('CELERY_RESULT_BACKEND', REDIS_URL or '')
CELERY_TASK_ALWAYS_EAGER = env_bool('CELERY_TASK_ALWAYS_EAGER', default=not bool(REDIS_URL))
CELERY_TASK_EAGER_PROPAGATES = True
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
# TIME_ZONE задаётся ниже в этом файле; берём тот же литерал, чтобы часовой пояс
# Celery всегда совпадал с Django независимо от env (и порядка определения).
CELERY_TIMEZONE = 'Europe/Moscow'
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True



AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
        # A07: явно требуем не короче 8 символов.
        'OPTIONS': {'min_length': 8},
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# Internationalization

LANGUAGE_CODE = 'ru'

TIME_ZONE = 'Europe/Moscow'

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)

STATIC_URL = '/static/'
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')
STATICFILES_DIRS = [os.path.join(BASE_DIR, 'static')]
# Use WhiteNoise storage backend so the static files can be served directly by the
# WSGI app (Heroku, Railway, etc.) and are compressed with a hash-based name.
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

# Media files
MEDIA_URL = '/media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')

# Security hardening defaults that are safe for local development.
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = 'same-origin'
SECURE_CROSS_ORIGIN_OPENER_POLICY = 'same-origin'
X_FRAME_OPTIONS = 'DENY'
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
CSRF_COOKIE_SAMESITE = 'Lax'
# A07: ограничиваем срок жизни сессии и продлеваем его при активности
# (скользящее окно). По умолчанию — 2 недели, можно переопределить через env.
SESSION_COOKIE_AGE = int(os.environ.get('DJANGO_SESSION_COOKIE_AGE', str(60 * 60 * 24 * 14)))
SESSION_SAVE_EVERY_REQUEST = True
SECURE_SSL_REDIRECT = env_bool('DJANGO_SECURE_SSL_REDIRECT', default=False)
SESSION_COOKIE_SECURE = env_bool('DJANGO_SESSION_COOKIE_SECURE', default=SECURE_SSL_REDIRECT)
CSRF_COOKIE_SECURE = env_bool('DJANGO_CSRF_COOKIE_SECURE', default=SECURE_SSL_REDIRECT)
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SECURE_HSTS_SECONDS = int(os.environ.get('DJANGO_SECURE_HSTS_SECONDS', '0'))
SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool('DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS', default=False)
SECURE_HSTS_PRELOAD = env_bool('DJANGO_SECURE_HSTS_PRELOAD', default=False)

# Опциональная защита эндпоинтов метрик (/api/metrics, /api/metrics/prometheus,
# /api/metrics/summary). Пусто (по умолчанию) → метрики открыты: локальный стек
# Prometheus+Grafana скрейпит их без токена. На публичном проде (Render) задайте
# METRICS_TOKEN — тогда эндпоинты потребуют '?token=<...>' или заголовок
# 'Authorization: Bearer <...>', чтобы не раскрывать бизнес-метрики (платежи,
# нагрузку, CPU/RAM) анонимным пользователям. /health/ остаётся открытым всегда.
METRICS_TOKEN = os.environ.get('METRICS_TOKEN', '')

LOGIN_URL = '/account/login/'
LOGIN_REDIRECT_URL = '/account/'
LOGOUT_REDIRECT_URL = '/'

# Google OAuth 2.0. Ключи берём из окружения; если пусто — вход через Google
# просто не предлагается (см. cohub_app/oauth.py).
GOOGLE_OAUTH_CLIENT_ID = os.environ.get('GOOGLE_OAUTH_CLIENT_ID', '')
GOOGLE_OAUTH_CLIENT_SECRET = os.environ.get('GOOGLE_OAUTH_CLIENT_SECRET', '')

# Google reCAPTCHA ("Я не робот"). Если оба ключа заданы — на формах входа и
# регистрации показывается виджет Google; если пусто — используется встроенная
# арифметическая капча (работает офлайн). Ключи: https://www.google.com/recaptcha/admin
RECAPTCHA_SITE_KEY = os.environ.get('RECAPTCHA_SITE_KEY', '')
RECAPTCHA_SECRET_KEY = os.environ.get('RECAPTCHA_SECRET_KEY', '')
# Версия reCAPTCHA: 'v2' (чекбокс «Я не робот») или 'v3' (невидимая, по score).
RECAPTCHA_VERSION = os.environ.get('RECAPTCHA_VERSION', 'v2').strip().lower()
# Минимальный score для reCAPTCHA v3 (0.0–1.0). Ниже порога запрос отклоняется.
RECAPTCHA_MIN_SCORE = float(os.environ.get('RECAPTCHA_MIN_SCORE', '0.5'))

# --- Платежи (PAY-002…PAY-006) ---------------------------------------------
# Цена PRO-подписки за месяц. Bereke принимает тенге, PayPal — доллары.
SUBSCRIPTION_PRICE_KZT = os.environ.get('SUBSCRIPTION_PRICE_KZT', '5000')
SUBSCRIPTION_PRICE_USD = os.environ.get('SUBSCRIPTION_PRICE_USD', '9.99')

# Публичный базовый URL для колбэков провайдеров. Для локального теста колбэка
# через ngrok (PAY-003) пропишите сюда ngrok-адрес, например
# https://xxxx.ngrok-free.app — провайдер должен достучаться до /payments/callback/.
PAYMENT_PUBLIC_BASE_URL = os.environ.get('PAYMENT_PUBLIC_BASE_URL', '')

# Bereke Bank ePay (PAY-002/PAY-003). Если BEREKE_SANDBOX=True или нет
# BEREKE_CLIENT_SECRET — используется встроенная sandbox-эмуляция формы оплаты.
BEREKE_SANDBOX = env_bool('BEREKE_SANDBOX', default=True)
BEREKE_API_BASE = os.environ.get('BEREKE_API_BASE', 'https://testoauth.homebank.kz')
BEREKE_CLIENT_ID = os.environ.get('BEREKE_CLIENT_ID', '')
BEREKE_CLIENT_SECRET = os.environ.get('BEREKE_CLIENT_SECRET', '')
BEREKE_TERMINAL = os.environ.get('BEREKE_TERMINAL', '')
# Секрет для проверки подписи колбэка (HMAC-SHA256).
BEREKE_CALLBACK_SECRET = os.environ.get('BEREKE_CALLBACK_SECRET', 'bereke-sandbox-secret')

# PayPal REST (PAY-006). PAYPAL_MODE=sandbox|live. Без PAYPAL_CLIENT_SECRET
# используется встроенная sandbox-эмуляция.
PAYPAL_MODE = os.environ.get('PAYPAL_MODE', 'sandbox')
PAYPAL_CLIENT_ID = os.environ.get('PAYPAL_CLIENT_ID', '')
PAYPAL_CLIENT_SECRET = os.environ.get('PAYPAL_CLIENT_SECRET', '')
PAYPAL_WEBHOOK_ID = os.environ.get('PAYPAL_WEBHOOK_ID', '')
PAYPAL_WEBHOOK_SECRET = os.environ.get('PAYPAL_WEBHOOK_SECRET', 'paypal-sandbox-secret')

# --- PostHog продуктовая аналитика (Week 5) --------------------------------
# Адаптация Flutter-чеклиста под веб. Без POSTHOG_API_KEY вся аналитика —
# graceful no-op (см. cohub_app/analytics.py), приложение работает как обычно.
# Где взять ключ: https://posthog.com → Project settings → Project API Key
# (формат phc_...). POSTHOG_HOST — регион вашего проекта:
#   США: https://us.i.posthog.com   ЕС: https://eu.i.posthog.com
POSTHOG_API_KEY = os.environ.get('POSTHOG_API_KEY', '')
POSTHOG_HOST = os.environ.get('POSTHOG_HOST', 'https://us.i.posthog.com')

# --- Google Analytics 4 (gtag.js) -----------------------------------------
# ID измерения формата G-XXXXXXXXXX. Без него partials/google_analytics.html
# ничего не подключает (graceful no-op, как у PostHog). Значение по умолчанию —
# ID проекта COHUB; переопределяется переменной окружения GOOGLE_ANALYTICS_ID.
GOOGLE_ANALYTICS_ID = os.environ.get('GOOGLE_ANALYTICS_ID', 'G-WZX3KZ8ZV6')

# Курс USD→KZT для сведе́ния KPI к одной валюте. Заказы Bereke в тенге, PayPal —
# в долларах; без конвертации MRR/ARPU складывали бы 9.99 и 5000 как одну валюту
# и давали бы неверное число. Это приблизительный конфиг-курс (не биржевой);
# при необходимости задайте актуальный через env USD_TO_KZT_RATE.
USD_TO_KZT_RATE = float(os.environ.get('USD_TO_KZT_RATE', '475'))

# Приватность: отправлять ли в PostHog персональные данные (email, имя, username).
# True (по умолчанию) — вкладка Persons показывает email/имя (требование Week 5).
# False — в PostHog уходят только обезличенные plan/role (для GDPR-чувствительных
# инсталляций). Клиент дополнительно уважает заголовок Do-Not-Track (respect_dnt).
POSTHOG_CAPTURE_PII = env_bool('POSTHOG_CAPTURE_PII', default=True)

# Значения feature-флагов по умолчанию — используются, когда аналитика
# выключена (нет ключа) либо PostHog не вернул значение флага. С заданным ключом
# реальные значения берутся из PostHog и меняются без редеплоя.
FEATURE_FLAG_DEFAULTS = {
    # Промо-баннер «перейти на PRO» на дашборде. В PostHog заводится флаг с тем
    # же ключом 'pro-upsell-banner'; здесь — поведение по умолчанию.
    'pro-upsell-banner': env_bool('FLAG_PRO_UPSELL_BANNER', default=True),
}

# Limit oversized requests and uploads to reduce abuse and accidental resource exhaustion.
DATA_UPLOAD_MAX_MEMORY_SIZE = int(os.environ.get('DJANGO_DATA_UPLOAD_MAX_MEMORY_SIZE', str(2_621_440)))
FILE_UPLOAD_MAX_MEMORY_SIZE = int(os.environ.get('DJANGO_FILE_UPLOAD_MAX_MEMORY_SIZE', str(2_097_152)))
AVATAR_MAX_UPLOAD_SIZE = int(os.environ.get('DJANGO_AVATAR_MAX_UPLOAD_SIZE', str(FILE_UPLOAD_MAX_MEMORY_SIZE)))

# Simple brute-force and API abuse controls.
LOGIN_RATE_LIMIT = int(os.environ.get('DJANGO_LOGIN_RATE_LIMIT', '5'))
LOGIN_RATE_LIMIT_WINDOW = int(os.environ.get('DJANGO_LOGIN_RATE_LIMIT_WINDOW', '300'))
API_THROTTLE_ANON = os.environ.get('DJANGO_API_THROTTLE_ANON', '30/min')
API_THROTTLE_USER = os.environ.get('DJANGO_API_THROTTLE_USER', '120/min')

# Default primary key field type

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# REST Framework settings
REST_FRAMEWORK = {
    # A07: только сессионная аутентификация. BasicAuthentication убрана —
    # она передаёт логин/пароль в каждом запросе (риск перехвата и подбора).
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework.authentication.SessionAuthentication',
    ],
    # RBAC: по умолчанию любой эндпоинт требует аутентификации (роль user).
    # Эндпоинты только для админов отдельно используют permissions.IsAdminRole.
    'DEFAULT_PERMISSION_CLASSES': [
        'cohub_app.permissions.IsAuthenticatedUser',
    ],
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 10,
    'DEFAULT_FILTER_BACKENDS': ['rest_framework.filters.SearchFilter'],
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.AnonRateThrottle',
        'rest_framework.throttling.UserRateThrottle',
    ],
    'DEFAULT_THROTTLE_RATES': {
        'anon': API_THROTTLE_ANON,
        'user': API_THROTTLE_USER,
    },
}

# ===========================================================================
# Логирование: JSON логирование для платежей и операций
# ===========================================================================
LOGS_DIR = os.path.join(BASE_DIR, 'logs')
os.makedirs(LOGS_DIR, exist_ok=True)

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'json': {
            '()': 'cohub_app.logging_utils.JSONFormatter',
        },
        'verbose': {
            'format': '[{levelname}] {asctime} {name} {message}',
            'style': '{',
        },
    },
    'handlers': {
        # JSON логирование платежей в файл
        'payment_json_file': {
            'level': 'INFO',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': os.path.join(LOGS_DIR, 'payments.json'),
            'maxBytes': 10 * 1024 * 1024,  # 10 MB
            'backupCount': 10,
            'formatter': 'json',
        },
        # JSON логирование ошибок в файл
        'errors_json_file': {
            'level': 'ERROR',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': os.path.join(LOGS_DIR, 'errors.json'),
            'maxBytes': 10 * 1024 * 1024,  # 10 MB
            'backupCount': 10,
            'formatter': 'json',
        },
        # JSON логирование обращений к ключевым endpoint'ам (API/платежи/auth/health).
        # По одной строке на запрос: method, path, status, latency_ms, user_id, request_id.
        'requests_json_file': {
            'level': 'INFO',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': os.path.join(LOGS_DIR, 'requests.json'),
            'maxBytes': 10 * 1024 * 1024,  # 10 MB
            'backupCount': 10,
            'formatter': 'json',
        },
        # Консоль для development
        'console': {
            'level': 'DEBUG' if DEBUG else 'INFO',
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
    },
    'loggers': {
        'cohub.payments': {
            'handlers': ['payment_json_file', 'console'],
            'level': 'INFO',
            'propagate': False,
        },
        # Структурированный лог обращений к ключевым endpoint'ам.
        # 5xx также дублируются в errors.json через корневой обработчик cohub_app,
        # поэтому здесь дополнительно подключаем errors_json_file.
        'cohub.requests': {
            'handlers': ['requests_json_file', 'errors_json_file'],
            'level': 'INFO',
            'propagate': False,
        },
        'cohub_app': {
            'handlers': ['console', 'errors_json_file'],
            'level': 'DEBUG' if DEBUG else 'INFO',
            'propagate': False,
        },
        'django': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
    },
}


# ===========================================================================
# Тестовый режим
# ===========================================================================
# Под тестами (manage.py test ИЛИ pytest) отключаем ManifestStaticFilesStorage:
# он требует заранее собранного манифеста (collectstatic) и иначе роняет любой
# рендер шаблона с {% static %} ошибкой "Missing staticfiles manifest entry".
# Для тестов достаточно простого хранилища без хэш-манифеста.
import sys as _sys

_RUNNING_TESTS = (
    'test' in _sys.argv
    or 'pytest' in os.path.basename(_sys.argv[0] if _sys.argv else '')
    or bool(os.environ.get('PYTEST_CURRENT_TEST'))
    or env_bool('DJANGO_TESTING', default=False)
)

if _RUNNING_TESTS:
    # Базовый файл уже задаёт STATICFILES_STORAGE (старый стиль), поэтому здесь
    # только ПЕРЕОПРЕДЕЛЯЕМ его (нельзя одновременно объявлять STORAGES —
    # Django 5 считает их взаимоисключающими).
    STATICFILES_STORAGE = 'whitenoise.storage.CompressedStaticFilesStorage'

