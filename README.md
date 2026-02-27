# 🏠 COHUB - Система управления совместной жизнью

## 📋 Что было исправлено и улучшено

### ✅ Основные исправления

1. **Инициализация Django проекта** - проект был пересоздан как полноценное Django приложение
2. **Создание базы данных** - инициализирована SQLite БД с необходимыми таблицами
3. **Структура проекта** - организована правильная структура Django + REST API

### 🆕 Новые функции

#### 1. **REST API (полный функционал)**
- Управление комнатами/командами
- CRUD операции для задач
- Отслеживание расходов и долей
- Статистика и аналитика по комнате

#### 2. **Модели приложения**
- `Room` - комната/команда для проживания
- `RoomMember` - участники комнаты с ролями
- `Task` - задачи с назначениями и статусами
- `Expense` - общие расходы
- `ExpenseShare` - распределение расходов между участниками

#### 3. **Улучшенный интерфейс**
- Современный дизайн с glass-morphism эффектом
- Адаптивный layout для мобильных устройств
- Красивые переходы и анимации
- Темы с градиентными фонами

#### 4. **JavaScript функциональность**
- Полная интеграция с REST API
- Функции для работы с комнатами, задачами и расходами
- Система уведомлений
- Форматирование дат и времени

#### 5. **Администрирование**
- Полная админ-панель Django
- Управление всеми моделями через админ
- Фильтрация и поиск
- Логирование действий

---

## 🚀 Как запустить приложение

### Требования
- Python 3.10+
- Django 5.2.8
- Django REST Framework

### Установка

1. **Установите зависимости:**
```bash
pip install -r requirements.txt
```

2. **Примените миграции:**
```bash
python manage.py migrate
```

3. **Создайте суперпользователя (если требуется новый):**
```bash
python manage.py createsuperuser
```

4. **Запустите сервер:**
```bash
python manage.py runserver
```

Сервер запустится на `http://localhost:8000`

### Доступные URL

- **Главная страница:** `http://localhost:8000/`
- **Страница регистрации:** `http://localhost:8000/register/`
- **Панель управления:** `http://localhost:8000/dashboard/`
- **Admin панель:** `http://localhost:8000/admin/` (логин: admin)
- **API:** `http://localhost:8000/api/`

---

## 📚 API Endpoints

### Комнаты (Rooms)
- `GET /api/rooms/` - Список ваших комнат
- `POST /api/rooms/` - Создать новую комнату
- `GET /api/rooms/{id}/` - Получить комнату
- `POST /api/rooms/join_room/` - Присоединиться к комнате (по коду)
- `GET /api/rooms/{id}/statistics/` - Статистика комнаты

### Задачи (Tasks)
- `GET /api/tasks/` - Список задач
- `POST /api/tasks/` - Создать задачу
- `GET /api/tasks/{id}/` - Получить задачу
- `PATCH /api/tasks/{id}/` - Обновить задачу
- `POST /api/tasks/{id}/complete/` - Отметить как завершено

### Расходы (Expenses)
- `GET /api/expenses/` - Список расходов
- `POST /api/expenses/` - Создать расход
- `GET /api/expenses/{id}/` - Получить расход
- `PATCH /api/expenses/{id}/` - Обновить расход

### Доли расходов (Expense Shares)
- `GET /api/expense-shares/` - Список долей
- `POST /api/expense-shares/{id}/settle/` - Отметить как расчет произведен

---

## 🎨 Структура проекта

```
cohub/
├── manage.py                    # Django управление
├── requirements.txt             # Зависимости
├── db.sqlite3                   # База данных
├── cohub_settings/
│   ├── __init__.py
│   ├── settings.py             # Настройки Django
│   ├── urls.py                 # Главные URL маршруты
│   └── wsgi.py                 # WSGI приложение
├── cohub_app/
│   ├── models.py               # Модели БД
│   ├── views.py                # API views
│   ├── serializers.py          # DRF serializers
│   ├── urls.py                 # API маршруты
│   ├── admin.py                # Admin регистрация
│   ├── apps.py                 # Конфигурация приложения
│   └── migrations/             # Миграции БД
├── templates/
│   ├── base.html               # Основной шаблон
│   ├── index.html              # Главная страница
│   ├── register.html           # Регистрация
│   └── dashboard.html          # Панель управления
└── static/
    ├── css/
    │   └── style.css           # Основные стили
    └── js/
        └── main.js             # JavaScript функции
```

