# CoHub — сценарий запуска и демонстрации (Windows / PowerShell)

> **Правила для Windows:**
> • `pytest`/`locust` запускай как `python -m pytest` / `python -m locust`.
> • Вместо `bash script.sh` — Python-команды (`python manage.py ...`).
> • Для флагов curl используй `curl.exe` (в PowerShell `curl` — это другой командлет).
> • Сайт открывай через **localhost**, НЕ через `0.0.0.0` (это адрес привязки, не для браузера).
> • Сервер запускай на `0.0.0.0:8001` — тогда его видит и браузер (localhost:8001),
>   и Prometheus в контейнере (через host.docker.internal:8001).

Канонический порт демо — **8001**. Логин: `artkimyu@gmail.com` / `Cohub2026!`.

## 0. Подготовка (один раз)
```powershell
cd H:\CohubV2\cohub-feature-analytics-tracking
python -m pip install -r requirements-dev.txt      # ставит и pytest, и locust
python manage.py migrate
python manage.py collectstatic --noinput
```

## 1. Запуск сервера
```powershell
python manage.py runserver 0.0.0.0:8001
```
Открыть **http://localhost:8001/** и войти под `artkimyu@gmail.com` / `Cohub2026!`.
(reCAPTCHA настроена на домены `localhost` и `127.0.0.1` — галочка «Я не робот» работает.)

## 2. Демо БЕЗ Docker
```powershell
python -m pytest -v                          # юнит/интеграционные: 94 passed, покрытие 75%
python -m pytest -k RBAC --no-cov -v         # подмножество (иначе сработает порог покрытия)
python manage.py nplusone_report --rows 20   # тест на N+1: 41 -> 1 запрос
python manage.py backup_data --compress      # бэкап в .\backups
python manage.py restore_data                # восстановление последнего
curl.exe http://localhost:8001/health/       # 200 + {"status":"ok","checks":{...}}
curl.exe -I http://localhost:8001/           # заголовки безопасности (CSP, X-Frame-Options...)
```
Кэш Redis (curl до/после — второй быстрее):
```powershell
curl.exe -s -o NUL -w "1й: %{time_total}s`n" http://localhost:8001/api/metrics/prometheus/
curl.exe -s -o NUL -w "2й: %{time_total}s`n" http://localhost:8001/api/metrics/prometheus/
```
- **Капча:** http://localhost:8001/register/ — галочка «Я не робот».
- **JSON-логи:** `Get-Content logs\requests.json -Tail 5`

## 3. Нагрузочный тест (Locust, 100 пользователей)
Locust решает только ВСТРОЕННУЮ арифметическую капчу, поэтому для нагрузки нужен
сервер с **выключенной reCAPTCHA**. Пустые ключи в env → приложение само переключается
на арифметическую капчу (см. `cohub_app/captcha.py`).

**Окно 1 — сервер без reCAPTCHA на 8001** (env-переменные перебивают .env):
```powershell
$env:RECAPTCHA_SITE_KEY=""; $env:RECAPTCHA_SECRET_KEY=""; python manage.py runserver 0.0.0.0:8001
```
**Окно 2 — сам тест:**
```powershell
python -m locust -f locust_loadtest.py --headless `
  --users 100 --spawn-rate 20 --run-time 40s `
  --host http://127.0.0.1:8001 --html loadtest_report.html
start loadtest_report.html      # открыть HTML-отчёт
```
Ожидаемо: ~97–98% успешных, средн. ~30–40 ms, p95 ~120–300 ms. exit code 1 у Locust —
не сбой, он так помечает любой прогон, где были ошибки (403 при разгоне без сессии — норма).
Тест создаёт ~100 временных юзеров `loadtest_*@test.cohub.local` — это ожидаемо.

⚠️ После нагрузки закрой Окно 1 и запусти сервер обычной командой из раздела 1
(чтобы вернулась reCAPTCHA для логина).

## 4. Grafana + мониторинг + Telegram (Docker)
Требует запущенного **Docker Desktop** (см. раздел 6, если не стартует).
Prometheus скрейпит приложение на **host.docker.internal:8001** (задано в
`monitoring/prometheus/prometheus.yml`) — поэтому сервер должен слушать `0.0.0.0:8001`.
```powershell
# приложение уже запущено на 0.0.0.0:8001 (раздел 1). Поднять стек мониторинга:
docker compose -f monitoring/docker-compose.yml up -d
# сгенерировать трафик, чтобы метрики появились:
curl.exe http://localhost:8001/api/rooms/ ; curl.exe http://localhost:8001/health/
```
- **Grafana:** http://localhost:3000 (admin/admin) → дашборд **«COHUB · 4 золотых сигнала»**.
- **Prometheus:** http://localhost:9090 → Status → Targets (цель `cohub` = UP), вкладка Alerts.
- **Alertmanager:** http://localhost:9093.
- **Тест-алерт в Telegram:**
  ```powershell
  curl.exe -H "Content-Type: application/json" -d "[{\"labels\":{\"alertname\":\"DemoTest\",\"severity\":\"critical\"},\"annotations\":{\"summary\":\"Demo\",\"description\":\"Test\"}}]" http://localhost:9093/api/v2/alerts
  ```
  → прилетает от @Cohubb_bot.

**🔥 Связка «нагрузка → Grafana»:** запусти нагрузочный тест из раздела 3 (на 8001) и
одновременно смотри дашборд Grafana — request rate и latency подскочат в реальном времени
(проверено: `cohub_requests_total` 0 → 1856, p95 → 207 ms).

## 5. Весь стек в Docker (app + БД + Redis + Celery)
```powershell
docker compose up --build
```
- Приложение: http://localhost:8000
- **Celery-воркер:** `docker compose logs -f worker` → `Task ... send_loan_reminder_task ... succeeded`
- **Health после рестарта:** `docker compose restart web` → `curl.exe http://localhost:8000/health/`

## 6. Если Docker/WSL не заводится
```powershell
# PowerShell ОТ АДМИНИСТРАТОРА:
wsl --update
wsl --install
# перезагрузка, затем запустить Docker Desktop, дождаться "Engine running"
docker info        # должно вывестись без ошибки
```
Либо Docker Desktop → Settings → General → выключить «Use WSL2 based engine» (Hyper-V).

**Альтернатива без Docker — показать с хостинга Render:**
- Мониторинг → Render Dashboard → сервис `cohub-web` → вкладки **Metrics** и **Logs**.
- Celery → сервис `cohub-worker` → **Logs**.

## 7. PostHog (продуктовая аналитика)
Ключ уже в `.env` (EU Cloud, posthog 3.7.0). После входа/регистрации серверные события
(`user_signed_up`, `room_created`) летят в PostHog → **Activity** и **Persons**.
Клиентские события ($pageview) режет блокировщик рекламы — для них выключи адблок на localhost.

## Виды тестов в проекте
| Тест | Команда | Что проверяет |
|------|---------|----------------|
| Юнит/интеграционные | `python -m pytest -v` | Корректность логики, 94 теста, покрытие 75% |
| Нагрузочный (Locust) | раздел 3 | Пропускную способность и latency при 100 юзерах |
| N+1 запросы | `python manage.py nplusone_report` | Отсутствие лишних SQL-запросов (41→1) |
| Health check | `curl.exe .../health/` | Живость БД, кэша, приложения |

## Топ-5 для защиты
1. `python -m pytest -v` (94 теста, 75%)  2. Тест-алерт в Telegram
3. Grafana «4 золотых сигнала» + всплеск от нагрузки  4. Locust 100 юзеров (~98%)  5. `docker compose up` — весь стек одной командой
