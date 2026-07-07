# 🎯 COHUB Мониторинг - Полная конфигурация

## 📊 Архитектура мониторинга

```
┌──────────────────────┐
│   Django Application │
│  (COHUB Platform)    │
└──────┬───────────────┘
       │ (MetricsMiddleware)
       │ Метрики: latency, status, errors
       │
       ├─────────────────────────────────────┐
       │                                     │
   [Logs]                            [Metrics]
  payments.json                  /api/metrics/
  errors.json                    /api/health/
       │                              │
       └───────────┬───────────────────┘
                   │
            ┌──────▼────────┐
            │  Grafana      │  🖥️ Dashboard
            │  (Визуализ.)  │  (Мониторинг)
            └───────────────┘
                   │
         ┌─────────┴─────────┐
         │                   │
    [Alerts]          [Golden Signals]
   - Service down     1. Request Rate
   - Error rate > 5%  2. Error Rate
   - High latency     3. P95 Latency
   - High CPU/mem     4. CPU/Memory
```

## 🔧 1. НАСТРОЙКА ЛОГИРОВАНИЯ (JSON)

### Файлы логов
- `logs/payments.json` - Все события платежей (JSON формат)
- `logs/errors.json` - Ошибки и исключения (JSON формат)

### JSON структура лога платежа
```json
{
  "timestamp": "2024-06-24T10:30:45.123Z",
  "level": "INFO",
  "event_type": "payment_confirmed",
  "user_id": 123,
  "order_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "confirmed",
  "provider": "paypal",
  "provider_order_id": "9HZ38AJRFSN23",
  "amount": 9.99,
  "currency": "USD"
}
```

### Типы событий платежей
1. `payment_initiated` - Платеж инициирован (пользователь нажал "Оплатить")
2. `payment_pending` - Платеж в статусе ожидания
3. `payment_confirmed` - Платеж успешно подтвержден
4. `payment_failed` - Платеж отклонен
5. `payment_error` - Ошибка при обработке платежа
6. `subscription_activated` - Подписка активирована

## 🎨 2. ЗОЛОТЫЕ СИГНАЛЫ (4 METRIC PANELS в Grafana)

### Panel 1: Request Rate
```
Метрика: cohub_requests_total
Визуал: Graph + Stats
Легенда: "Total Requests per Minute"
Порог (warning): 1000 req/min
Порог (critical): 5000 req/min
```

### Panel 2: Error Rate
```
Метрика: cohub_error_rate_percent
Визуал: Gauge
Легенда: "% Errors"
Порог (warning): 2%
Порог (critical): 5%
Цвет:
  - Зеленый: < 1%
  - Желтый: 1-5%
  - Красный: > 5%
```

### Panel 3: P95 Latency
```
Метрика: cohub_p95_latency_ms
Визуал: Graph + Stat
Легенда: "95th Percentile Latency (ms)"
Порог (warning): 2000ms
Порог (critical): 5000ms
```

### Panel 4: System Resources
```
Метрики:
  - cohub_cpu_usage (%)
  - cohub_memory_usage (%)
  - cohub_disk_usage (%)
Визуал: Multi-graph
Пороги:
  - CPU > 80% → WARNING
  - Memory > 85% → WARNING
  - Disk > 90% → CRITICAL
```

## 🚨 3. СИСТЕМА АЛЕРТОВ

### Alert 1: Service Down
```
Условие: error_rate > 50% ИЛИ все запросы падают
Время перед срабатыванием: 2 минуты
Уровень: CRITICAL
Канал оповещений: email, Slack
Сообщение:
  "🚨 CRITICAL: Service DOWN! Error rate: {error_rate}%"
```

### Alert 2: High Error Rate
```
Условие: error_rate > 5% (в течение 5 минут)
Уровень: WARNING
Канал оповещений: email, Slack
Сообщение:
  "⚠️ WARNING: High error rate detected: {error_rate}%"
```

### Alert 3: High Latency
```
Условие: p95_latency > 5000ms
Время перед срабатыванием: 3 минуты
Уровень: WARNING
Сообщение:
  "⚠️ Slow response times: P95 = {p95_latency}ms"
```

### Alert 4: High Resource Usage
```
Условие: cpu_usage > 80% ИЛИ memory_usage > 85%
Уровень: WARNING
Сообщение:
  "⚠️ High resource usage: CPU={cpu}% Memory={mem}%"
```

## 📈 4. API ЭНДПОИНТЫ МЕТРИК

### GET /api/health/
Проверка живости приложения
```json
{
  "status": "healthy",
  "database": "ok",
  "cache": "ok",
  "timestamp": "2024-06-24T10:30:45Z"
}
```

### GET /api/metrics/
JSON метрики (Grafana compatible)
```json
{
  "request_rate": 152,
  "error_rate": 2.5,
  "p95_latency": 245.5,
  "avg_latency": 145.2,
  "total_errors": 4,
  "cpu_usage": 45.2,
  "memory_usage": 62.1,
  "payment_success_rate": 98.5
}
```

### GET /api/metrics/prometheus/
Prometheus формат для Grafana
```
# HELP cohub_requests_total Total HTTP requests processed
# TYPE cohub_requests_total counter
cohub_requests_total 1523

# HELP cohub_error_rate_percent Error rate in percent
# TYPE cohub_error_rate_percent gauge
cohub_error_rate_percent 2.50

# ... и т.д.
```

