import os
import logging
from django.core.management import BaseCommand, call_command
from django.conf import settings
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)

scheduler = None


class Command(BaseCommand):
    help = 'Запускает фоновый планировщик для автоматического резервного копирования.'

    def handle(self, *args, **options):
        global scheduler
        
        if scheduler and scheduler.running:
            self.stdout.write(self.style.WARNING('Scheduler уже запущен'))
            return

        scheduler = BackgroundScheduler()
        
        # Получить настройки расписания из переменных окружения
        backup_enabled = os.environ.get('DJANGO_BACKUP_SCHEDULE_ENABLED', 'True').lower() in {'true', '1', 'yes'}
        backup_hour = int(os.environ.get('DJANGO_BACKUP_SCHEDULE_HOUR', '2'))
        backup_minute = int(os.environ.get('DJANGO_BACKUP_SCHEDULE_MINUTE', '0'))
        
        if backup_enabled:
            scheduler.add_job(
                self.backup_job,
                CronTrigger(hour=backup_hour, minute=backup_minute),
                id='backup_data',
                name='Daily Backup',
                misfire_grace_time=15 * 60,
                replace_existing=True
            )
            self.stdout.write(
                self.style.SUCCESS(
                    f'Backup запланирована на {backup_hour:02d}:{backup_minute:02d} каждый день'
                )
            )
        
        scheduler.start()
        self.stdout.write(self.style.SUCCESS('Scheduler запущен'))
        
        try:
            # Держать планировщик запущенным
            while True:
                pass
        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING('\nОстановка scheduler...'))
            scheduler.shutdown()
            self.stdout.write(self.style.SUCCESS('Scheduler остановлен'))

    @staticmethod
    def backup_job():
        """Выполнить backup_data команду"""
        logger.info('Starting scheduled backup...')
        try:
            call_command(
                'backup_data',
                output_dir=os.path.join(
                    settings.BASE_DIR, 
                    os.environ.get('DJANGO_BACKUP_DIR', 'backups')
                ),
                compress=os.environ.get('DJANGO_BACKUP_COMPRESS', 'True').lower() in {'true', '1', 'yes'},
            )
            logger.info('Backup completed successfully')
        except Exception as e:
            logger.error(f'Backup failed: {e}')
