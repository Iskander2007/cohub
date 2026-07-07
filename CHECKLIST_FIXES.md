# Доработки чек-листа (частичные пункты → выполнены)

Ниже — что было доделано по каждому ранее «частичному» пункту, и как проверить.
Все тесты зелёные: `pytest -v` → 93 passed, покрытие **74.75%** (≥70%).

| # | Пункт | Что сделано | Проверка |
|---|-------|-------------|----------|
| 3 | Docker: app + БД локально | Новый `Dockerfile` (Python/gunicorn) и `docker-compose.yml`: сервисы **web** (Django, migrate+collectstatic), **db** (postgres:16), **redis**, **worker** (Celery) с healthcheck'ами | `docker compose up --build` → http://localhost:8000 |
| 8 | Бэкап + тест восстановления | `backup.sh` (bash), команда `restore_data`, автотест round-trip `BackupRestoreTests` | `./backup.sh`; `pytest -k BackupRestore` |
| 10 | pytest + покрытие ≥70% | `pytest.ini` + `.coveragerc`, dev-зависимости (pytest/pytest-django/pytest-cov), шаг в CI `pytest -v` с `--cov-fail-under=70`; починен порядок collectstatic до тестов | `pytest -v` |
| 12 | Celery-задача | `cohub_settings/celery.py`, `@shared_task send_loan_reminder_task`, воркер в compose и `render.yaml`, тест в eager-режиме `CeleryTaskTests`; прод с Redis реально шлёт через Celery | `pytest -k Celery`; логи воркера |
| 13 | Redis-кэш >2 эндпоинтов | `redis` в requirements; REDIS_URL в compose/render/.env; общий кэш метрик → кэшируются `/api/metrics/`, `/metrics/prometheus/`, `/metrics/summary/` (+assistant) | `CACHING.md`, `pytest -k MetricsCache` |
| 14 | N+1 + лог запросов | Команда `nplusone_report` печатает запросы до/после; тест `NPlusOneQueryTests` (`assertNumQueries(1)`); 8 индексов | `python manage.py nplusone_report`; `DB_PERFORMANCE.md` |
| 16 | /health под Docker | web-сервис в compose с healthcheck на `/health/` (БД+кэш); рестарт-проба | `docker compose restart web && curl localhost:8000/health/` |
| 20 | RBAC на эндпоинтах | Применены `IsAdminRole`/`IsAdminOrReadOnly`: новый `GET /api/admin/overview/`, `subscription/activate` через `get_permissions`; матрица + тесты `RBACRoleTests` | `RBAC.md`, `pytest -k RBAC` |
| 25 | Алерты в Telegram | `alertmanager.yml`: receiver `telegram` (bot_token_file + chat_id), маршрутизация всех алертов; секрет-файл в .gitignore | `monitoring/TELEGRAM_ALERTS.md` |

## Что нужно сделать вам (значения, которые я не могу знать)
1. **Telegram**: создать бота у @BotFather, положить токен в
   `monitoring/alertmanager/secrets/telegram_bot_token`, вписать `chat_id` в
   `alertmanager.yml`. Пошагово — `monitoring/TELEGRAM_ALERTS.md`.
2. **Docker/Render**: реальные `DATABASE_URL` и (для прод-Celery) `REDIS_URL`
   задаются платформой; в `render.yaml` Redis уже подключается автоматически.

## Осталось внешним (не код — это пункты, требующие «живого» пруфа)
Пункты 1, 2, 4, 5, 6, 9, 11 из чек-листа доказываются только на GitHub/Render/
Confluence (защита ветки, PR с ревью, живой URL/HTTPS, зелёный прогон, страница
Confluence). Их нельзя «сделать в коде» — нужны скриншоты/ссылки.