### GET /api/metrics/summary/
Краткая сводка
```json
{
  "status": "ok",
  "golden_signals": {
    "request_rate": 152,
    "error_rate_percent": "2.50%",
    "p95_latency_ms": "245.50ms",
    "cpu_usage_percent": "45.2%",
    "memory_usage_percent": "62.1%"
  },
  "alerts": {
    "service_down": false,
    "high_error_rate": false,
    "high_latency": false
  }
}
```

## 🖥️ 5. DASHBOARDS В GRAFANA

### Dashboard 1: Overview (Главный дашборд)
**Элементы:**
1. Status gauge (Healthy/Warning/Critical)
2. Request Rate (Graph)
3. Error Rate (Gauge)
4. P95 Latency (Graph)
5. System Resources (CPU/Memory/Disk)
6. Recent Errors (Table)
7. Payment Transactions (Stat)

### Dashboard 2: Payments (Платежи)
**Элементы:**
1. Total Transactions (Stat)
2. Successful Payments (Stat)
3. Failed Payments (Stat)
4. Success Rate (Gauge)
5. Payment Timeline (Graph)
6. Provider Distribution (Pie Chart)
7. Recent Payment Events (Table)

### Dashboard 3: Errors & Alerts
**Элементы:**
1. Error Rate Trend (Graph)
2. Top Errors (Table)
3. Alert Status (Alert list)
4. Error by Endpoint (Bar chart)
5. Response Time Distribution (Histogram)

## 📊 6. ИНТЕГРАЦИЯ С RENDER (Production)

### Переменные окружения для Render
```
DJANGO_DEBUG=False
DJANGO_SECURE_SSL_REDIRECT=True
LOGGING_LEVEL=INFO
```

### Мониторинг на Render
- Health check: `/api/health/`
- Metrics: `/api/metrics/`
- Logs: автоматический сбор в `/logs/`

## 🧪 7. ЛОКАЛЬНОЕ ТЕСТИРОВАНИЕ

### Запуск Django с логированием
```bash
# Создаем папку логов
mkdir -p logs

# Запускаем Django
python manage.py runserver

# Тестируем эндпоинты:
curl http://localhost:8000/api/health/
curl http://localhost:8000/api/metrics/
curl http://localhost:8000/api/metrics/summary/
```

### Просмотр логов платежей
```bash
# JSON логи платежей
tail -f logs/payments.json | jq .

# Все ошибки
tail -f logs/errors.json | jq .
```

### Load testing с Locust
```bash
# Установка
pip install locust

# Запуск load теста
locust -f locust_loadtest.py --users 100 --spawn-rate 10 --run-time 2m

# Результаты в web UI (http://localhost:8089)
```

## 📋 ЧЕКЛИСТ КОНФИГУРАЦИИ

- ✅ JSON логирование настроено — `cohub_app/logging_utils.py`
- ✅ Per-request JSON лог ключевых endpoints — `cohub_app/metrics_middleware.py` → `logs/requests.json`
- ✅ Middleware для метрик добавлен
- ✅ API эндпоинты для метрик созданы — `cohub_app/monitoring.py`
- ✅ Реальный стек Prometheus + Grafana + Alertmanager — `monitoring/docker-compose.yml`
- ✅ Импортируемый Grafana dashboard (4 золотых сигнала) — `monitoring/grafana/dashboards/cohub-golden-signals.json`
- ✅ Реальные правила алертов (server down / error rate / latency) — `monitoring/prometheus/alert_rules.yml`
- ✅ Load test на 100 пользователей + HTML-отчёт — `locust_loadtest.py`, `loadtest/run_loadtest.*`
- ✅ Документация написана — `monitoring/README.md`, этот файл, `ALERT_RULES.md`
- ✅ Настройки Django обновлены (LOGGING, MIDDLEWARE)

> 🚀 Быстрый старт стека мониторинга — см. **[monitoring/README.md](monitoring/README.md)**.
> Раннеры нагрузочного теста — **[loadtest/run_loadtest.ps1](loadtest/run_loadtest.ps1)** /
> **[loadtest/run_loadtest.sh](loadtest/run_loadtest.sh)**.

## 🚀 СЛЕДУЮЩИЕ ШАГИ

1. **Установить Grafana** (если локально):
   ```bash
   docker run -d -p 3000:3000 grafana/grafana
   ```

2. **Добавить Data Source** в Grafana:
   - Type: JSON API
   - URL: http://localhost:8000/api/metrics/

3. **Создать Dashboards** с предоставленными конфигурациями

4. **Настроить Alert Channels** (Email, Slack, PagerDuty)

5. **Запустить Load Test** для проверки метрик

## 📞 SUPPORT & CONTACTS

**Документация:**
- JSON Logging Format: [logging_utils.py](cohub_app/logging_utils.py)
- Metrics API: [monitoring.py](cohub_app/monitoring.py)
- Middleware: [metrics_middleware.py](cohub_app/metrics_middleware.py)

**Эндпоинты мониторинга:**
- Health: `/api/health/`
- Metrics (JSON): `/api/metrics/`
- Metrics (Prometheus): `/api/metrics/prometheus/`
- Summary: `/api/metrics/summary/`
