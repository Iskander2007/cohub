"""RBAC: роли admin/user и DRF-классы прав доступа.

Единая точка истины о роли пользователя. Пользователь считается администратором,
если у него выставлен Django-флаг is_superuser/is_staff ИЛИ роль профиля == 'admin'.
Это позволяет управлять ролью как через админку Django, так и через профиль.
"""

from rest_framework.permissions import BasePermission, SAFE_METHODS


def get_user_role(user):
    """Вернуть глобальную роль пользователя: 'admin' или 'user'.

    Неаутентифицированный пользователь роли не имеет — возвращаем None.
    """
    if not user or not user.is_authenticated:
        return None
    if user.is_superuser or user.is_staff:
        return 'admin'
    profile = getattr(user, 'profile', None)
    if profile is not None and getattr(profile, 'role', 'user') == 'admin':
        return 'admin'
    return 'user'


def is_admin(user):
    """True, если пользователь имеет роль администратора."""
    return get_user_role(user) == 'admin'


class IsAuthenticatedUser(BasePermission):
    """Базовое право: доступ только аутентифицированному активному пользователю.

    Применяется ко всем эндпоинтам по умолчанию — это уровень роли 'user'.
    """

    message = 'Требуется вход в систему.'

    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and user.is_active)


class IsAdminRole(BasePermission):
    """Право: доступ только пользователю с ролью 'admin'."""

    message = 'Требуется роль администратора.'

    def has_permission(self, request, view):
        return is_admin(request.user)


class IsAdminOrReadOnly(BasePermission):
    """Чтение — любому аутентифицированному, запись — только администратору."""

    message = 'Изменение доступно только администратору.'

    def has_permission(self, request, view):
        user = request.user
        if not (user and user.is_authenticated and user.is_active):
            return False
        if request.method in SAFE_METHODS:
            return True
        return is_admin(user)
