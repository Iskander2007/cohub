# COHUB - Быстрая справка по развертыванию

## 🎯 ЧТО БЫЛО СДЕЛАНО

### ✅ Безопасность
- [x] **DJANGO_SECRET_KEY** - сгенерирован безопасный ключ
- [x] **DJANGO_ALLOWED_HOSTS** - настроены хосты для localhost и production
- [x] **DJANGO_CSRF_TRUSTED_ORIGINS** - настроены CSRF origins
- [x] **HTTPS параметры** - включены все security headers:
  - DJANGO_SECURE_SSL_REDIRECT
  - DJANGO_SESSION_COOKIE_SECURE
  - DJANGO_CSRF_COOKIE_SECURE
  - DJANGO_SECURE_HSTS_SECONDS=31536000 (1 год)

### ✅ Резервное копирование
- [x] **Scheduler** - создан management command для автоматического backup
- [x] **APScheduler** - интегрирован для фонового планирования
- [x] **Расписание** - резервные копии создаются каждый день (по умолчанию 2:00 AM UTC)
- [x] **Облачные сервисы** - поддержка S3, Google Drive, локальной сети

### ✅ Конфигурация
- [x] **.env** - конфигурация для развития (localhost)
- [x] **.env.production** - шаблон для production
- [x] **.env.example** - документация переменных
- [x] **settings.py** - обновлен для загрузки .env

### ✅ Документация
- [x] **HOSTING_GUIDE.md** - полное руководство по всем хостингам
- [x] **DEPLOYMENT_SUMMARY.md** - подробное резюме всех изменений
- [x] **check_deployment.py** - скрипт для проверки конфигурации

---

## 🚀 БЫСТРЫЙ СТАРТ НА ХОСТИНГЕ

### 1. Выберите хостинг (Railway.app рекомендуется)
```
Railway.app → самый простой, 5$ бесплатных кредитов
Render.com → бесплатный tier
PythonAnywhere → бесплатный tier (ограниченно)
```

### 2. Подготовьте .env.production
```bash
# Отредактируйте .env.production и установите:
DJANGO_SECRET_KEY=<ваш-ключ-из-check>
DJANGO_ALLOWED_HOSTS=yourdomain.com,www.yourdomain.com
DJANGO_CSRF_TRUSTED_ORIGINS=https://yourdomain.com,https://www.yourdomain.com

# Для production ВСЕГДА:
DJANGO_DEBUG=False
DJANGO_SECURE_SSL_REDIRECT=True
DJANGO_SESSION_COOKIE_SECURE=True
DJANGO_CSRF_COOKIE_SECURE=True
DJANGO_SECURE_HSTS_SECONDS=31536000
```

### 3. Запустите на хостинге в порядке:
```
1. Миграции БД:     python manage.py migrate
2. Статические:     python manage.py collectstatic --noinput
3. Основное приложение:   gunicorn cohub_settings.wsgi
4. Scheduler (backup):     python manage.py scheduler
```

### 4. Готово! ✅
Приложение работает с HTTPS и автоматическими backup'ами!

---

## 📁 СОЗДАННЫЕ/ОБНОВЛЕННЫЕ ФАЙЛЫ

```
.env                          ← конфигурация для локальной разработки
.env.production               ← ШАБЛОН для production (отредактируйте!)
.env.example                  ← документация всех переменных
backup_daily.bat              ← Windows Task Scheduler скрипт
check_deployment.py           ← скрипт проверки конфигурации
requirements.txt              ← обновлено: +APScheduler, +python-dotenv
cohub_settings/settings.py    ← обновлено: загрузка .env
cohub_app/management/commands/scheduler.py          ← NEW: фоновый scheduler
cohub_app/management/commands/backup_uploader.py    ← NEW: облачные backup'ы
HOSTING_GUIDE.md              ← полное руководство по хостингам
DEPLOYMENT_SUMMARY.md         ← подробный отчет
QUICK_REFERENCE.md            ← этот файл
```

---

## 🔧ТЕ, КТО РАБОТАЕТ ЛОКАЛЬНО

### Запуск сервера:
```bash
python manage.py runserver
# http://localhost:8000
```

### Создание backup вручную:
```bash
python manage.py backup_data --compress
# Файл сохраняется в: backups/cohub-backup-YYYYMMDD-HHMMSS.json.gz
```

