"""Контекст-процессоры: значения, доступные во всех шаблонах."""

import json

from django.conf import settings
from django.utils.safestring import mark_safe

from .oauth import google_oauth_configured
from .captcha import recaptcha_configured, recaptcha_version
from . import analytics


# Экранирование символов, которыми можно «выйти» из <script> (XSS), при встраивании
# JSON прямо в тег. Те же замены делает django.utils.html.json_script. Имя (name) в
# person — пользовательский ввод (ФИО при регистрации), поэтому экранируем обязательно.
_JSON_SCRIPT_ESCAPES = {
    ord('>'): '\\u003e',
    ord('<'): '\\u003c',
    ord('&'): '\\u0026',
    0x2028: '\\u2028',  # LINE SEPARATOR — иначе ломает JS-строку
    0x2029: '\\u2029',  # PARAGRAPH SEPARATOR — иначе ломает JS-строку
}


def _json_for_script(value):
    """Безопасный JSON для вставки внутрь <script> (экранирует < > & и разделители)."""
    return mark_safe(json.dumps(value).translate(_JSON_SCRIPT_ESCAPES))


def oauth_flags(request):
    """Флаги для шаблонов: вход через Google и тип капчи (reCAPTCHA vs встроенная)."""
    return {
        'google_oauth_enabled': google_oauth_configured(),
        'recaptcha_enabled': recaptcha_configured(),
        'recaptcha_site_key': getattr(settings, 'RECAPTCHA_SITE_KEY', ''),
        'recaptcha_version': recaptcha_version(),
    }


def analytics_flags(request):
    """Данные для подключения posthog-js и identify в шаблонах.

    Если ключ не задан — posthog_enabled=False, и partials/posthog.html ничего
    не подключает (graceful no-op на клиенте). Для залогиненного пользователя
    отдаём готовый JSON для posthog.identify, чтобы события не «осиротели».
    """
    user = getattr(request, 'user', None)
    person = None
    distinct_id = ''
    if user is not None and getattr(user, 'is_authenticated', False):
        distinct_id = analytics.distinct_id_for(user)
        person = analytics.person_properties(user)

    return {
        'posthog_enabled': analytics.analytics_enabled(),
        'posthog_api_key': getattr(settings, 'POSTHOG_API_KEY', ''),
        'posthog_host': getattr(settings, 'POSTHOG_HOST', ''),
        'posthog_distinct_id': distinct_id,
        # XSS-safe JSON: name/email — пользовательский ввод, экранируем < > & и пр.
        'posthog_person_json': _json_for_script(person) if person else '',
    }
