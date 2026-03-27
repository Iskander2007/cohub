# Руководство по развертыванию COHUB на бесплатном хостинге

## 1. Переменные окружения (Environment Variables)

### Общие параметры безопасности

Все переменные окружения должны быть установлены на вашем хостинге:

```
DJANGO_SECRET_KEY=<безопасный-ключ>
DJANGO_DEBUG=False
DJANGO_ALLOWED_HOSTS=yourdomain.com,www.yourdomain.com
DJANGO_CSRF_TRUSTED_ORIGINS=https://yourdomain.com,https://www.yourdomain.com

# HTTPS параметры
DJANGO_SECURE_SSL_REDIRECT=True
DJANGO_SESSION_COOKIE_SECURE=True
DJANGO_CSRF_COOKIE_SECURE=True
DJANGO_SECURE_HSTS_SECONDS=31536000
DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS=True
DJANGO_SECURE_HSTS_PRELOAD=True
```

### Получение SECRET_KEY

```bash
python manage.py shell
from django.core.management.utils import get_random_secret_key
print(get_random_secret_key())
```

## 2. Рекомендуемые бесплатные хостинги

### Railway.app (Рекомендуется)

Railway предоставляет:
- Бесплатные 5$ в месяц кредиты
- PostgreSQL БД
- Автоматический деплой из GitHub
- Бесплатный SSL/TLS

**Шаги развертывания:**

1. Создайте аккаунт на https://railway.app
2. Свяжите ваш GitHub репозиторий
3. Создайте новый проект
4. Добавьте PostgreSQL плагин
5. Переменные окружения установите в Settings -> Environment
6. Railway автоматически запустит ваше приложение используя Procfile

**Для Railway вам нужен Procfile (уже есть в проекте):**
```
web: gunicorn cohub_settings.wsgi --log-file -
release: python manage.py migrate
scheduler: python manage.py scheduler
```

### Heroku (Legacy - платный)
Heroku больше не предоставляет бесплатный хостинг.

### PythonAnywhere

1. Создайте аккаунт на https://pythonanywhere.com
2. Загрузьте ваш код через Git
3. Установите зависимости: `pip install -r requirements.txt`
4. Настройте Web app с Django
5. Переменные окружения: веб-интерфейс -> Web app -> Environment variables
6. Для резервного копирования используйте Tasks -> Scheduled tasks

### Render.com

1. Создайте аккаунт на https://render.com
2. Создайте новый Web Service из GitHub
3. Environment установите в Settings
4. Запустите миграции в Shell
5. Для backup используйте Render Crons

### Glitch.com

Подходит для обучения, но ограничен по возможностям для production.

## 3. Автоматическое резервное копирование

### Опция 1: APScheduler (встроенный в Django)

Запустить в отдельном процессе на хостинге:

```bash
python manage.py scheduler
```

Когда scheduler запущен, он будет автоматически создавать backup каждый день в 02:00 (UTC).

Параметры в .env:
```
DJANGO_BACKUP_SCHEDULE_ENABLED=True
DJANGO_BACKUP_SCHEDULE_HOUR=2
DJANGO_BACKUP_SCHEDULE_MINUTE=0
DJANGO_BACKUP_COMPRESS=True
```

### Опция 2: Railway Cron Jobs

Добавьте в Procfile:
```
scheduler: python manage.py scheduler
```

И восстановите приложение вручную или используйте webhook для запуска.

### Опция 3: PythonAnywhere Scheduled Tasks

1. Перейдите в Tasks
2. Создайте новую задачу
3. Время: каждый день в 02:00
4. Команда:
```bash
cd /home/yourusername/cohub && python manage.py backup_data --compress
```

### Опция 4: Render Scheduled Jobs

1. Создайте Scheduled Job в Render
2. Команда: `python manage.py backup_data --compress`
3. Cron schedule: `0 2 * * *` (2:00 AM UTC каждый день)

### Опция 5: Windows Task Scheduler (локально)

Используйте batch-скрипт `backup_daily.bat`:

1. Откройте Task Scheduler
2. Создайте Basic Task
3. Trigger: Daily в нужное время
4. Action: Run `backup_daily.bat`

## 4. Процесс миграции базы данных

Перед первым запуском выполните:

```bash
python manage.py migrate
python manage.py collectstatic --noinput
```

На хостинге это обычно запускается автоматически через Release command в Procfile:
```
release: python manage.py migrate && python manage.py collectstatic --noinput
```

## 5. Локальное тестирование перед развертыванием

```bash
# Установка зависимостей
pip install -r requirements.txt

# Загрузить переменные окружения
source .env  # Linux/Mac
# или Windows: set не нужно, используется .venv

# Запустить локально с production-подобными параметрами
DEBUG=False python manage.py runserver
```

## 6. Обновление зависимостей

```bash
pip install --upgrade -r requirements.txt
```

Новые пакеты добавлены:
- `APScheduler==3.10.4` - для фонового планировщика
- `python-dotenv==1.0.0` - для загрузки переменных из .env файла

## 7. Безопасность на production

✅ **Уже настроено в проекте:**
- SECRET_KEY из переменных окружения
- DEBUG=False на production
- CSRF protection
- HSTS (HTTP Strict Transport Security)
- Secure cookies
- Click-jacking protection
- Host header validation
- Rate limiting

**Дополнительно проверьте:**
- SSL сертификат установлен (автоматически на Railway/Render)
- ALLOWED_HOSTS и CSRF_TRUSTED_ORIGINS точны
- Регулярно резервное копирование
- Логирование и мониторинг

## 8. Мониторинг резервных копий

Backups сохраняются в папке `backups/`:
```
backups/
  ├── cohub-backup-20240328-140000.json.gz
  ├── cohub-backup-20240327-140000.json.gz
  └── ...
```

Примечание: Убедитесь, что папка `backups/` синхронизируется с облаком или регулярно загружается!

### Railway.app примечание
На Railway файловая система происходит удаление при перезапуске. 
**Решение:** Используйте backup_upload.py скрипт для загрузки backups в облако (S3, Google Drive и т.д.)

## 9. Восстановление из backup

```bash
python manage.py loaddata backups/cohub-backup-YYYYMMDD-HHMMSS.json
```

## 10. Проблемы и решения

### Проблема: "Disallowed Host"
**Решение:** Обновите DJANGO_ALLOWED_HOSTS в переменных окружения на хостинге

### Проблема: Backup не запускается
**Решение:** 
- Проверьте DJANGO_BACKUP_SCHEDULE_ENABLED=True
- Проверьте логи хостинга
- Убедитесь что scheduler процесс запущен

### Проблема: Статические файлы не загружаются
**Решение:** Выполните `python manage.py collectstatic --noinput`

### Проблема: Ошибка SSL redirect
**Решение:** Убедитесь что хостер предоставляет SSL сертификат

## 11. Дополнительная поддержка

Если вам нужна помощь с конкретным хостингом:
- Railway: https://docs.railway.app/
- Render: https://render.com/docs
- PythonAnywhere: https://help.pythonanywhere.com/
- Heroku: https://devcenter.heroku.com/

