# 📊 COHUB · Мониторинг, логирование и нагрузочное тестирование

> **TL;DR.** Наблюдаемость COHUB строится на стеке **Prometheus + Grafana + Alertmanager**. Приложение отдаёт метрики в формате Prometheus, Grafana рисует дашборд «4 золотых сигнала», Alertmanager рассылает алерты (server down / error rate / latency). Ключевые запросы пишутся структурированным JSON-логом. Нагрузка проверяется через Locust (100 пользователей, HTML-отчёт).

---

## 🗺️ Содержание

1. Архитектура
2. Компоненты и порты
3. Быстрый старт
4. 4 золотых сигнала
5. Метрики и эндпоинты приложения
6. Алерты
7. Структурированное JSON-логирование
8. Нагрузочное тестирование (Locust)
9. Карта файлов
10. Траблшутинг
11. Известные ограничения
12. Чек-лист эксплуатации

---

## 1. 🏗️ Архитектура

```
            ┌─────────────────────────────┐
            │   Django (COHUB) · host:8000 │
            │   MetricsMiddleware          │
            └──────┬───────────────┬───────┘
                   │               │
        логи (JSON)│               │ метрики (Prometheus text)
                   ▼               ▼
        logs/*.json        GET /api/metrics/prometheus/
   payments / errors /             │  scrape каждые 15 c
   requests.json                   ▼
                          ┌──────────────────┐     алерты    ┌────────────────┐
                          │  Prometheus :9090 │ ───────────▶ │ Alertmanager   │
                          │  + alert_rules    │              │ :9093          │
                          └─────────┬─────────┘              └───────┬────────┘
                                    │ запросы PromQL                 │ Slack / email
                                    ▼                                ▼
                          ┌──────────────────┐                 каналы команд
                          │  Grafana :3000    │
                          │  Dashboard «4 GS» │
                          └──────────────────┘
```

**Принцип:** приложение ничего не «пушит» — оно только выставляет метрики на HTTP-эндпоинте, а Prometheus сам их забирает (pull-модель). Это устойчиво к рестартам и не требует внешних зависимостей в рантайме приложения.

---

## 2. 🧩 Компоненты и порты

| Компонент | Порт | Доступ | Назначение |
|---|---|---|---|
| Django (COHUB) | `8000` | — | Источник метрик и логов |
| Prometheus | `9090` | http://localhost:9090 | Сбор и хранение time-series, оценка алертов |
| Alertmanager | `9093` | http://localhost:9093 | Маршрутизация и доставка алертов |
| Grafana | `3000` | http://localhost:3000 (`admin` / `admin`) | Визуализация, дашборд «4 золотых сигнала» |

> 💡 Версии образов зафиксированы: `prom/prometheus:v2.54.1`, `prom/alertmanager:v0.27.0`, `grafana/grafana:11.2.0`.

---

## 3. 🚀 Быстрый старт

**Шаг 1 — приложение на хосте (порт 8000):**

```bash
cd cohub
.venv/Scripts/python.exe manage.py runserver 0.0.0.0:8000   # Windows
# python manage.py runserver 0.0.0.0:8000                   # Linux/macOS
```

**Шаг 2 — стек мониторинга:**

```bash
docker compose -f monitoring/docker-compose.yml up -d
```

**Шаг 3 — открыть интерфейсы:**

- Grafana → http://localhost:3000 → дашборд **COHUB · 4 золотых сигнала** (папка COHUB)
- Prometheus → http://localhost:9090 → Status → Targets → таргет `cohub` должен быть **UP**
- Alertmanager → http://localhost:9093

> ⚠️ **ALLOWED_HOSTS.** Prometheus обращается к приложению по имени `host.docker.internal`, поэтому это имя обязано присутствовать в `DJANGO_ALLOWED_HOSTS` — иначе Django вернёт `400 DisallowedHost` и таргет `cohub` будет DOWN. Оно уже добавлено в дефолт `settings.py`, в `.env` и `.env.example`.

> 🐧 На Linux хост доступен из контейнера благодаря `extra_hosts: host.docker.internal:host-gateway` в compose. На Docker Desktop (Windows/macOS) — из коробки.

---

## 4. 🌟 4 золотых сигнала

Подход Google SRE: четыре сигнала, которых достаточно, чтобы понять здоровье сервиса.

