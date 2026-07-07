# RBAC: роли admin / user

Две роли на уровне сервиса, единая точка истины — `cohub_app/permissions.py`.

- **user** (по умолчанию) — любой аутентифицированный активный пользователь.
- **admin** — `is_superuser`/`is_staff` **ИЛИ** `UserProfile.role == 'admin'`
  (поле роли добавлено миграцией `0012_userprofile_role`).

## Permission-классы (DRF)
| Класс | Правило |
|-------|---------|
| `IsAuthenticatedUser` | доступ только аутентифицированному пользователю (роль user). **DEFAULT_PERMISSION_CLASSES** — применяется ко всем эндпоинтам API. |
| `IsAdminRole` | доступ только роли admin. |
| `IsAdminOrReadOnly` | чтение — любому, запись (POST/PUT/PATCH/DELETE) — только admin. |

Базовая роль `user` enforced глобально через `REST_FRAMEWORK['DEFAULT_PERMISSION_CLASSES']`,
поэтому **каждый** API-эндпоинт требует минимум роль user. Ниже — где различается admin/user.

## Матрица доступа
| Эндпоинт | user | admin | Как enforced |
|----------|:----:|:-----:|--------------|
| `GET/POST /api/rooms/`, `/tasks/`, `/expenses/`, `/loans/`, `/chat-messages/` … | ✅ (свои комнаты) | ✅ | `IsAuthenticatedUser` + object-level (владелец/участник) |
| `GET /api/admin/overview/` | ❌ 403 | ✅ 200 | **`IsAdminRole`** |
| `POST /api/subscription/activate/` | ❌ 403 | ✅ | `get_permissions()` → `IsAdminRole` |
| `GET /api/teacher-metrics/` (глобальные) | ❌ 403 | ✅ | inline `is_admin()` |
| `GET /api/teacher-metrics/?room=<id>` | ✅ (участник) | ✅ | членство в комнате или admin |
| `GET /analytics/kpi/` (веб) | ❌ redirect | ✅ | `is_admin()` |
| `GET /health/`, `/api/metrics/*` | открыто (инфраструктура; метрики можно закрыть `METRICS_TOKEN`) | — | по дизайну для Prometheus |

## Как назначить роль admin
- Через Django admin: `UserProfile` → поле «Роль (RBAC)» → `admin`; либо
- `is_staff=True` / `is_superuser=True` у пользователя.

## Тесты
`cohub_app/tests.py::RBACRoleTests` проверяет: аноним → 401/403, user → 403,
admin → 200 на `/api/admin/overview/`, и что `subscription/activate` запрещён user.
