"""Чернорабочий очереди задач.

"""

import time

from django.core.management.base import BaseCommand

from cohub_app.tasks import run_pending_tasks, requeue_stale_tasks


class Command(BaseCommand):
    help = 'Разбирает фоновые задачи из таблицы BackgroundTask.'

    def add_arguments(self, parser):
        parser.add_argument('--once', action='store_true',
                            help='Обработать доступные задачи один раз и выйти.')
        parser.add_argument('--interval', type=float, default=5.0,
                            help='Пауза между опросами очереди, секунд.')
        parser.add_argument('--batch', type=int, default=10,
                            help='Сколько задач брать за один проход.')

    def handle(self, *args, **options):
        once = options['once']
        interval = options['interval']
        batch = options['batch']

        self.stdout.write(self.style.SUCCESS('Воркер очереди запущен'))
        # Подберём задачи, зависшие в 'running' после падения прошлого воркера.
        recovered = requeue_stale_tasks()
        if recovered:
            self.stdout.write(self.style.WARNING(f'Восстановлено зависших задач: {recovered}'))
        try:
            while True:
                count = run_pending_tasks(limit=batch)
                if count:
                    self.stdout.write(f'Обработано задач: {count}')
                if once:
                    break
                time.sleep(interval)
        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING('\nВоркер остановлен'))
