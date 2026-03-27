import gzip
from pathlib import Path

from django.conf import settings
from django.core.management import BaseCommand, call_command
from django.utils import timezone


class Command(BaseCommand):
    help = 'Создает JSON-резервную копию пользователей и данных cohub_app.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--output-dir',
            default=str(Path(settings.BASE_DIR) / 'backups'),
            help='Каталог, в который будет сохранена резервная копия.',
        )
        parser.add_argument(
            '--compress',
            action='store_true',
            help='Сохранить backup в формате .json.gz',
        )

    def handle(self, *args, **options):
        output_dir = Path(options['output_dir'])
        output_dir.mkdir(parents=True, exist_ok=True)

        timestamp = timezone.now().strftime('%Y%m%d-%H%M%S')
        suffix = 'json.gz' if options['compress'] else 'json'
        output_path = output_dir / f'cohub-backup-{timestamp}.{suffix}'
        open_file = gzip.open if options['compress'] else open

        with open_file(output_path, 'wt', encoding='utf-8') as output_handle:
            call_command(
                'dumpdata',
                'auth',
                'cohub_app',
                exclude=['contenttypes', 'sessions', 'admin.logentry'],
                indent=2,
                natural_foreign=True,
                natural_primary=True,
                stdout=output_handle,
            )

        self.stdout.write(self.style.SUCCESS(f'Backup created: {output_path}'))