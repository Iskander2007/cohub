# Runbook для сайта COHUB

## 1. Назначение

Этот runbook предназначен для запуска, поддержки, обновления и восстановления сайта COHUB в случае инцидентов.

Проект: Django-приложение для управления совместной жизнью, комнатами, задачами, расходами и долгами.

## 2. Краткая информация о системе

- Backend: Django 5.2.8
- API: Django REST Framework
- База данных: SQLite локально / PostgreSQL в production
- Frontend: HTML, CSS, JavaScript
- Рекомендуемый запуск: через Django development server или через hosting-процесс
- Основные URL:
  - Главная: /
  - Регистрация: /register/
  - Dashboard: /dashboard/
  - Admin: /admin/
  - API: /api/

## 3. Предварительные требования

### Локальная разработка
- Python 3.10+
- pip
- Git
- (рекомендуется) venv

### Production
- доступ к серверу/хостингу
- переменные окружения
- доступ к базе данных
- доступ к логам и backup-хранилищу

## 4. Подготовка окружения

### 4.1 Установка зависимостей

Windows:
```powershell
pip install -r requirements.txt
```

Linux/macOS:
```bash
pip install -r requirements.txt
```

### 4.2 Настройка переменных окружения

Ожидаются переменные:
```env
DJANGO_SECRET_KEY=your-secret-key
DJANGO_DEBUG=False
DJANGO_ALLOWED_HOSTS=your-domain.com
DJANGO_CSRF_TRUSTED_ORIGINS=https://your-domain.com
```

Если используется файл .env, он должен находиться в корне проекта.

### 4.3 Применение миграций

```bash
python manage.py migrate
```

### 4.4 Создание администратора (при необходимости)

```bash
python manage.py createsuperuser
```

## 5. Запуск сайта

### 5.1 Локальный запуск

Windows:
```powershell
run_server.bat
```

Linux/macOS:
```bash
bash run_server.sh
```

Или напрямую:
```bash
python manage.py runserver
```

Ожидаемый адрес:
- http://localhost:8000/

### 5.2 Запуск на сервере/хостинге

Обычно используются:
```bash
python manage.py migrate
python manage.py collectstatic --noinput
```

Для запуска веб-сервиса:
```bash
gunicorn cohub_settings.wsgi
```

Если включен scheduler backup'ов:
```bash
python manage.py scheduler
```

## 6. Проверка работоспособности

После запуска выполнить следующие проверки:

1. Открыть главную страницу.
2. Проверить регистрацию и вход.
3. Проверить доступ к dashboard.
4. Проверить доступ к admin.
5. Проверить API endpoints:
   - /api/rooms/
   - /api/tasks/
   - /api/expenses/
6. Проверить, что статические файлы загружаются корректно.

### Быстрая проверка через curl

```bash
curl -I http://localhost:8000/
curl -I http://localhost:8000/admin/
```

## 7. Резервное копирование и восстановление

### 7.1 Создание backup

```bash
python manage.py backup_data --compress
```

Результат: файл в папке backups/.

### 7.2 Восстановление из backup

```bash
python manage.py loaddata backups/your-backup-file.json
```

### 7.3 Автоматический backup

Если включен scheduler:
```bash
python manage.py scheduler
```

Рекомендуемый график: ежедневно в 02:00 UTC.

## 8. Обновление приложения

### Процесс обновления

1. Слить изменения в репозиторий.
2. Установить новые зависимости.
3. Выполнить миграции.
4. Выполнить collectstatic.
5. Перезапустить веб-процесс.
6. Проверить основные страницы и API.

```bash
pip install -r requirements.txt
python manage.py migrate
python manage.py collectstatic --noinput
```

## 9. Откат изменений

Если после обновления возникли проблемы:

1. Остановить новый процесс.
2. Вернуть предыдущую версию кода.
3. Выполнить миграции в соответствии с предыдущей версией.
4. Запустить приложение снова.
5. Проверить работоспособность.

> Если база данных уже была изменена миграциями, откат может потребовать ручной работы с миграциями и backup.

## 10. Диагностика и решение типовых проблем

### 10.1 Приложение не запускается

Симптомы:
- ошибка импорта модуля
- ошибка Django settings
- порт занят

Что проверить:
- Python и зависимости установлены
- правильные переменные окружения
- нет ли процесса, который уже использует порт 8000

Команды:
```bash
python manage.py check
```

### 10.2 Ошибка при миграциях

```bash
python manage.py migrate --plan
python manage.py makemigrations
```

Если база повреждена, восстановить из backup.

### 10.3 Ошибка 500 / белая страница

Что проверить:
- логи приложения
- DEBUG-параметры
- наличие ошибок в консоли и в логах сервера
- корректность .env и ALLOWED_HOSTS

### 10.4 Статические файлы не загружаются

```bash
python manage.py collectstatic --noinput
```

### 10.5 Проблемы с доступом / auth

Проверить:
- правильность CSRF_TRUSTED_ORIGINS
- правильность ALLOWED_HOSTS
- корректность cookie settings в production

## 11. Мониторинг и логирование

Рекомендуется проверять:
- логи веб-сервера
- логи Django
- наличие backup-файлов
- состояние базы данных
- доступность основных URL

## 12. Сценарий инцидента

### Сценарий A: сайт недоступен

1. Проверить, запущен ли процесс.
2. Проверить логи.
3. Проверить, не занят ли порт.
4. Проверить базу данных.
5. При необходимости перезапустить приложение.
6. Если проблема не решена — восстановить из последнего backup.

### Сценарий B: ошибка базы данных

1. Проверить подключение к БД.
2. Проверить миграции.
3. Проверить доступность файла/сервиса базы данных.
4. При необходимости восстановить backup.

### Сценарий C: проблема после обновления

1. Откатить код к предыдущей рабочей версии.
2. Проверить миграции и конфигурацию.
3. Перезапустить процесс.
4. Проверить основные сценарии пользователя.

## 13. Контрольный список перед релизом

- [ ] зависимости установлены
- [ ] миграции применены
- [ ] collectstatic выполнен
- [ ] основные URL доступны
- [ ] admin работает
- [ ] backup создан
- [ ] логирование доступно

## 14. Рекомендуемая структура для Confluence

- Overview
- Prerequisites
- Startup steps
- Health check
- Backup and restore
- Troubleshooting
- Incident response
- Release checklist
