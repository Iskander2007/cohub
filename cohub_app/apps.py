from django.apps import AppConfig


class CohubAppConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'cohub_app'
    verbose_name = 'COHUB'

    def ready(self):
        # Включаем для SQLite режим WAL и таймаут ожидания блокировки.
        # Без этого при конкурентной записи (например, нагрузочный тест на 100
        # пользователей) SQLite отдаёт "database is locked" и запросы падают с 500.
        # WAL разрешает читать во время записи, busy_timeout заставляет писателя
        # подождать освобождения блокировки вместо мгновенной ошибки.
        # На PostgreSQL (продакшен на Render) обработчик ничего не делает.
        from django.db.backends.signals import connection_created

        def _set_sqlite_pragmas(sender, connection, **kwargs):
            if connection.vendor != 'sqlite':
                return
            cursor = connection.cursor()
            cursor.execute('PRAGMA journal_mode=WAL;')
            cursor.execute('PRAGMA synchronous=NORMAL;')
            cursor.execute('PRAGMA busy_timeout=5000;')  # ждать блокировку до 5 c
            cursor.close()

        # dispatch_uid защищает от двойной регистрации при автоперезагрузке.
        connection_created.connect(_set_sqlite_pragmas, dispatch_uid='cohub_sqlite_pragmas')
