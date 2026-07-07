# Алерты в Telegram (Alertmanager → бот)

Prometheus следит за метриками CoHub и при проблеме (error rate / latency /
server down / насыщение CPU-RAM / платежи) отправляет алерт в Alertmanager, а тот
доставляет его вам в **Telegram** через бота.

> Важно: бот не может писать «на номер телефона». Он пишет в **чат** по его
> `chat_id`. Ниже — как получить токен бота и свой `chat_id`.

## Шаг 1. Создать бота и получить токен
1. В Telegram откройте **@BotFather** → команда `/newbot`.
2. Задайте имя и username бота. BotFather пришлёт **токен** вида
   `123456789:ABCdefGhIJKlmNoPQRstuVWxyz`.

## Шаг 2. Положить токен в файл (не в git)
Скопируйте пример и вставьте токен:
```bash
cp monitoring/alertmanager/secrets/telegram_bot_token.example \
   monitoring/alertmanager/secrets/telegram_bot_token
# отредактируйте файл — впишите только токен, одной строкой
```
Файл `telegram_bot_token` добавлен в `.gitignore` — секрет не попадёт в репозиторий.

## Шаг 3. Узнать свой chat_id
1. Найдите своего бота в Telegram и отправьте ему любое сообщение (например `/start`).
2. Откройте в браузере (подставив токен):
   `https://api.telegram.org/bot<ТОКЕН>/getUpdates`
3. В ответе найдите `"chat":{"id":123456789,...}` — это ваш `chat_id`.
   (Для группового чата id будет отрицательным, например `-1001234567890`.)

Впишите его в `monitoring/alertmanager/alertmanager.yml` → `chat_id:`.

## Шаг 4. Запустить стек мониторинга
```bash
docker compose -f monitoring/docker-compose.yml up -d
```
- Prometheus: http://localhost:9090
- Alertmanager: http://localhost:9093
- Grafana: http://localhost:3000 (admin/admin)

## Шаг 5. Проверить доставку
Быстрый способ — отправить тестовый алерт напрямую в Alertmanager:
```bash
curl -H 'Content-Type: application/json' -d '[{
  "labels": {"alertname":"TelegramTest","severity":"critical"},
  "annotations": {"summary":"Проверка связи","description":"Если видите это в Telegram — доставка работает"}
}]' http://localhost:9093/api/v2/alerts
```
Через несколько секунд бот пришлёт сообщение в ваш чат.

Проверить конфиг Alertmanager:
```bash
docker run --rm -v "$PWD/monitoring/alertmanager:/etc/alertmanager" \
  prom/alertmanager:v0.27.0 amtool check-config /etc/alertmanager/alertmanager.yml
```

## Что именно приходит
Правила алертов — в `monitoring/prometheus/alert_rules.yml`:
- **Server down** — `CohubServerDown` (`up{job="cohub"} == 0`, 1 мин).
- **Error rate** — `CohubHighErrorRate` (>5%), `CohubErrorStorm` (>50%, critical).
- **Latency** — `CohubHighLatency` (p95 > 5000 мс), `CohubElevatedLatency` (>2000 мс).
- Плюс насыщение CPU/RAM и платёжные алерты.

Все они маршрутизируются в один Telegram-получатель (`receiver: telegram`),
critical — с меньшей задержкой и повтором раз в час.
