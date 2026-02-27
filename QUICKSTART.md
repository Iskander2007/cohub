# 🚀 Быстрый Старт COHUB

## За 5 минут к запущенному приложению!

### Шаг 1: Установка зависимостей (2 минуты)

**Windows:**
```bash
pip install -r requirements.txt
```

**Linux/Mac:**
```bash
pip3 install -r requirements.txt
```

### Шаг 2: Инициализация базы данных (1 минута)

```bash
python manage.py migrate
```

### Шаг 3: (Опционально) Создание тестовых данных (1 минута)

```bash
python manage.py init_sample_data.py
```

Это создаст:
- 3 тестовых пользователя (Alex, Anna, Maxim)
- 1 комнату с кодом `ABC123`
- 3 задачи
- 3 расхода

### Шаг 4: Запуск сервера (1 минута)

**Windows:**
```bash
run_server.bat
```

**Linux/Mac:**
```bash
bash run_server.sh
```

Или напрямую:
```bash
python manage.py runserver
```

### 🎉 Готово!

Приложение COHUB запущено и доступно по адресам:

- **Главная страница:** http://localhost:8000/
- **Регистрация:** http://localhost:8000/register/
- **Панель управления:** http://localhost:8000/dashboard/
- **Admin панель:** http://localhost:8000/admin/

---

## 🧪 Тестовые учетные данные

**Если вы запустили `init_sample_data.py`:**

| Пользователь | Пароль | Роль |
|---|---|---|
| alex | testpass123 | Администратор |
| anna | testpass123 | Участник |
| maxim | testpass123 | Участник |
| admin | — | Администратор |

**Для админа установите пароль:**
```bash
python manage.py changepassword admin
```

**Код комнаты для присоединения:** `ABC123`

---

## 💡 Что попробовать

### 1. Вступить в комнату
- Перейдите на главную страницу (/)
- Введите код `ABC123` в поле "Введите код комнаты"
- Нажмите "ВСТУПИТЬ В КОМАНДУ"

### 2. Просмотреть панель управления
- Перейдите на http://localhost:8000/dashboard/
- Посмотрите статистику по задачам и расходам
- Просмотрите список участников

### 3. Управлять данными через Admin
- Перейдите на http://localhost:8000/admin/
- Вход с логином `admin`
- Создавайте, редактируйте, удаляйте задачи и расходы

### 4. Использовать REST API
```bash
# Получить все комнаты текущего пользователя
curl http://localhost:8000/api/rooms/

# Получить все задачи
curl http://localhost:8000/api/tasks/

# Получить все расходы
curl http://localhost:8000/api/expenses/

# Присоединиться к комнате
curl -X POST http://localhost:8000/api/rooms/join_room/ \
  -H "Content-Type: application/json" \
  -d '{"code":"ABC123"}'
```

---

## 🆘 Решение проблем

### Python не установлен
Скачайте Python с https://www.python.org/

### Django не установлен
```bash
pip install Django==5.2.8
```

### Ошибка при миграциях
```bash
# Удалите db.sqlite3 и попробуйте снова
rm db.sqlite3
python manage.py migrate
python manage.py init_sample_data.py
```

### Порт 8000 занят
```bash
# Используйте другой порт
python manage.py runserver 0.0.0.0:8001
```

---

## 📚 Полная документация

Для подробной информации см:
- [README.md](README.md) - Полная документация проекта
- [IMPROVEMENTS.md](IMPROVEMENTS.md) - Что было исправлено и улучшено
- [API документация](#api-endpoints) - Описание API endpoints

---

## 🎓 Следующие шаги

После запуска приложения:

1. **Интегрируйте Authentication**
   - Добавьте JWT токены
   - Реализуйте login/logout страницы

2. **Завершите Frontend**
   - Заполните JavaScript функции для API вызовов
   - Добавьте валидацию форм
   - Реализуйте модальные окна

3. **Расширьте функционал**
   - Добавьте WebSocket для real-time обновлений
   - Email уведомления о задачах
   - Экспорт данных в PDF/Excel

4. **Deploy в production**
   - Используйте PostgreSQL вместо SQLite
   - Настройте Nginx/Apache
   - Установите SSL сертификат

---

## 🔗 Полезные команды

```bash
# Просмотреть все задачи
python manage.py shell
>>> from cohub_app.models import Task
>>> Task.objects.all()

# Создать новую комнату через Django shell
>>> from cohub_app.models import Room
>>> from django.contrib.auth.models import User
>>> user = User.objects.get(username='admin')
>>> room = Room.objects.create(name="New Room", code="XYZ789", owner=user)

# Экспортировать данные
python manage.py dumpdata > backup.json

# Импортировать данные
python manage.py loaddata backup.json

# Очистить базу данных
python manage.py flush

# Запустить тесты
python manage.py test

# Создать миграцию после изменения моделей
python manage.py makemigrations

# Просмотреть SQL запросы миграции
python manage.py sqlmigrate cohub_app 0001
```

---

## ❓ FAQ

**Q: Можно ли использовать другую БД вместо SQLite?**
A: Да, отредактируйте `cohub_settings/settings.py` и измените `DATABASES`.

**Q: Как добавить нового пользователя?**
A: `python manage.py createsuperuser` или через админ панель.

**Q: API требует аутентификацию?**
A: Сейчас нет, но это рекомендуется добавить.

**Q: Как отправить сообщение об ошибке?**
A: Поднимите issue на GitHub или создайте PR с исправлениями.

---

**Приятного использования COHUB!** 🎉

Для вопросов и предложений посетите документацию или создайте issue.
