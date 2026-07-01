# ✅ COHUB · Production Readiness Checklist (24 пункта)

> **OPS-008.** Чек-лист готовности к эксплуатации. **Ровно 24 пункта**, сгруппированы
> по 6 разделам. Каждый пункт: **критерий приёмки → доказательство (файл/эндпоинт) →
> как проверить**. Документ готов к переносу в Confluence/Notion.
>
> **Итог: 24 / 24 пройдено ✅** (статус на 2026-06-30, ветка `feature/github-actions-ci`).
> Связанные документы: [PLAYBOOK.md](PLAYBOOK.md) · [MONITORING_NOTION.md](MONITORING_NOTION.md) · [ALERT_RULES.md](ALERT_RULES.md).

---

## A. Мониторинг и метрики (1–6)

- [x] **1. Стек мониторинга поднимается одной командой.** Prometheus + Alertmanager + Grafana.
  - 📁 `monitoring/docker-compose.yml`
  - 🔎 `docker compose -f monitoring/docker-compose.yml up -d` → 3 контейнера `Up`.
- [x] **2. Приложение экспонирует метрики в формате Prometheus.**
  - 📁 `cohub_app/monitoring.py` → `metrics_prometheus_format` (`text/plain; version=0.0.4`).
  - 🔎 `curl http://localhost:8000/api/metrics/prometheus/` → строки `cohub_*`.
- [x] **3. Prometheus скрейпит таргет `cohub` (target = UP).**
  - 📁 `monitoring/prometheus/prometheus.yml` (`metrics_path: /api/metrics/prometheus/`).
  - 🔎 Prometheus → Status → Targets → `cohub` = **UP**.
- [x] **4. Grafana подключает датасорс и дашборд автоматически (provisioning).**
  - 📁 `monitoring/grafana/provisioning/datasources/datasource.yml`, `.../dashboards/dashboards.yml`.
  - 🔎 После `up` в Grafana уже есть датасорс Prometheus (uid `prometheus`) и папка COHUB.
- [x] **5. Дашборд «4 золотых сигнала» содержит все 4 сигнала.** Traffic, Errors, Latency, Saturation (+ up, + платежи).
  - 📁 `monitoring/grafana/dashboards/cohub-golden-signals.json` (uid `cohub-golden-signals`).
  - 🔎 Grafana → COHUB → «COHUB · 4 золотых сигнала».
- [x] **6. Health-check возвращает 200 и проверяет зависимости (БД + кеш).**
  - 📁 `cohub_app/monitoring.py` → `health_check` (503 при проблеме).
  - 🔎 `curl -s http://localhost:8000/health/ | jq .` → `status: healthy`.

## B. Структурированное логирование (7–10)

- [x] **7. Логи пишутся в структурированном JSON.**
  - 📁 `cohub_app/logging_utils.py` → `JSONFormatter`; конфиг `LOGGING` в `cohub_settings/settings.py`.
- [x] **8. Ключевые endpoints логируются построчно (method/path/status/latency/user_id/request_id).**
  - 📁 `cohub_app/metrics_middleware.py` → `logs/requests.json`. Скрейп метрик исключён, чтобы не шуметь.
  - 🔎 `tail -n 5 logs/requests.json | jq .`.
- [x] **9. События платежей пишутся отдельным JSON-логом.**
  - 📁 `PaymentLogger` → `logs/payments.json` (initiated/pending/confirmed/failed/error/subscription_activated).
- [x] **10. Ошибки/5xx логируются отдельно; есть request_id для трейсинга.**
  - 📁 `logs/errors.json` (handler уровня ERROR); `request_id` валидируется и возвращается в заголовке `X-Request-ID`.

## C. Алерты (11–15)

- [x] **11. Алерт «сервер недоступен» (server down).**
  - 📁 `alert_rules.yml` → `CohubServerDown` (`up{job="cohub"} == 0`, for 1m, critical).
- [x] **12. Алерт «повышенный error rate».** Считается в **окне** (recording rule
  `cohub:error_rate_5m:percent` через `rate()`), а не из накопительного gauge — поэтому
  чувствителен к реальному всплеску ошибок.
  - 📁 `CohubHighErrorRate` (>5%, warning) + `CohubErrorStorm` (>50%, critical).
- [x] **13. Алерт «высокая задержка» (latency).**
  - 📁 `CohubHighLatency` (p95 > 5s, warning) + `CohubElevatedLatency` (>2s, info).
