# Загружаем Celery-приложение при старте Django, чтобы декоратор @shared_task
# в cohub_app/tasks.py привязывался к нему. Если celery не установлен (например,
# в урезанном окружении), приложение продолжает работать через встроенный
# DB-воркер (manage.py run_worker) — импорт не роняет проект.
try:
    from .celery import app as celery_app

    __all__ = ('celery_app',)
except ImportError:  # celery не установлен — деградируем к DB-воркеру
    celery_app = None
    __all__ = ()
except Exception:  # pragma: no cover - реальная ошибка bootstrap Celery: логируем, не молчим
    import logging

    logging.getLogger(__name__).warning(
        'Не удалось инициализировать Celery-приложение; фон переходит на DB-воркер.',
        exc_info=True,
    )
    celery_app = None
    __all__ = ()