---

## 🔐 Свойства безопасности

- CSRF защита для всех форм
- Аутентификация через Django
- Permissions проверки в API
- SQL-injection защита через ORM
- XSS защита

---

## 📱 Функции для использования

### Главная страница
- Входная страница с описанием функций
- Форма присоединения к комнате по коду
- Информация о преимуществах COHUB

### Страница регистрации
- Регистрация новых пользователей
- Валидация пароля
- Условия использования

### Панель управления
- Просмотр участников комнаты
- Статистика по задачам
- Отслеживание расходов
- Управление задачами
- Калькулятор долгов

---

## 🛠️ Технологический стек

- **Backend:** Django 5.2.8
- **API:** Django REST Framework
- **Database:** SQLite3 (можно заменить на PostgreSQL)
- **Frontend:** HTML5, CSS3, JavaScript (Vanilla)
- **Styling:** Modern CSS с Glass Morphism эффектом

---

## 📝 Примечания

- Приложение полностью готово к использованию
- Необходимо везде интегрировать API вызовы в JavaScript части
- Можно добавить аутентификацию (Token/JWT)
- Рекомендуется использовать PostgreSQL для production

---

## 🚢 Деплой на Railway

1. Зарегистрируйтесь на [railway.app](https://railway.app) и установите CLI:
   ```bash
   npm install -g @railway/cli
   railway login
   ```

2. Создайте пустой репозиторий на GitHub и привяжите его к проекту:
   ```bash
   git init
   git add .
   git commit -m "initial"
   git branch -M main
   git remote add origin https://github.com/<ваш‑ник>/cohub.git
   git push -u origin main
   ```

3. Инициализируйте Railway проект и создайте сервис базы данных:
   ```bash
   railway init            # выберите ваш репо, если потребуется
   ```
   Затем **создайте Postgres‑сервис**. CLI команды могут меняться и иногда
   выдавать ошибки вроде "unexpected argument"; если так, просто
   воспользуйтесь веб‑интерфейсом:
   1. Откройте https://railway.app и выберите свой проект.
   2. Нажмите **New Service → PostgreSQL** (или "Database").
   3. Подождите, пока сервис станет online.

   После этого в настройках проекта автоматически появится переменная
   `DATABASE_URL`.
   
   Для проверки статуса из CLI можно запустить:
   ```bash
   railway status   # или просто откройте Dashboard
   ```
   но если команды `railway service list`/`railway service add` возвращают
   ошибки, используйте веб‑интерфейс, это надёжнее.

4. Установите переменные окружения (секреты). На PowerShell
   каждая пара надо задавать отдельно:
   ```powershell
   railway variables set DJANGO_SECRET_KEY=секрет
   railway variables set DJANGO_DEBUG=False
   railway variables set DJANGO_ALLOWED_HOSTS=*
   ```
   либо используйте одинарные кавычки обёртку и escape для спецсимволов.
   Команда возвращает ошибку "No service linked" до тех пор, пока в
   проекте не создан хотя бы один сервис (Postgres, Redis и т.п.).

5. После пуша в `main` Railway автоматически собирает приложение:
   - устанавливаются зависимости из `requirements.txt`
   - выполняется `python manage.py collectstatic` по Procfile
   - запускается gunicorn как в `Procfile`.

6. Запустите миграции и создайте суперпользователя через CLI:
   ```bash
   railway run python manage.py migrate
   railway run python manage.py createsuperuser
   ```
   > Если вы получите сообщение `Project has no services`, это значит,
   > что сервисы (например, база данных) ещё не созданы или не привязаны.  
   > Создайте хотя бы один сервис (Postgres) через `railway service add`
   > или через Dashboard, затем повторите команды.

7. Откройте URL приложения:
   ```bash
   railway open
   ```

Сайт будет доступен по адресу вида `https://<your-project>.railway.app`.

## 🎯 Будущие улучшения

- [ ] WebSocket для real-time обновлений
- [ ] Email уведомления
- [ ] Экспорт данных (PDF, Excel)
- [ ] История изменений
- [ ] Интеграция с календарем
- [ ] Напоминания о задачах
- [ ] Мобильное приложение

---

**Версия:** 1.0  
**Дата создания:** 27 февраля 2026  
**Автор:** COHUB Team
#   c o h u b - s i t e 
 
 