- [x] **14. Правила алертов загружены в Prometheus.**
  - 📁 `prometheus.yml` → `rule_files: alert_rules.yml`.
  - 🔎 Prometheus → Alerts → 8 правил видны.
- [x] **15. Маршрутизация и эскалация настроены; доставка — заглушка.** Роутинг по
  `severity`/`team`, inhibit-правила, политика эскалации — готовы. Реальные приёмники
  Slack/SMTP закомментированы (нет приватных секретов) — заполнить перед продом.
  - 📁 `monitoring/alertmanager/alertmanager.yml` + Escalation Policy в `ALERT_RULES.md`.

## D. Нагрузочное тестирование (16–18)

- [x] **16. Locust-сценарий имитирует 100 одновременных пользователей.** Регистрация (CAPTCHA+CSRF) → реалистичный микс действий.
  - 📁 `locust_loadtest.py`, раннеры `loadtest/run_loadtest.ps1` · `.sh`.
- [x] **17. Генерируется HTML-отчёт.**
  - 📁 `loadtest_report.html` (+ `loadtest_stats_*.csv`).
  - 🔎 `locust -f locust_loadtest.py --headless --users 100 --spawn-rate 10 --run-time 2m --host http://127.0.0.1:8000 --html loadtest_report.html`.
- [x] **18. Успешность под нагрузкой ≥ 95%.** Факт прогона: **98.8%** (2479 запросов, 30 ошибок), p95 ≈ 640 мс, avg ≈ 90 мс.
  - 📁 `loadtest_stats_stats.csv` (агрегат).

## E. Производительность и надёжность (19–21)

- [x] **19. Кеширование настроено.** Cache backend + кеш горячего эндпоинта метрик (`cache_page(5)`).
  - 📁 `cohub_settings/settings.py` → `CACHES`; `monitoring.py` → `@cache_page(5)`.
- [x] **20. Индексы БД для горячих запросов.**
  - 📁 миграция `0013_..._idx_...`: `order_user_status_idx`, `order_provider_ref_idx`, `payevent_order_time_idx`.
- [x] **21. Тяжёлые операции вынесены из веб-потока.** Фоновый воркер + планировщик.
  - 📁 `cohub_app/management/commands/run_worker.py`, `.../scheduler.py`, `cohub_app/tasks.py`.

## F. Безопасность и эксплуатация (22–24)

- [x] **22. Прод-секьюрность управляется через env и проверяется автоматически.** SSL-redirect, secure-cookies, HSTS.
  - 📁 `settings.py` (`SECURE_SSL_REDIRECT`, `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE`); `manage.py check --deploy` в CI.
- [x] **23. CI/CD-пайплайн зелёный + автотесты наблюдаемости.** Тесты на PostgreSQL,
  проверка отсутствия незакоммиченных миграций, секрет-скан. Эпик observability покрыт
  тестами (`ObservabilityTests`: health, Prometheus-формат, сводка, защита токеном,
  per-request лог, ветка 5xx→ERROR) — всего 72 теста.
  - 📁 `.github/workflows/ci.yml` (`migrate`, `test`, `check --deploy`, `check_secrets`, TruffleHog); `cohub_app/tests.py`.
  - 🔎 Локально: `python manage.py check` → 0 issues; `python manage.py test` → 72 OK.
- [x] **24. Документация эксплуатации написана.** Playbook (3 сценария) + правила алертов/эскалация + setup-гайд.
  - 📁 `PLAYBOOK.md`, `ALERT_RULES.md`, `MONITORING_NOTION.md`, `MONITORING_SETUP.md`, `monitoring/README.md`.

---

## 🧮 Сводка

| Раздел | Пунктов | Пройдено |
|---|---|---|
| A. Мониторинг и метрики | 6 | ✅ 6 |
| B. Логирование | 4 | ✅ 4 |
| C. Алерты | 5 | ✅ 5 |
| D. Нагрузочное тестирование | 3 | ✅ 3 |
| E. Производительность и надёжность | 3 | ✅ 3 |
| F. Безопасность и эксплуатация | 3 | ✅ 3 |
| **Итого** | **24** | **✅ 24 / 24** |

> 🔧 **Перед реальным продом** дозаполнить заглушки в `monitoring/alertmanager/alertmanager.yml`
> (Slack webhook + SMTP) — это единственный пункт, требующий приватных значений и потому
> оставленный конфигурируемым (пункт 15).