| Сигнал | Метрика / PromQL | Панель Grafana | Порог (warn / crit) |
|---|---|---|---|
| **Traffic** (нагрузка) | `rate(cohub_requests_total[1m])` | Timeseries + Stat | — |
| **Errors** (ошибки) | `cohub:error_rate_5m:percent` (оконный, recording rule) | Gauge + Stat | 5% / 50% |
| **Latency** (задержка) | `cohub_p95_latency_ms`, `cohub_avg_latency_ms` | Timeseries + Stat | 2000ms / 5000ms |
| **Saturation** (насыщение) | `cohub_cpu_usage`, `cohub_memory_usage` | Timeseries | CPU 80% / RAM 85% |

Дополнительно на дашборде: статус **`up{job="cohub"}`** (жив ли сервер) и блок **платежей** (всего/успешно/неуспешно, success rate).

> 📁 Дашборд: `monitoring/grafana/dashboards/cohub-golden-signals.json` (15 панелей, импортируется автоматически через provisioning, uid `cohub-golden-signals`).

---

## 5. 📈 Метрики и эндпоинты приложения

| Эндпоинт | Формат | Назначение |
|---|---|---|
| `GET /health/` · `GET /api/health/` | JSON | Healthcheck (БД + кеш). 200 = жив, 503 = проблема |
| `GET /api/metrics/` | JSON | Метрики для дашбордов (кеш 5 c) |
| `GET /api/metrics/prometheus/` | text/plain | **Основной скрейп-эндпоинт Prometheus** |
| `GET /api/metrics/summary/` | JSON | Человекочитаемая сводка золотых сигналов + флаги алертов |

**Список метрик в формате Prometheus:**

```
cohub_requests_total          # counter — всего HTTP-запросов
cohub_errors_total            # counter — всего ошибок (status >= 400)
cohub_error_rate_percent      # gauge   — доля ошибок, %
cohub_p95_latency_ms          # gauge   — 95-й перцентиль времени ответа
cohub_avg_latency_ms          # gauge   — среднее время ответа
cohub_cpu_usage               # gauge   — загрузка CPU, %
cohub_memory_usage            # gauge   — использование RAM, %
cohub_payments_total          # counter — всего платёжных транзакций
cohub_payments_successful     # counter — успешные платежи
cohub_payments_failed         # counter — неуспешные платежи
cohub_payment_success_rate    # gauge   — success rate платежей, %
```

> Реализация: `cohub_app/monitoring.py` (эндпоинты), `cohub_app/logging_utils.py` (`MetricsCollector`), `cohub_app/metrics_middleware.py` (сбор по каждому запросу).

> 🔒 **Защита метрик (опционально).** По умолчанию эндпоинты метрик открыты — локальный Prometheus скрейпит их без токена. На публичном проде задайте переменную окружения `METRICS_TOKEN`: тогда `/api/metrics(/prometheus|/summary)` потребуют `?token=<...>` или заголовок `Authorization: Bearer <...>` (иначе 403), чтобы не раскрывать бизнес-метрики анонимам. `/health/` остаётся открытым для балансировщика. В этом случае пропишите токен и в `prometheus.yml` (`authorization`/`params`).

---

## 6. 🚨 Алерты

Файл правил: `monitoring/prometheus/alert_rules.yml` (загружается Prometheus, виден в **Prometheus → Alerts**). Доставка: `monitoring/alertmanager/alertmanager.yml`.

| Alert | Условие | for | Severity |
|---|---|---|---|
| `CohubServerDown` | `up{job="cohub"} == 0` | 1m | 🔴 critical |
| `CohubErrorStorm` | `cohub:error_rate_5m:percent > 50` | 2m | 🔴 critical |
| `CohubHighErrorRate` | `5% < cohub:error_rate_5m:percent ≤ 50%` | 5m | 🟡 warning |
| `CohubHighLatency` | `cohub_p95_latency_ms > 5000` | 3m | 🟡 warning |
| `CohubElevatedLatency` | `2000 < p95 ≤ 5000` | 5m | 🔵 info |
| `CohubHighCPU` | `cohub_cpu_usage > 80` | 5m | 🟡 warning |
| `CohubHighMemory` | `cohub_memory_usage > 85` | 5m | 🟡 warning |
| `CohubPaymentFailureRateHigh` | `payment_success_rate < 90 и payments_total > 0` | 5m | 🔴 critical |

