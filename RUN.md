# CoHub — краткая инструкция запуска (локально + хостинг)

> Windows/PowerShell. `python` = Python 3.14 (все зависимости уже стоят).
> Замени `cohub-r2ut.onrender.com` на свой URL Render, если он другой.

**Доступы**
- Локальный сайт: http://localhost:8001/ · логин `artkimyu@gmail.com` / `Cohub2026!`
- Grafana: http://localhost:3000 — **admin / admin**
- Прод-сайт: https://cohub-r2ut.onrender.com/
- Прод-админка: https://cohub-r2ut.onrender.com/admin/

---

# ЛОКАЛЬНО

**0. Подготовка (один раз)**
```powershell
cd H:\CohubV2\cohub-feature-analytics-tracking
python -m pip install -r requirements-dev.txt
python manage.py migrate
python manage.py collectstatic --noinput
```

**1. Запуск сервера** (открывать через localhost, не 0.0.0.0)
```powershell
python manage.py runserver 0.0.0.0:8001
http://localhost:8001
```

**2. Тесты**
```powershell
python -m pytest -v                          # все 94 теста + покрытие 75%
python -m pytest -k RBAC --no-cov -v         # подмножество (с --no-cov)
```

**3. Фичи**
```powershell
python manage.py nplusone_report --rows 20   # N+1: 41 -> 1 запрос
python manage.py backup_data --compress      # бэкап БД в .\backups
python manage.py restore_data                # восстановление последнего
curl.exe http://localhost:8001/health/       # health
curl.exe -I http://localhost:8001/           # заголовки безопасности
Get-Content logs\requests.json -Tail 5       # JSON-логи
```
Капча: http://localhost:8001/register/

**4. Нагрузочный тест Locust (100 юзеров)** — нужен сервер без reCAPTCHA
```powershell
# Окно 1:
$env:RECAPTCHA_SITE_KEY=""; $env:RECAPTCHA_SECRET_KEY=""; python manage.py runserver 0.0.0.0:8001
# Окно 2:
python -m locust -f locust_loadtest.py --headless --users 100 --spawn-rate 20 --run-time 40s --host http://127.0.0.1:8001 --html loadtest_report.html
start loadtest_report.html
```
После теста закрой Окно 1 и запусти обычный сервер (п.1) — вернётся reCAPTCHA.

**5. Grafana + Telegram-алерты (Docker)**
```powershell
docker compose -f monitoring/docker-compose.yml up -d
curl.exe http://localhost:8001/health/       # немного трафика для метрик
# тест-алерт в Telegram:
curl.exe -H "Content-Type: application/json" -d "[{\"labels\":{\"alertname\":\"DemoTest\",\"severity\":\"critical\"},\"annotations\":{\"summary\":\"Demo\",\"description\":\"Test\"}}]" http://localhost:9093/api/v2/alerts
```
Grafana → localhost:3000 (admin/admin) → дашборд «COHUB · 4 золотых сигнала».

**6. PostHog** — ключ уже в `.env`. После входа/регистрации серверные события летят в PostHog → Activity. Клиентские ($pageview) режет адблок — выключи его на localhost.

---

# НА ХОСТИНГЕ (Render)

Приложение уже запущено (gunicorn). Взаимодействие: **URL** (HTTP), **Render Shell** (manage.py), **GitHub Actions** (тесты), **Render Dashboard** (Logs/Metrics).

**Админка**
1. Render Dashboard → cohub-web → **Shell**: `python manage.py createsuperuser`
2. Войти на https://cohub-r2ut.onrender.com/admin/

**Команды: локально → хостинг**
| Локально | Хостинг |
|---|---|
| `migrate` / `collectstatic` | автоматом при деплое (`git push origin main`) |
| `runserver` | уже работает → https://cohub-r2ut.onrender.com/ |
| `python -m pytest` | GitHub → вкладка **Actions** (не на хосте) |
| `curl.exe http://localhost:8001/health/` | `curl.exe https://cohub-r2ut.onrender.com/health/` |
| `curl.exe -I http://localhost:8001/` | `curl.exe -I https://cohub-r2ut.onrender.com/` |
| `backup_data` / `createsuperuser` | Render **Shell** (бэкап ещё идёт cron'ом 02:00 UTC) |
| `Get-Content logs\requests.json` | Render Dashboard → cohub-web → **Logs** |
| Celery `docker compose logs worker` | Render Dashboard → cohub-worker → **Logs** |
| капча `localhost:8001/register/` | https://cohub-r2ut.onrender.com/register/ |
| `nplusone_report`, `restore_data` | ⚠️ только локально (портят прод-БД) |

**Locust по проду** (осторожно — reCAPTCHA + слабый free-инстанс, много 403):
```powershell
python -m locust -f locust_loadtest.py --headless --users 10 --spawn-rate 2 --run-time 30s --host https://cohub-r2ut.onrender.com --html loadtest_report.html
```
Полноценный тест (98%) делай локально — его и показывай.

**Grafana/Telegram по проду:** стека на Render нет. Запусти локальную Grafana, поменяв target в `monitoring/prometheus/prometheus.yml` на `cohub-r2ut.onrender.com` + `scheme: https`, затем `docker compose -f monitoring/docker-compose.yml up -d`. Проще для показа: Render Dashboard → cohub-web → **Metrics**.

**PostHog/reCAPTCHA на проде:** работают, только если добавить их ключи в Render → **Environment** (`POSTHOG_API_KEY`, `POSTHOG_HOST`, `RECAPTCHA_SITE_KEY`, `RECAPTCHA_SECRET_KEY`, `RECAPTCHA_VERSION`) — в `render.yaml` их нет.

---
**Суть:** локально ты всё *запускаешь*; на хостинге приложение уже *работает* — стучишься по HTTPS-URL или выполняешь `manage.py` через **Render Shell**, а тесты и деплой идут через **GitHub Actions**.
