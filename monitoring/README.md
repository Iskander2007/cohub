# COHUB · Стек мониторинга (Prometheus + Grafana + Alertmanager)

Готовый локальный стек наблюдаемости для COHUB. Поднимается одной командой и
автоматически подключает источник данных и дашборд «4 золотых сигнала».

```
Django (host :8000)
  └── GET /api/metrics/prometheus/   ← текстовый формат Prometheus
        │  scrape каждые 15s
        ▼
   Prometheus (:9090) ──→ Alertmanager (:9093)   ← алерты (server down / error rate / latency / …)
        │
        ▼
    Grafana (:3000)   ← дашборд «COHUB · 4 золотых сигнала»
```

## Что входит

| Компонент | Файл | Назначение |
|-----------|------|-----------|
| Prometheus | `prometheus/prometheus.yml` | Скрейп приложения + загрузка правил алертов |
| Alert rules | `prometheus/alert_rules.yml` | Server down / error rate / latency / CPU / RAM / платежи |
| Alertmanager | `alertmanager/alertmanager.yml` | Маршрутизация алертов по командам/каналам |
| Grafana datasource | `grafana/provisioning/datasources/datasource.yml` | Источник данных Prometheus (uid `prometheus`) |
| Grafana dashboards | `grafana/provisioning/dashboards/dashboards.yml` | Автозагрузка дашбордов из папки |
| Dashboard | `grafana/dashboards/cohub-golden-signals.json` | 4 золотых сигнала + платежи |
| Compose | `docker-compose.yml` | Поднимает весь стек |

## Запуск

1. Запустите приложение на хосте (порт 8000):
   ```bash
   cd cohub
   .venv/Scripts/python.exe manage.py runserver 0.0.0.0:8000   # Windows
   # python manage.py runserver 0.0.0.0:8000                   # Linux/macOS
   ```

2. Поднимите стек мониторинга:
   ```bash
   docker compose -f monitoring/docker-compose.yml up -d
   ```

3. Откройте:
   - Grafana — http://localhost:3000 (логин `admin` / пароль `admin`),
     дашборд **COHUB · 4 золотых сигнала** (папка COHUB);
   - Prometheus — http://localhost:9090 (Status → Targets: таргет `cohub` = UP);
   - Alertmanager — http://localhost:9093.

> Prometheus обращается к приложению по `host.docker.internal:8000`. На Docker
> Desktop (Windows/macOS) это работает из коробки; на Linux в compose добавлен
> `extra_hosts: host.docker.internal:host-gateway`.
>
> ⚠️ **ALLOWED_HOSTS.** Скрейп идёт с заголовком `Host: host.docker.internal`,
> поэтому это имя обязано быть в `DJANGO_ALLOWED_HOSTS` — иначе Django вернёт
> `400 DisallowedHost`, и таргет `cohub` будет DOWN. Оно уже добавлено в дефолт
> `settings.py`, в `.env` и `.env.example`. Если переопределяете список вручную —
> не забудьте `host.docker.internal`.

## 4 золотых сигнала (метрики приложения)

| Сигнал | Метрика Prometheus | Источник |
|--------|--------------------|----------|
| **Traffic** | `rate(cohub_requests_total[1m])` | счётчик запросов (MetricsMiddleware) |
| **Errors** | `cohub_error_rate_percent` | доля ответов со статусом ≥ 400 |
| **Latency** | `cohub_p95_latency_ms`, `cohub_avg_latency_ms` | время ответа (p95/avg) |
| **Saturation** | `cohub_cpu_usage`, `cohub_memory_usage` | psutil (CPU/RAM хоста) |

Дополнительно: `up{job="cohub"}` (генерирует Prometheus) — признак «сервер жив»,
и метрики платежей `cohub_payments_*`, `cohub_payment_success_rate`.

## Алерты

Правила в `prometheus/alert_rules.yml` (видны в Prometheus → Alerts):

| Alert | Условие | Severity |
|-------|---------|----------|
| `CohubServerDown` | `up{job="cohub"} == 0` 1m | critical |
| `CohubErrorStorm` | `error_rate > 50%` 2m | critical |
| `CohubHighErrorRate` | `5% < error_rate ≤ 50%` 5m | warning |
| `CohubHighLatency` | `p95 > 5000ms` 3m | warning |
| `CohubElevatedLatency` | `2000 < p95 ≤ 5000ms` 5m | info |
| `CohubHighCPU` | `cpu > 80%` 5m | warning |
| `CohubHighMemory` | `memory > 85%` 5m | warning |
| `CohubPaymentFailureRateHigh` | `payments > 0 и success_rate < 90%` 5m | critical |

Чтобы алерты уходили в Slack/email — раскомментируйте и заполните
`receivers` в `alertmanager/alertmanager.yml`.

## Проверка конфигурации (без запуска стека)

```bash
# Проверить prometheus.yml и правила алертов
docker run --rm -v "$PWD/monitoring/prometheus:/p" prom/prometheus:v2.54.1 \
  promtool check config /p/prometheus.yml

# Проверить только правила
docker run --rm -v "$PWD/monitoring/prometheus:/p" prom/prometheus:v2.54.1 \
  promtool check rules /p/alert_rules.yml
```

## Альтернатива: Render dashboard

Если разворачиваете на Render (см. `render.yaml`), встроенный мониторинг Render
использует `healthCheckPath: /health/`. Метрики приложения остаются доступны по
`/api/metrics/` и `/api/metrics/prometheus/` — Grafana Cloud / любой внешний
Prometheus может скрейпить публичный URL сервиса.
