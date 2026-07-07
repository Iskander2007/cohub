# Кэширование (Redis)

## Конфигурация
`cohub_settings/settings.py`: если задан `REDIS_URL` — используется `RedisCache`,
иначе локальный `LocMemCache`. Пакет `redis` теперь в `requirements.txt`, а в
`docker-compose.yml` и `render.yaml` поднимается Redis и прокидывается `REDIS_URL`.

## Кэшируемые эндпоинты (>2)
| Эндпоинт | Что кэшируется | TTL |
|----------|----------------|-----|
| `GET /api/metrics/` | общий payload метрик (`_get_cached_metrics`) | 5 c |
| `GET /api/metrics/prometheus/` | тот же payload (для скрейпа Grafana) | 5 c |
| `GET /api/metrics/summary/` | тот же payload | 5 c |
| `GET /api/rooms/{id}/assistant/` | результат ИИ-ассистента (low-level cache) | 120 c |

Метрики берут CPU/RAM через `psutil.cpu_percent(interval=0.1)` — это **блокирует
~100 мс** на каждый вызов. Кэш убирает эту задержку для всех трёх метрик-эндпоинтов.

## Замер curl «до/после»
```bash
# без кэша (первый запрос наполняет кэш) vs из кэша (второй запрос)
curl -s -o /dev/null -w 'первый (miss): %{time_total}s\n'  http://localhost:8000/api/metrics/prometheus/
curl -s -o /dev/null -w 'второй (hit):  %{time_total}s\n'  http://localhost:8000/api/metrics/prometheus/
```
Ожидаемо: первый ответ ≈ 0.1 c+ (сбор psutil), второй — единицы миллисекунд.

## Тест
`cohub_app/tests.py::MetricsCacheTests` проверяет, что после запроса payload
метрик лежит в кэше и что три метрик-эндпоинта его используют.