**Три обязательных сигнала покрыты:** server down (`up == 0`), error rate, latency.

> 📨 Каналы доставки (Slack/email) в `alertmanager.yml` оставлены закомментированными заглушками — впишите свои вебхуки и SMTP перед продакшеном. Маршрутизация по `severity`/`team` уже настроена.

---

## 7. 📝 Структурированное JSON-логирование

Все логи пишутся в JSON (форматтер `JSONFormatter` в `logging_utils.py`) — удобно парсить в Grafana Loki / ELK.

| Файл | Что содержит | Логгер |
|---|---|---|
| `logs/requests.json` | По одной строке на запрос к ключевым endpoint'ам | `cohub.requests` |
| `logs/payments.json` | События платежей (initiated/confirmed/failed/...) | `cohub.payments` |
| `logs/errors.json` | Ошибки и исключения (ERROR+), включая 5xx | `cohub_app` |

**Ключевые endpoint'ы** (логируются): `/api/`, `/payments/`, `/account/`, `/register/`, `/dashboard/`, `/room/`, `/subscription/`, `/health/`. Скрейп-эндпоинты метрик (`/api/metrics*`) исключены, чтобы не зашумлять лог.

**Пример строки `requests.json`:**

```json
{
  "timestamp": "2026-06-29T07:43:25.036660+00:00",
  "level": "INFO",
  "logger": "cohub.requests",
  "event_type": "http_request",
  "method": "POST",
  "path": "/api/rooms/",
  "status_code": 201,
  "latency_ms": 12.34,
  "user_id": 27,
  "request_id": "1e3d6208-a71b-4001-92cb-e4a40e4c0ff0",
  "client_ip": "127.0.0.1",
  "user_agent": "..."
}
```

> 🛡️ Логирование изолировано try/except — сбой записи лога **не может** превратить успешный ответ в 500. `request_id` принимается от клиента только если проходит валидацию, иначе генерируется.

---

## 8. 🧪 Нагрузочное тестирование (Locust)

**Сценарий** (`locust_loadtest.py`): до 100 одновременных пользователей. Каждый регистрируется (с автоматическим решением CAPTCHA и CSRF → авто-вход), затем со взвешенными вероятностями смотрит комнаты, создаёт комнату, добавляет расходы, смотрит задачи, дёргает health и метрики.

**Запуск:**

```bash
pip install -r requirements-dev.txt          # ставит locust

# Windows
.\loadtest\run_loadtest.ps1                   # 100 юзеров, 2 мин, HTML-отчёт
.\loadtest\run_loadtest.ps1 -Users 100 -RunTime 2m -TargetHost http://127.0.0.1:8000

# Linux/macOS
./loadtest/run_loadtest.sh
USERS=100 RUN_TIME=2m ./loadtest/run_loadtest.sh

# Напрямую
locust -f locust_loadtest.py --headless --users 100 --spawn-rate 10 \
       --run-time 2m --host http://127.0.0.1:8000 --html loadtest_report.html
```

**Результат прогона (100 пользователей, разгон 10/с):**

| Метрика | Значение |
|---|---|
| Всего запросов | ~2490 |
| Успешность | **98.8%** |
| Среднее время ответа | 89 мс |
| p95 | 600 мс |
| Артефакт | `loadtest_report.html` (+ `loadtest_stats_*.csv`) |

> 🧰 **Важно для локального прогона.** На dev-`runserver` + SQLite высокая конкуренция вызывала «database is locked». Решено включением **WAL + busy_timeout** для SQLite (`cohub_app/apps.py`, на PostgreSQL не влияет) — успешность выросла с ~22% до 98.8%. Если в окружении включена Google reCAPTCHA — для нагрузочного прогона её ключи нужно временно очистить (locust не может пройти серверную проверку Google).

---

## 9. 🗂️ Карта файлов

