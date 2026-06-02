"""Вход через Google OAuth 2.0 (Authorization Code Flow).

Реализовано на стандартной библиотеке (urllib), без сторонних зависимостей.
Поток:
  1) google_login_view  — генерируем антифрод-параметр state, кладём его в сессию
     и перенаправляем пользователя на страницу согласия Google.
  2) google_callback_view — Google возвращает code + state. Проверяем state (защита
     от CSRF в OAuth), меняем code на access_token, запрашиваем профиль пользователя
     (email, имя), находим/создаём локального пользователя и логиним его.

Ключи приложения берутся из настроек (из переменных окружения):
  GOOGLE_OAUTH_CLIENT_ID, GOOGLE_OAUTH_CLIENT_SECRET.
Если они не заданы — кнопка входа через Google не показывается, а прямой переход
возвращает пользователя на обычную форму входа.
"""

import json
import secrets
import urllib.parse
import urllib.request

from django.conf import settings
from django.contrib.auth import login
from django.contrib.auth.models import User
from django.contrib import messages
from django.shortcuts import redirect
from django.urls import reverse

GOOGLE_AUTH_URL = 'https://accounts.google.com/o/oauth2/v2/auth'
GOOGLE_TOKEN_URL = 'https://oauth2.googleapis.com/token'
GOOGLE_USERINFO_URL = 'https://openidconnect.googleapis.com/v1/userinfo'

SESSION_STATE_KEY = 'google_oauth_state'


def google_oauth_configured():
    """True, если заданы оба ключа приложения Google."""
    return bool(settings.GOOGLE_OAUTH_CLIENT_ID and settings.GOOGLE_OAUTH_CLIENT_SECRET)


def _redirect_uri(request):
    """Абсолютный URL колбэка, который должен совпадать с настройкой в Google Console."""
    return request.build_absolute_uri(reverse('google-callback'))


def google_login_view(request):
    """Шаг 1: перенаправление на страницу согласия Google."""
    if not google_oauth_configured():
        messages.error(request, 'Вход через Google не настроен.')
        return redirect('login')

    # state — случайная строка против CSRF: вернётся от Google без изменений.
    state = secrets.token_urlsafe(32)
    request.session[SESSION_STATE_KEY] = state

    params = {
        'client_id': settings.GOOGLE_OAUTH_CLIENT_ID,
        'redirect_uri': _redirect_uri(request),
        'response_type': 'code',
        'scope': 'openid email profile',
        'state': state,
        'access_type': 'online',
        'prompt': 'select_account',
    }
    return redirect(f'{GOOGLE_AUTH_URL}?{urllib.parse.urlencode(params)}')


def _post_json(url, data):
    """POST form-urlencoded → распарсенный JSON-ответ."""
    body = urllib.parse.urlencode(data).encode('utf-8')
    req = urllib.request.Request(url, data=body, method='POST')
    req.add_header('Content-Type', 'application/x-www-form-urlencoded')
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode('utf-8'))


def _get_json(url, access_token):
    """GET с Bearer-токеном → распарсенный JSON-ответ (профиль пользователя)."""
    req = urllib.request.Request(url, method='GET')
    req.add_header('Authorization', f'Bearer {access_token}')
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode('utf-8'))


def google_callback_view(request):
    """Шаг 2: обработка ответа Google и вход пользователя."""
    if not google_oauth_configured():
        return redirect('login')

    if request.GET.get('error'):
        messages.error(request, 'Авторизация через Google отменена.')
        return redirect('login')

    # Проверка state (CSRF). pop — чтобы значение было одноразовым.
    expected_state = request.session.pop(SESSION_STATE_KEY, None)
    returned_state = request.GET.get('state')
    if not expected_state or expected_state != returned_state:
        messages.error(request, 'Ошибка проверки состояния OAuth (state).')
        return redirect('login')

    code = request.GET.get('code')
    if not code:
        messages.error(request, 'Google не вернул код авторизации.')
        return redirect('login')

    try:
        # Обмен кода на токен доступа.
        token_data = _post_json(GOOGLE_TOKEN_URL, {
            'code': code,
            'client_id': settings.GOOGLE_OAUTH_CLIENT_ID,
            'client_secret': settings.GOOGLE_OAUTH_CLIENT_SECRET,
            'redirect_uri': _redirect_uri(request),
            'grant_type': 'authorization_code',
        })
        access_token = token_data.get('access_token')
        if not access_token:
            raise ValueError('no access_token')

        # Запрос профиля пользователя.
        info = _get_json(GOOGLE_USERINFO_URL, access_token)
    except Exception:
        messages.error(request, 'Не удалось получить данные от Google. Попробуйте ещё раз.')
        return redirect('login')

    email = (info.get('email') or '').strip().lower()
    if not email or not info.get('email_verified', True):
        messages.error(request, 'Google не предоставил подтверждённый email.')
        return redirect('login')

    # username == email (как и в обычной регистрации проекта).
    user, created = User.objects.get_or_create(
        username=email,
        defaults={
            'email': email,
            'first_name': info.get('given_name', '') or '',
            'last_name': info.get('family_name', '') or '',
        },
    )
    if created:
        # Аккаунт создан через Google — локального пароля нет.
        user.set_unusable_password()
        user.save(update_fields=['password'])

    # Указываем backend явно: пользователь найден не через ModelBackend.authenticate.
    login(request, user, backend='django.contrib.auth.backends.ModelBackend')
    messages.success(request, 'Вы вошли через Google.')
    return redirect('dashboard')
