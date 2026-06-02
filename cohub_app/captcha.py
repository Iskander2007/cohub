"""CAPTCHA для форм регистрации и входа.

Реализована встроенная арифметическая CAPTCHA, не требующая внешних сервисов и
ключей, — поэтому она работает офлайн, в тестах и в CI. Вопрос и правильный ответ
хранятся в серверной сессии (пользователь видит только текст вопроса), что
защищает от автоматических ботов при регистрации и брутфорса при входе.

Если в окружении заданы ключи Google reCAPTCHA
(RECAPTCHA_SITE_KEY / RECAPTCHA_SECRET_KEY), можно подключить и её — для учебного
проекта по умолчанию используется встроенный вариант.
"""

import secrets

# Ключи в сессии, под которыми храним правильный ответ и сам вопрос.
SESSION_ANSWER_KEY = 'captcha_answer'
SESSION_QUESTION_KEY = 'captcha_question'


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


def validate_captcha(request, answer):
    """Проверить ответ пользователя на CAPTCHA.

    Ответ одноразовый: после проверки (успешной или нет) он удаляется из сессии,
    чтобы один и тот же ответ нельзя было переиспользовать (replay).
    Возвращает True/False.
    """
    expected = request.session.pop(SESSION_ANSWER_KEY, None)
    request.session.pop(SESSION_QUESTION_KEY, None)
    if expected is None:
        return False
    try:
        return int(str(answer).strip()) == int(expected)
    except (TypeError, ValueError):
        return False
