"""Контекст-процессоры: значения, доступные во всех шаблонах."""

from .oauth import google_oauth_configured


def oauth_flags(request):
    """Флаг доступности входа через Google — для условного показа кнопки."""
    return {'google_oauth_enabled': google_oauth_configured()}
