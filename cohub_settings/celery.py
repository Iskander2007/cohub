"""Celery-приложение CoHub.

Фоновые задачи выполняются Celery-воркером через брокер Redis (см. REDIS_URL /
CELERY_BROKER_URL в settings.py). Задачи ищутся автоматически в <app>/tasks.py
(autodiscover_tasks), поэтому реальная задача живёт в cohub_app/tasks.py
(send_loan_reminder_task).

Локально/в тестах, когда брокера нет, включается режим CELERY_TASK_ALWAYS_EAGER —
задача выполняется синхронно в том же процессе, что удобно для юнит-тестов.
"""

import os

from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'cohub_settings.settings')

app = Celery('cohub')

# Все настройки берём из Django settings с префиксом CELERY_ (namespace='CELERY').
app.config_from_object('django.conf:settings', namespace='CELERY')

# Автопоиск задач в cohub_app/tasks.py и других приложениях.
app.autodiscover_tasks()


@app.task(bind=True, name='cohub.debug_task')
def debug_task(self):
    """Простейшая задача для проверки, что воркер жив (celery ... call cohub.debug_task)."""
    return f'ok:{self.request.id}'
