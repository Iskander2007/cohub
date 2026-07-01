"""Middleware безопасности: дополнительные HTTP-заголовки защиты.

Django через SecurityMiddleware уже умеет HSTS, nosniff, SSL-redirect и т.п.
Здесь добавляем заголовки, которых там нет:
  * Content-Security-Policy   — ограничивает источники скриптов/стилей/картинок
                                 (защита от XSS и внедрения постороннего контента);
  * Permissions-Policy        — отключает ненужные браузерные возможности
                                 (камера, микрофон, геолокация);
  * X-Content-Type-Options    — дублируем nosniff на всякий случай.

CSP по умолчанию разрешает 'unsafe-inline' для скриптов и стилей, потому что в
шаблонах проекта есть встроенные <script> и style-атрибуты. Значение можно
переопределить переменной окружения DJANGO_CSP.

Домены PostHog (для аналитики) добавляются в script-src/connect-src автоматически:
к облачным US/EU добавляется хост из settings.POSTHOG_HOST и его -assets вариант,
поэтому self-hosted/проксированный PostHog не блокируется CSP.
"""

import os

from django.conf import settings


def _posthog_csp_hosts():
    """Список origin'ов PostHog для CSP, исходя из настроенного POSTHOG_HOST.

    Всегда включаем облачные US/EU (на случай дефолтного хоста), плюс выводим из
    POSTHOG_HOST его assets-домен. Для облака `us.i.posthog.com` →
    `us-assets.i.posthog.com`; для self-hosted `ph.example.com` replace — no-op,
    поэтому добавляем сам хост (с него же грузится array.js и туда же шлются события).
    """
    hosts = {
        'https://us.i.posthog.com', 'https://eu.i.posthog.com',
        'https://us-assets.i.posthog.com', 'https://eu-assets.i.posthog.com',
    }
    configured = (getattr(settings, 'POSTHOG_HOST', '') or '').strip().rstrip('/')
    if configured:
        hosts.add(configured)
        hosts.add(configured.replace('.i.posthog.com', '-assets.i.posthog.com'))
    return sorted(hosts)


def _build_default_csp():
    """Собирает CSP по умолчанию, подставляя актуальные домены PostHog."""
    posthog = ' '.join(_posthog_csp_hosts())
    return (
        "default-src 'self'; "
        # Google reCAPTCHA грузит свой скрипт с www.google.com и www.gstatic.com.
        # PostHog грузит array.js с *-assets.i.posthog.com (или с self-hosted хоста).
        f"script-src 'self' 'unsafe-inline' https://www.google.com https://www.gstatic.com {posthog}; "
        "style-src 'self' 'unsafe-inline' https://www.gstatic.com; "
        "img-src 'self' data: https:; "
        "font-src 'self' data:; "
        # PostHog шлёт события на свой ingestion-домен (облако или self-hosted).
        f"connect-src 'self' {posthog}; "
        # Виджет reCAPTCHA («Я не робот») отрисовывается в iframe с www.google.com.
        "frame-src https://www.google.com; "
        "frame-ancestors 'none'; "
        "base-uri 'self'; "
        "form-action 'self'"
    )


PERMISSIONS_POLICY = 'geolocation=(), microphone=(), camera=(), payment=()'


class SecurityHeadersMiddleware:
    """Навешивает заголовки безопасности на каждый ответ."""

    def __init__(self, get_response):
        self.get_response = get_response
        # Явный DJANGO_CSP всегда побеждает; иначе собираем CSP с доменами PostHog.
        self.csp = os.environ.get('DJANGO_CSP') or _build_default_csp()

    def __call__(self, request):
        response = self.get_response(request)
        response.setdefault('Content-Security-Policy', self.csp)
        response.setdefault('Permissions-Policy', PERMISSIONS_POLICY)
        response.setdefault('X-Content-Type-Options', 'nosniff')
        return response
