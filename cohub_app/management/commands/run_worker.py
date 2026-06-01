"""Воркер очереди задач.

Запуск:
  python manage.py run_worker            # бесконечный цикл (для прода/воркера)
  python manage.py run_worker --once     # один проход и выход (удобно в тестах)
"""

import time

from django.core.management.base import BaseCommand

from cohub_app.tasks import run_pending_tasks


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
