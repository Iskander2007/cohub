# Производительность БД: N+1 и индексы

Задача чек-листа: устранить N+1, добавить ≥2 индекса, показать **лог запросов
до/после** и файл миграции.

## Индексы (8 штук, миграции 0010/0011/0013)
| Индекс | Модель | Поля | Миграция |
|--------|--------|------|----------|
| `chat_room_created_idx` | ChatMessage | room, created_at | 0010 |
| `expense_room_date_idx` | Expense | room, date | 0010 |
| `task_room_status_idx` | Task | room, status | 0010 |
| `task_assignee_status_idx` | Task | assigned_to, status | 0010 |
| `bgtask_status_created_idx` | BackgroundTask | status, created_at | 0011 |
| `order_user_status_idx` | Order | user, status | 0013 |
| `order_provider_ref_idx` | Order | provider, provider_order_id | 0013 |
| `payevent_order_time_idx` | PaymentEvent | order, created_at | 0013 |

## N+1: исправление через select_related / prefetch_related
В `views.py` списковые выборки подгружают связи заранее (напр. `TaskViewSet`,
`ExpenseViewSet.get_queryset` c `prefetch_related('shares__user')`,
`LoanViewSet` c `select_related`). Это убирает лишние запросы на каждую строку.

## Лог запросов «до/после» (воспроизводимо)
Команда сеет временные данные (в транзакции, которая откатывается) и печатает
число SQL-запросов при наивной загрузке и при `select_related`:

```bash
python manage.py nplusone_report --rows 20
```

Пример вывода (20 задач, обращение к `task.room` и `task.assigned_to` в цикле):

```
N+1 отчёт (лог запросов до/после)
  Задач в выборке:            20
  ДО  (наивно, N+1):          41 запросов        # 1 + 2*20
  ПОСЛЕ (select_related):     1 запрос(а)
  Устранено запросов:         40
```

## Автотест (регрессия)
`cohub_app/tests.py::NPlusOneQueryTests::test_select_related_reduces_query_count`
доказывает, что оптимизированная выборка укладывается в **1 запрос**
(`assertNumQueries(1)`), а наивная делает заметно больше. Тест гоняется в CI.
