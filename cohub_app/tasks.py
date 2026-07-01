
import logging

from django.db import connection, transaction
from django.db.models import F
from django.utils import timezone

from .models import BackgroundTask

logger = logging.getLogger(__name__)

TASK_REGISTRY = {}

# Задача, провисевшая в статусе 'running' дольше этого времени, считается
# брошенной (воркер умер на полпути) и возвращается в очередь.
STALE_RUNNING_TIMEOUT = 600


def requeue_stale_tasks(timeout_seconds=STALE_RUNNING_TIMEOUT):
    """Вернуть в очередь задачи, зависшие в 'running'.

    Если воркер был убит (деплой/OOM) между захватом задачи и её завершением,
    строка осталась бы в 'running' навсегда. Возвращаем такие задачи в pending,
    чтобы они переобработались. Возвращает число восстановленных задач.
    """
    cutoff = timezone.now() - timezone.timedelta(seconds=timeout_seconds)
    return BackgroundTask.objects.filter(status='running', started_at__lt=cutoff).update(status='pending')


def register_task(name):
    """Декоратор: регистрирует функцию как обработчик задачи с именем `name`."""
    def decorator(func):
        TASK_REGISTRY[name] = func
        return func
    return decorator


def enqueue(task_name, **payload):
    """Положить задачу в очередь. Ничего не выполняет — только создаёт запись."""
    return BackgroundTask.objects.create(task_name=task_name, payload=payload)


def _claim_next_task():
  
    with transaction.atomic():
        qs = BackgroundTask.objects.filter(status='pending').order_by('created_at')
        if connection.features.has_select_for_update:
            lock_kwargs = {}
            if connection.features.has_select_for_update_skip_locked:
                lock_kwargs['skip_locked'] = True
            qs = qs.select_for_update(**lock_kwargs)

        task = qs.first()
        if task is None:
            return None

        # Атомарный захват: переводим в 'running' только если задача всё ещё
        # 'pending'. На бэкендах без SELECT FOR UPDATE (например, SQLite) это
        # не даёт двум воркерам выполнить одну и ту же задачу дважды.
        claimed = BackgroundTask.objects.filter(id=task.id, status='pending').update(
            status='running',
            attempts=F('attempts') + 1,
            started_at=timezone.now(),
        )
        if not claimed:
            return None
        task.refresh_from_db()
        return task


def run_pending_tasks(limit=10):
    """Выполнить до `limit` задач из очереди. Возвращает число обработанных."""
    processed = 0
    for _ in range(limit):
        task = _claim_next_task()
        if task is None:
            break

        handler = TASK_REGISTRY.get(task.task_name)
        try:
            if handler is None:
                raise ValueError(f'Неизвестная задача: {task.task_name}')
            result = handler(**task.payload)
            task.status = 'done'
            task.result = str(result) if result is not None else 'ok'
        except Exception as exc:  # noqa: BLE001 — логируем любую ошибку задачи
            logger.exception('Задача %s упала', task.task_name)
            task.result = str(exc)
            # Если попытки не исчерпаны — вернём в очередь для повтора.
            task.status = 'pending' if task.attempts < task.max_attempts else 'failed'

        update_fields = ['status', 'result']
        # finished_at проставляем только для терминальных статусов; задача,
        # возвращённая в 'pending' для повтора, ещё не завершена.
        if task.status in ('done', 'failed'):
            task.finished_at = timezone.now()
            update_fields.append('finished_at')
        task.save(update_fields=update_fields)
        processed += 1

    return processed


# --- Обработчики задач -------------------------------------------------------

@register_task('send_loan_reminder')
def send_loan_reminder(loan_id):
    """Фоновая отправка напоминания по долгу.

    Здесь могла бы быть отправка email/push. Пока просто фиксируем факт
    напоминания в самой модели Loan (поля уже есть).
    """
    from .models import Loan

    loan = Loan.objects.get(id=loan_id)
    loan.last_reminder_sent_at = timezone.now()
    loan.reminder_count += 1
    loan.save(update_fields=['last_reminder_sent_at', 'reminder_count', 'updated_at'])
    return f'Напоминание #{loan.reminder_count} по долгу {loan_id}'