| Файл | Роль |
|---|---|
| `monitoring/docker-compose.yml` | Поднимает Prometheus + Alertmanager + Grafana |
| `monitoring/prometheus/prometheus.yml` | Scrape-конфиг + подключение правил |
| `monitoring/prometheus/alert_rules.yml` | Правила алертов (server down / error rate / latency / …) |
| `monitoring/alertmanager/alertmanager.yml` | Маршрутизация и доставка алертов |
| `monitoring/grafana/provisioning/datasources/datasource.yml` | Датасорс Prometheus (uid `prometheus`) |
| `monitoring/grafana/provisioning/dashboards/dashboards.yml` | Автозагрузка дашбордов |
| `monitoring/grafana/dashboards/cohub-golden-signals.json` | Дашборд «4 золотых сигнала» |
| `monitoring/README.md` | Документация стека |
| `cohub_app/monitoring.py` | Эндпоинты метрик и health |
| `cohub_app/logging_utils.py` | `JSONFormatter`, `MetricsCollector`, логгер платежей |
| `cohub_app/metrics_middleware.py` | Сбор метрик + per-request JSON-лог |
| `cohub_app/apps.py` | PRAGMA WAL/busy_timeout для SQLite |
| `cohub_settings/settings.py` | `LOGGING`, `MIDDLEWARE`, `ALLOWED_HOSTS` |
| `locust_loadtest.py` | Нагрузочный сценарий (100 юзеров) |
| `loadtest/run_loadtest.ps1` · `.sh` | Раннеры с генерацией HTML-отчёта |
| `requirements-dev.txt` | Dev-зависимости (locust) |

---

## 10. 🔧 Траблшутинг

| Симптом | Причина | Решение |
|---|---|---|
| Таргет `cohub` = **DOWN** в Prometheus | `host.docker.internal` нет в `ALLOWED_HOSTS` → 400 | Добавить `host.docker.internal` в `DJANGO_ALLOWED_HOSTS` |
| Дашборд пустой («No data») | Приложение не запущено / таргет DOWN | Поднять `runserver` на 8000, проверить Targets |
| Panel Saturation «No Data» | psutil не смог снять CPU/RAM | Норма для некоторых ФС; метрика выставляется условно |
| Алерты не приходят в Slack/email | Receivers закомментированы | Заполнить `alertmanager.yml` своими вебхуками |
| Locust: все `/api/` → 403 | Регистрация не прошла (включена reCAPTCHA) | Очистить `RECAPTCHA_*` для прогона |
| Locust: 500 «database is locked» | SQLite под конкуренцией | WAL уже включён; на проде — PostgreSQL |
| `run_loadtest.ps1` не стартует | (исправлено) конфликт `$Host` | Используется `$TargetHost`, файл с BOM |

---

## 11. ⚠️ Известные ограничения

- **In-process метрики.** `MetricsCollector` — синглтон в памяти процесса. Прод на Render запускает gunicorn с **1 воркером**, поэтому счётчики корректны. При увеличении числа воркеров/инстансов нужен `prometheus_client` в multiprocess-режиме (см. предупреждение в [PLAYBOOK.md](PLAYBOOK.md), Сценарий 3).
- **Окна расчёта.** Алерты и панель Errors используют **оконный** error rate (recording rule `cohub:error_rate_5m:percent` = `rate(cohub_errors_total[5m]) / rate(cohub_requests_total[5m])`) — он чувствителен к текущему всплеску. Накопительный gauge `cohub_error_rate_percent` (доля за всё время жизни процесса) приложение всё ещё отдаёт, но он используется только как информационный (в `/api/metrics/summary/`). `p95`/`avg` — по последним ≤2000 запросам.
- **Сброс при рестарте.** Счётчики живут в памяти и обнуляются при перезапуске приложения (Prometheus корректно обрабатывает reset счётчика через `rate()`).
- **SQLite только для dev.** Прод использует PostgreSQL (`DATABASE_URL` в `render.yaml`).

---

## 12. ✅ Чек-лист эксплуатации

- [ ] `DJANGO_ALLOWED_HOSTS` содержит `host.docker.internal` (для локального стека)
- [ ] Приложение отвечает на `GET /api/metrics/prometheus/`
- [ ] Prometheus → Targets: `cohub` = UP
- [ ] Grafana → дашборд «4 золотых сигнала» рисует данные
- [ ] Prometheus → Alerts: правила загружены (8 шт.)
- [ ] Alertmanager: заполнены реальные каналы доставки (перед продом)
- [ ] Нагрузочный прогон выполнен, `loadtest_report.html` сохранён
- [ ] Логи `logs/requests.json` / `payments.json` / `errors.json` пишутся

---

*Связанные документы в репозитории: `monitoring/README.md` (запуск стека), `ALERT_RULES.md` (детали алертов и эскалаций), `MONITORING_SETUP.md` (исходная конфигурация).*
