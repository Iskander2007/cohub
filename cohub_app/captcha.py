"""CAPTCHA для форм регистрации и входа.

Реализована встроенная арифметическая CAPTCHA, не требующая внешних сервисов и
ключей, — поэтому она работает офлайн, в тестах и в CI. Вопрос и правильный ответ
хранятся в серверной сессии (пользователь видит только текст вопроса), что
защищает от автоматических ботов при регистрации и брутфорса при входе.

Если в окружении заданы ключи Google reCAPTCHA
(RECAPTCHA_SITE_KEY / RECAPTCHA_SECRET_KEY), можно подключить и её — для учебного
проекта по умолчанию используется встроенный вариант.
"""

import json
import secrets
import urllib.parse
import urllib.request

from django.conf import settings

# Ключи в сессии, под которыми храним правильный ответ и сам вопрос.
SESSION_ANSWER_KEY = 'captcha_answer'
SESSION_QUESTION_KEY = 'captcha_question'

# Адрес проверки токена Google reCAPTCHA v2 на стороне сервера.
RECAPTCHA_VERIFY_URL = 'https://www.google.com/recaptcha/api/siteverify'


def recaptcha_configured():
    """True, если заданы оба ключа Google reCAPTCHA (site + secret).

    Если ключи есть — на формах показываем виджет «Я не робот» (как у Google);
    если нет — используем встроенную арифметическую CAPTCHA (офлайн-режим).
    """
    return bool(
        getattr(settings, 'RECAPTCHA_SITE_KEY', '')
        and getattr(settings, 'RECAPTCHA_SECRET_KEY', '')
    )


def recaptcha_version():
    """Версия reCAPTCHA: 'v2' (чекбокс) или 'v3' (невидимая, по score).

    Управляется переменной RECAPTCHA_VERSION. От версии зависит и фронтенд
    (чекбокс vs фоновый grecaptcha.execute), и серверная проверка (для v3
    дополнительно проверяется оценка score).
    """
    return (getattr(settings, 'RECAPTCHA_VERSION', 'v2') or 'v2').strip().lower()


def _client_ip(request):
    """IP клиента (для передачи Google как доп. сигнал). За прокси — первый из XFF."""
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR', '')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')


def verify_recaptcha(request, expected_action=None):
    """Проверить токен Google reCAPTCHA, пришедший с формой.

    Браузер кладёт результат в скрытое поле `g-recaptcha-response`; мы отправляем
    его вместе с секретным ключом на сервер Google.

    Для v2 достаточно поля `success`. Для v3 ответ дополнительно содержит `score`
    (0.0–1.0, насколько запрос похож на человека) и `action` — проверяем, что
    оценка не ниже порога RECAPTCHA_MIN_SCORE и действие совпадает с ожидаемым.
    Любая сетевая ошибка трактуется как непрохождение проверки (fail-closed).
    """
    token = request.POST.get('g-recaptcha-response', '')
    if not token:
        return False

    data = {
        'secret': settings.RECAPTCHA_SECRET_KEY,
        'response': token,
    }
    ip = _client_ip(request)
    if ip:
        data['remoteip'] = ip

    try:
        body = urllib.parse.urlencode(data).encode('utf-8')
        req = urllib.request.Request(RECAPTCHA_VERIFY_URL, data=body, method='POST')
        req.add_header('Content-Type', 'application/x-www-form-urlencoded')
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read().decode('utf-8'))
    except Exception:
        return False

    if not result.get('success'):
        return False

    # v3: Google присылает score и action — проверяем их дополнительно.
    if 'score' in result:
        min_score = float(getattr(settings, 'RECAPTCHA_MIN_SCORE', 0.5))
        try:
            if float(result.get('score', 0)) < min_score:
                return False
        except (TypeError, ValueError):
            return False
        action = result.get('action')
        if expected_action and action and action != expected_action:
            return False

    return True


def generate_captcha(request):
    """Сгенерировать новую CAPTCHA, положить ответ в сессию и вернуть вопрос.

    Используем модуль secrets (криптостойкий генератор), чтобы значения нельзя
    было предугадать. Возвращаем строку-вопрос для показа в шаблоне.
    """
    a = secrets.randbelow(9) + 1   # 1..9
    b = secrets.randbelow(9) + 1   # 1..9
    question = f'Сколько будет {a} + {b}?'
    request.session[SESSION_ANSWER_KEY] = a + b
    request.session[SESSION_QUESTION_KEY] = question
    return question


def get_captcha_question(request):
    """Вернуть текущий вопрос из сессии или сгенерировать новый, если его нет."""
    return request.session.get(SESSION_QUESTION_KEY) or generate_captcha(request)


def validate_captcha(request, answer=None, action=None):
    """Проверить пройденную пользователем CAPTCHA.

    Если настроена Google reCAPTCHA — проверяем её токен на сервере Google
    (для v3 `action` помогает убедиться, что токен сгенерирован на нужной форме).
    Иначе используем встроенную арифметическую капчу: ответ одноразовый — после
    проверки (успешной или нет) он удаляется из сессии, чтобы один и тот же ответ
    нельзя было переиспользовать (replay). Возвращает True/False.
    """
    # Приоритет — Google reCAPTCHA, если она настроена ключами в окружении.
    if recaptcha_configured():
        return verify_recaptcha(request, expected_action=action)

    # Откат: арифметическая капча. Ответ берём из аргумента или прямо из формы.
    if answer is None:
        answer = request.POST.get('captcha', '')
    expected = request.session.pop(SESSION_ANSWER_KEY, None)
    request.session.pop(SESSION_QUESTION_KEY, None)
    if expected is None:
        return False
    try:
        return int(str(answer).strip()) == int(expected)
    except (TypeError, ValueError):
        return False
