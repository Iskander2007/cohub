#!/bin/bash
# Скрипт для запуска COHUB приложения на Linux/Mac

echo "Запуск COHUB - Система управления совместной жизнью..."
echo ""

# Проверяем наличие Python
if ! command -v python3 &> /dev/null; then
    echo "ОШИБКА: Python3 не установлен"
    echo "Пожалуйста установите Python 3.10 или выше"
    exit 1
fi

echo "✓ Python найден"

# Проверяем наличие requirements.txt
if [ ! -f "requirements.txt" ]; then
    echo "ОШИБКА: requirements.txt не найден"
    exit 1
fi

# Устанавливаем зависимости если нужно
echo ""
echo "Проверка зависимостей..."

if ! python3 -c "import django" 2>/dev/null; then
    echo "Установка зависимостей..."
    pip install -r requirements.txt
    
    if [ $? -ne 0 ]; then
        echo "ОШИБКА: Не удалось установить зависимости"
        exit 1
    fi
fi

echo "✓ Зависимости установлены"

# Применяем миграции
echo ""
echo "Применение миграций базы данных..."
python3 manage.py migrate

if [ $? -ne 0 ]; then
    echo "ОШИБКА: Не удалось применить миграции"
    exit 1
fi

echo "✓ Миграции применены"

# Запускаем сервер
echo ""
echo "========================================"
echo "Запуск сервера разработки..."
echo "========================================"
echo ""
echo "Приложение доступно по адресу:"
echo "  http://localhost:8000/"
echo ""
echo "Admin панель:"
echo "  http://localhost:8000/admin/"
echo "  Логин: admin"
echo "  Пароль: установите с помощью: python3 manage.py changepassword admin"
echo ""
echo "Для остановки сервера нажмите Ctrl+C"
echo "========================================"
echo ""

python3 manage.py runserver 0.0.0.0:8000
