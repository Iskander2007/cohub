"""Лог запросов «до/после» для устранения N+1 (задача производительности БД).

Сеет временные данные (в транзакции, которая откатывается — БД не меняется),
затем печатает число SQL-запросов при НАИВНОЙ загрузке (обращение к FK в цикле
→ N+1) и при ОПТИМИЗИРОВАННОЙ (select_related). Разница и есть доказательство
устранения N+1.

Запуск:
    python manage.py nplusone_report --rows 20
"""

from django.contrib.auth.models import User
from django.core.management import BaseCommand
from django.db import connection, transaction
from django.test.utils import CaptureQueriesContext

from cohub_app.models import Room, Task


class _Rollback(Exception):
    """Служебное исключение: откатывает временные данные после замера."""


class Command(BaseCommand):
    help = 'Печатает число SQL-запросов до/после устранения N+1 (Task → room/assigned_to).'

    def add_arguments(self, parser):
        parser.add_argument('--rows', type=int, default=20, help='Сколько задач создать для замера.')

    def handle(self, *args, **options):
        rows = options['rows']

        try:
            with transaction.atomic():
                owner = User.objects.create_user(
                    username='nplusone-demo@example.com', password='demo-pass-123'
                )
                room = Room.objects.create(name='N+1 demo', code='NP1DEMO', owner=owner)
                for i in range(rows):
                    Task.objects.create(room=room, title=f'Task {i}', created_by=owner, assigned_to=owner)

                # --- ДО: наивная загрузка (N+1) ---
                with CaptureQueriesContext(connection) as naive:
                    for task in Task.objects.filter(room=room):
                        _ = task.room.name              # +1 запрос на каждую задачу
                        _ = task.assigned_to.username   # ещё +1 запрос на каждую задачу
                naive_count = len(naive.captured_queries)

                # --- ПОСЛЕ: select_related (константа) ---
                with CaptureQueriesContext(connection) as optimized:
                    for task in Task.objects.filter(room=room).select_related('room', 'assigned_to'):
                        _ = task.room.name
                        _ = task.assigned_to.username
                optimized_count = len(optimized.captured_queries)

                self.stdout.write('')
                self.stdout.write(self.style.MIGRATE_HEADING('N+1 отчёт (лог запросов до/после)'))
                self.stdout.write(f'  Задач в выборке:            {rows}')
                self.stdout.write(f'  ДО  (наивно, N+1):          {naive_count} запросов')
                self.stdout.write(f'  ПОСЛЕ (select_related):     {optimized_count} запрос(а)')
                saved = naive_count - optimized_count
                self.stdout.write(self.style.SUCCESS(f'  Устранено запросов:         {saved}'))
                self.stdout.write('')

                raise _Rollback  # откат: временные данные не остаются в БД
        except _Rollback:
            pass
