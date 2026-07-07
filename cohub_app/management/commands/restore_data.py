"""Восстановление данных из резервной копии, созданной backup_data.

Загружает JSON(.gz)-дамп (users + данные cohub_app) обратно в БД через loaddata.
loaddata сам распознаёт сжатие по расширению (.json.gz → gzip + json).

Использование:
    python manage.py restore_data backups/cohub-backup-20260707-020000.json.gz
    python manage.py restore_data            # взять самый свежий бэкап из каталога
"""

import glob
from pathlib import Path

from django.conf import settings
from django.core.management import BaseCommand, CommandError, call_command


class Command(BaseCommand):
    help = 'Восстанавливает данные из JSON-бэкапа (см. backup_data).'

    def add_arguments(self, parser):
        parser.add_argument(
            'backup_file',
            nargs='?',
            default=None,
            help='Путь к cohub-backup-*.json[.gz]. Если не задан — берётся самый свежий из каталога бэкапов.',
        )
        parser.add_argument(
            '--backup-dir',
            default=str(Path(settings.BASE_DIR) / 'backups'),
            help='Каталог с бэкапами (для авто-выбора самого свежего файла).',
        )

    def handle(self, *args, **options):
        backup_file = options['backup_file']

        if not backup_file:
            backup_dir = Path(options['backup_dir'])
            candidates = sorted(glob.glob(str(backup_dir / 'cohub-backup-*.json*')))
            if not candidates:
                raise CommandError(f'В каталоге {backup_dir} нет файлов cohub-backup-*.json[.gz]')
            backup_file = candidates[-1]

        path = Path(backup_file)
        if not path.exists():
            raise CommandError(f'Файл резервной копии не найден: {path}')

        self.stdout.write(f'Восстановление данных из {path} ...')
        # loaddata распознаёт .gz по расширению и восстанавливает natural keys.
        call_command('loaddata', str(path))
        self.stdout.write(self.style.SUCCESS(f'Данные успешно восстановлены из {path}'))
