# 🛠️ COHUB · Runbook (если ведущего разработчика нет рядом)

Короткая инструкция: как запустить, проверить и починить COHUB своими силами.
Подробный разбор аварий — в `PLAYBOOK.md`. Ход мысли для «а что если…» — в `SCENARIOS.md`.

---

## Что это

COHUB — сайт на Django (комнаты, задачи, расходы, чат, подписки и платежи).
- База: SQLite локально, PostgreSQL в проде.
- Хостинг: **Render** (деплой сам из git).
- Мониторинг: Prometheus + Grafana + Alertmanager (папка `monitoring/`).

---

## 🚦 Главные правила (чтобы не сделать хуже)

1. Сначала **верни сервис в строй**, потом разбирайся почему. Откат и перезапуск — важнее «понять».
2. Если сломалось **сразу после релиза** — откати релиз, не чини на ходу.
3. **Базу руками не трогай** (никаких ручных правок данных).
4. **Секреты не коммить** в git. Чужие ключи (PayPal, PostHog) не меняй без владельца.
5. Не делай `push --force`. Не увеличивай число воркеров gunicorn (сломает метрики).
6. Не уверен — **спроси/эскалируй**, а не делай необратимое.

---

## ⏱️ Первым делом (30 секунд)

```bash
curl -s https://<АДРЕС_САЙТА>/health/
```
- Ответ `200` и `"status":"ok"` → сайт живой.
- Не отвечает или ошибка → это авария, открой `PLAYBOOK.md`.

---

## ▶️ Как запустить локально

```bash
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```
Открыть: http://localhost:8000
Готовые скрипты: `run_server.bat` (Windows), `bash run_server.sh` (Mac/Linux).

Полный стек как на проде (Postgres + Redis + Celery):
```bash
docker compose up --build
```

---

## 🚀 Прод (Render)

Деплой происходит **сам**: пуш в ветку `main` → проходит проверка → Render обновляет сайт.

Вручную (Render Dashboard → выбрать сервис):
- **Перезапустить:** Manual Deploy → Restart.
- **Откатить:** Deploys → выбрать прошлую рабочую версию → Rollback.

Откат через git (пуш в `main` сам запускает деплой):
```bash
git revert <плохой_коммит> && git push origin main
```

---

## 🧰 Частые команды

```bash
# Создать администратора
python manage.py createsuperuser

# Бэкап базы (файл появится в папке backups/)
python manage.py backup_data --compress

# Восстановить из бэкапа (осторожно — перезапись данных)
python manage.py restore_data <файл_из_backups>

# Посмотреть последние ошибки
tail -n 50 logs/errors.json | jq .

# Самые медленные запросы
tail -n 500 logs/requests.json | jq -r '[.latency_ms, .path] | @tsv' | sort -rn | head
```

> Для команд с логами нужен `jq`. Файлы `logs/*.json` есть локально и в консоли сервера.
> На проде (Render) логи смотри в панели: сервис → **Logs**.

---

## 📊 Мониторинг

Поднять локально:
```bash
docker compose -f monitoring/docker-compose.yml up -d
```

| Что | Адрес |
|---|---|
| Grafana (графики) | http://localhost:3000 |
| Prometheus (метрики, алерты) | http://localhost:9090 |
| Alertmanager (активные алерты) | http://localhost:9093 |
| Проверка сайта | `GET /health/` |
| Сводка + что горит | `GET /api/metrics/summary/` |

Алерты приходят в **Telegram** (настроено в `monitoring/alertmanager/alertmanager.yml`).
Заменить бота/чат — см. `monitoring/TELEGRAM_ALERTS.md`.

---

## 🚨 Если что-то сломалось

Полные инструкции — в `PLAYBOOK.md`. Коротко:

| Симптом | Что это | Куда смотреть |
|---|---|---|
| Сайт не открывается | Сервер лёг | PLAYBOOK → Server Down |
| Часть запросов с ошибкой | High Error Rate | `logs/errors.json`, откат релиза |
| Всё медленно, но без ошибок | High Latency | Grafana (CPU/RAM), `logs/requests.json` |
| Платежи не проходят | Проблема с оплатой | `logs/payments.json`, статус PayPal |

Самый быстрый фикс почти всегда — **откат релиза или перезапуск**.

---

## ✅ Проверка раз в день (пока ведущего нет)

- [ ] `GET /health/` отвечает `ok`
- [ ] В Grafana ошибок мало, скорость нормальная, сервер зелёный
- [ ] За сутки появился свежий бэкап в `backups/`
- [ ] Нет новых ошибок: `tail logs/errors.json | jq .`
