"""Локальная проверка секретов и небезопасной конфигурации.

Запуск:  python manage.py check_secrets

Проверяет:
  1) что файл .env НЕ отслеживается git (его нельзя коммитить);
  2) что .env присутствует в .gitignore;
  3) что DJANGO_SECRET_KEY задан и не равен небезопасному значению по умолчанию;
  4) что в продакшене (DJANGO_DEBUG=False) включены ключевые HTTPS-настройки.

Команда дополняет автоматическое сканирование trufflehog в CI: trufflehog ищет
утёкшие секреты в истории git, а эта команда — ошибки конфигурации здесь и сейчас.
Возвращает ненулевой код выхода при найденных проблемах (удобно для CI).
"""

import subprocess
import sys
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

INSECURE_DEFAULT_KEY = 'django-insecure-your-secret-key-change-in-production'


class Command(BaseCommand):
    help = 'Проверяет, что секреты не попали в git и настройки безопасны.'

    def handle(self, *args, **options):
        problems = []
        warnings = []
        base_dir = Path(settings.BASE_DIR)

        # 1) .env не должен быть в индексе git.
        try:
            tracked = subprocess.run(
                ['git', 'ls-files', '--error-unmatch', '.env'],
                cwd=base_dir, capture_output=True, text=True,
            )
            if tracked.returncode == 0:
                problems.append('Файл .env отслеживается git — удалите его из индекса (git rm --cached .env).')
        except FileNotFoundError:
            warnings.append('git не найден — пропускаю проверку отслеживания .env.')

        # 2) .env должен быть в .gitignore.
        gitignore = base_dir / '.gitignore'
        if gitignore.exists():
            if '.env' not in gitignore.read_text(encoding='utf-8', errors='ignore'):
                problems.append('.env отсутствует в .gitignore.')
        else:
            warnings.append('.gitignore не найден.')

        # 3) SECRET_KEY.
        if not settings.SECRET_KEY:
            problems.append('DJANGO_SECRET_KEY не задан.')
        elif settings.SECRET_KEY == INSECURE_DEFAULT_KEY:
            problems.append('Используется небезопасный SECRET_KEY по умолчанию — задайте свой.')
        elif settings.SECRET_KEY.startswith('django-insecure-'):
            warnings.append('SECRET_KEY помечен как insecure — для продакшена сгенерируйте новый.')

        # 4) Продакшен-настройки HTTPS при выключенном DEBUG.
        if not settings.DEBUG:
            if not settings.SECURE_SSL_REDIRECT:
                warnings.append('DEBUG=False, но SECURE_SSL_REDIRECT выключен.')
            if not settings.SESSION_COOKIE_SECURE:
                warnings.append('DEBUG=False, но SESSION_COOKIE_SECURE выключен.')
            if not settings.CSRF_COOKIE_SECURE:
                warnings.append('DEBUG=False, но CSRF_COOKIE_SECURE выключен.')

        for w in warnings:
            self.stdout.write(self.style.WARNING(f'[warn] {w}'))

        if problems:
            for p in problems:
                self.stdout.write(self.style.ERROR(f'[fail] {p}'))
            self.stderr.write(self.style.ERROR(f'Найдено проблем: {len(problems)}'))
            sys.exit(1)

        self.stdout.write(self.style.SUCCESS('Аудит секретов пройден: критичных проблем не найдено.'))