### Проверка конфигурации:
```bash
python check_deployment.py  # Полная проверка всех параметров
python manage.py check       # Django system check
```

### Запуск scheduler локально:
```bash
python manage.py scheduler
# Запустит фоновый процесс, создающий backup наежу день
```

---

## 🌐 PRODUCTION ПАРАМЕТРЫ

### HTTPS параметры (ВКЛЮЧЕНЫ)
```bash
DJANGO_SECURE_SSL_REDIRECT=True           # Redirect HTTP → HTTPS
DJANGO_SESSION_COOKIE_SECURE=True         # Cookies только по HTTPS
DJANGO_CSRF_COOKIE_SECURE=True            # CSRF cookies только по HTTPS
DJANGO_SECURE_HSTS_SECONDS=31536000       # Enforce HTTPS 1 год
DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS=True  # Включить subdomains
DJANGO_SECURE_HSTS_PRELOAD=True           # Включить в HSTS preload list
```

### Rate Limiting
```bash
DJANGO_LOGIN_RATE_LIMIT=5         # 5 попыток
DJANGO_LOGIN_RATE_LIMIT_WINDOW=300 # за 5 минут
DJANGO_API_THROTTLE_ANON=30/min   # Анонимные: 30 запросов/мин
DJANGO_API_THROTTLE_USER=120/min  # Авторизованные: 120 запросов/мин
```

### Backup Scheduling
```bash
DJANGO_BACKUP_SCHEDULE_ENABLED=True    # Включить scheduler
DJANGO_BACKUP_SCHEDULE_HOUR=2          # Часав UTC
DJANGO_BACKUP_SCHEDULE_MINUTE=0        # Минуты
DJANGO_BACKUP_COMPRESS=True            # Сжимать (.json.gz)
```

---

## 📞 РЕШЕНИЕ ПРОБЛЕМ

| Проблема | Решение |
|----------|---------|
| "Disallowed Host" | Обновите DJANGO_ALLOWED_HOSTS в .env.production |
| Backup не запускается | Проверьте DJANGO_BACKUP_SCHEDULE_ENABLED=True |
| Статические файлы не показываются | Запустите `python manage.py collectstatic --noinput` |
| SSL ошибки | Убедитесь что хостер проводит SSL (Railway/Render/PythonAnywhere да) |
| 500 ошибка при доступе | Проверьте DEBUG=False, смотрите логи хостинга |

---

## 🆓 РЕКОМЕНДУЕМЫЕ БЕСПЛАТНЫЕ ХОСТИНГИ

### Railway.app ⭐ (РЕКОМЕНДУЕТСЯ)
- 5$ бесплатных кредитов в месяц
- Автоматический SSL
- PostgreSQL база
- GitHub auto-deploy
- **Идеально для начинающих!**

### Render.com
- Бесплатный tier
- Автоматический SSL
- Auto-pause неактивных приложений
- Подходит для малых проектов

### PythonAnywhere
- Бесплатный tier (500MB)
- Легко начать
- Встроенный консолос доступ
- Меньше ресурсов

---

## 📚 ДОПОЛНИТЕЛЬНАЯ ИНФОРМАЦИЯ

**Полные руководства:**
- `HOSTING_GUIDE.md` - детали для каждого хостинга
- `DEPLOYMENT_SUMMARY.md` - полный отчет о изменениях
- `.env.example` - все доступные переменные

**Встроенные скрипты:**
- `check_deployment.py` - проверка конфигурации
- `backup_daily.bat` - Windows Task Scheduler
- `backup_uploader.py` - облачные backup'ы

**Django документация:**
- https://docs.djangoproject.com
- https://docs.djangoproject.com/en/stable/howto/deployment/

---

## ✍️ СЛЕДУЮЩИЕ ШАГИ

1. **Отредактируйте** `.env.production` со своими значениями
2. **Выберите хостинг** (Railway.app проще всего)
3. **Упустите на хостинг** используя переменные env
4. **Настройте scheduler** для backup'ов
5. **Готово!** Приложение работает с HTTPS и backup'ами

---

**Версия:** COHUB v1.0 с Production Security & Backup Automation
**Дата:** Март 28, 2026
**Статус:** ✅ Готово к развертыванию
