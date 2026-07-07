# 🚨 COHUB Alert Rules Configuration

> ℹ️ **Канонический источник правил — [`monitoring/prometheus/alert_rules.yml`](monitoring/prometheus/alert_rules.yml)**
> (его реально загружает Prometheus). Этот документ описывает политику алертов,
> каналы доставки и **эскалацию**. Важное уточнение: в проде «сервер недоступен»
> определяется по `up{job="cohub"} == 0` (алерт `CohubServerDown`), а условие
> `error_rate > 50%` (`CohubErrorStorm`) — это резервный признак отказа.
> Пошаговые действия по инцидентам — в **[PLAYBOOK.md](PLAYBOOK.md)**.

## Alert Rules (для Grafana & Prometheus)

### Файл: alert_rules.yaml

```yaml
# Группа правил для COHUB мониторинга
groups:
  - name: cohub_alerts
    interval: 30s  # Проверять каждые 30 секунд
    rules:
      
      # ALERT 1: SERVER DOWN. Канон (monitoring/prometheus/alert_rules.yml):
      # основной признак отказа — up{job="cohub"} == 0 (CohubServerDown, for 1m).
      # Ниже — резервный «шторм ошибок» по ОКОННОМУ error rate (recording rule).
      - alert: CohubErrorStorm
        expr: cohub:error_rate_5m:percent > 50
        for: 2m  # Срабатывает если условие true 2+ минуты
        labels:
          severity: critical
          team: backend
        annotations:
          summary: "🚨 COHUB Service DOWN"
          description: |
            Сервис недоступен!
            Current error rate: {{ $value }}%
            Instance: {{ $labels.instance }}
          runbook_url: "https://confluence.company.com/cohub/runbooks/service-down"
      
      # ALERT 2: HIGH ERROR RATE (> 5%)
      - alert: CohubHighErrorRate
        expr: cohub:error_rate_5m:percent > 5 and cohub:error_rate_5m:percent <= 50
        for: 5m  # 5 минут
        labels:
          severity: warning
          team: backend
        annotations:
          summary: "⚠️ High error rate detected"
          description: |
            Error rate выше нормы!
            Error rate: {{ $value }}%
            Threshold: 5%
          runbook_url: "https://confluence.company.com/cohub/runbooks/high-error-rate"
      
      # ALERT 3: HIGH P95 LATENCY (> 5 seconds)
      - alert: CohubHighLatency
        expr: cohub_p95_latency_ms > 5000
        for: 3m
        labels:
          severity: warning
          team: backend
        annotations:
          summary: "⚠️ High response latency"
          description: |
            P95 latency выше нормы!
            P95 Latency: {{ $value }}ms
            Threshold: 5000ms
      
      # ALERT 4: HIGH CPU USAGE (> 80%)
      - alert: CohubHighCPU
        expr: cohub_cpu_usage > 80
        for: 5m
        labels:
          severity: warning
          team: infrastructure
        annotations:
          summary: "⚠️ High CPU usage"
          description: "CPU usage: {{ $value }}%"
      
      # ALERT 5: HIGH MEMORY USAGE (> 85%)
      - alert: CohubHighMemory
        expr: cohub_memory_usage > 85
        for: 5m
        labels:
          severity: warning
          team: infrastructure
        annotations:
          summary: "⚠️ High memory usage"
          description: "Memory usage: {{ $value }}%"
      
      # ALERT 6: PAYMENT FAILURE RATE HIGH (> 10%). Канон считает ОКОННЫЙ failure
      # rate с guard'ом rate(payments_total)>0 (имя: CohubPaymentFailureRateHigh),
      # чтобы пустая система (0 платежей) не давала ложного срабатывания.
      - alert: CohubPaymentFailureRateHigh
        expr: cohub:payment_failure_rate_30m:percent > 10 and rate(cohub_payments_total[30m]) > 0
        for: 5m
        labels:
          severity: critical
          team: payments
        annotations:
          summary: "🚨 High payment failure rate"
          description: |
            Payment success rate упал ниже 90%!
            Success rate: {{ $value }}%
            Failed payments: {{ cohub_payments_failed }}
```

## Notification Channels

### Slack Integration

