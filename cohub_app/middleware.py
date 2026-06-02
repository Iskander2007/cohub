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
"""

import os

DEFAULT_CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: https:; "
    "font-src 'self' data:; "
    "connect-src 'self'; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "form-action 'self'"
)

PERMISSIONS_POLICY = 'geolocation=(), microphone=(), camera=(), payment=()'


class SecurityHeadersMiddleware:
    """Навешивает заголовки безопасности на каждый ответ."""

    def __init__(self, get_response):
        self.get_response = get_response
        self.csp = os.environ.get('DJANGO_CSP', DEFAULT_CSP)

    def __call__(self, request):
        response = self.get_response(request)
        response.setdefault('Content-Security-Policy', self.csp)
        response.setdefault('Permissions-Policy', PERMISSIONS_POLICY)
        response.setdefault('X-Content-Type-Options', 'nosniff')
        return response