**Webhook URL:** `https://hooks.slack.com/services/YOUR/WEBHOOK/URL`

**Сообщение в Slack:**
```
🚨 ALERT: Service Down
━━━━━━━━━━━━━━━━━━━━━━━
Severity: CRITICAL
Error Rate: 67.5%
Time: 2024-06-24 10:30 UTC
Instance: render.com/cohub
Runbook: https://confluence/cohub/runbooks/service-down
```

### Email Notifications

**Адреса:**
- admin@cohub.dev (все alerts)
- devops@cohub.dev (infrastructure alerts)
- payments@cohub.dev (payment alerts)

**Шаблон письма:**
```
Subject: [ALERT] {{alert_name}} - {{severity}}

Body:
Alert: {{alert_name}}
Severity: {{severity}}
Description: {{description}}
Value: {{value}}
Time: {{timestamp}}

Runbook: {{runbook_url}}

---
Grafana Dashboard: http://grafana.cohub.dev/d/cohub-main
Metrics: http://cohub.dev/api/metrics/summary/
```

## Testing Alerts

### Создать тестовый alert

```bash
# 1. SSH на production сервер
ssh deploy@render.cohub.dev

# 2. Симулировать высокую ошибку rate (для теста)
# Это можно сделать через управление трафиком или отключение части сервиса

# 3. Проверить что alert сработал в Grafana
# Dashboard → Alerts → Alert Status

# 4. Проверить что уведомление пришло в Slack/Email
```

### Alert Status Dashboard

Переходим в Grafana → Alerting → Alert rules

- ✅ Firing alerts (активные)
- ⏸️ Paused rules (временно отключенные)
- ✓ Resolved alerts (разрешенные)

## Escalation Policy

```
Severity: CRITICAL
├─ Instant: Page on-call (SMS + Phone)
├─ +5 min: Escalate to team lead
├─ +15 min: Escalate to engineering manager
└─ +30 min: Fire the alert

Severity: WARNING
├─ Slack notification
├─ +1 hour: Email
└─ +4 hours: Escalate if not acknowledged
```

## Alert Routing Rules

> ℹ️ Ниже — иллюстрация на синтаксисе Alertmanager v1 (`match:`). В реальном
> `monitoring/alertmanager/alertmanager.yml` используется актуальный синтаксис
> `matchers:` (v2), маршрутизация по `severity`/`team` и inhibit-правила; реальные
> получатели Slack/SMTP оставлены заглушками — заполнить перед продом.

```yaml
# routing:
  receiver: 'default-receiver'
  
  routes:
    # Critical alerts - все каналы
    - match:
        severity: critical
      receiver: 'critical-team'
      group_wait: 10s      # Подождать 10сек перед отправкой
      group_interval: 1m   # Переотправлять каждую минуту
      repeat_interval: 4h  # Повторять каждые 4 часа
    
    # Payment alerts
    - match:
        team: payments
      receiver: 'payments-team'
      group_interval: 5m
    
    # Infrastructure alerts
    - match:
        team: infrastructure
      receiver: 'devops-team'
      group_interval: 10m

receivers:
  - name: 'critical-team'
    slack_configs:
      - channel: '#alerts-critical'
    email_configs:
      - to: 'admin@cohub.dev'
  
  - name: 'payments-team'
    slack_configs:
      - channel: '#payments-alerts'
  
  - name: 'devops-team'
    slack_configs:
      - channel: '#devops-alerts'
```

## Dashboard Quick Links

- 📊 [Main Dashboard](http://grafana.cohub.dev/d/cohub-main)
- 💰 [Payments Dashboard](http://grafana.cohub.dev/d/cohub-payments)
- ⚠️ [Alerts Dashboard](http://grafana.cohub.dev/d/cohub-alerts)
- 🔧 [System Dashboard](http://grafana.cohub.dev/d/cohub-system)

## Useful Commands

```bash
# Проверить статус alertmanager
curl http://localhost:9093/api/v1/alerts

# Получить текущие метрики
curl http://cohub.dev/api/metrics/

# Посмотреть health status
curl http://cohub.dev/api/health/

# Проверить логи платежей (последние 100 строк)
tail -n 100 logs/payments.json | jq .
```
