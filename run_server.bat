@echo off
REM Скрипт для запуска COHUB приложения на Windows

echo Запуск COHUB - Система управления совместной жизнью...
echo.

REM Проверяем наличие Python
python --version >nul 2>&1
if errorlevel 1 (
    echo ОШИБКА: Python не установлен или не в PATH
    echo Пожалуйста установите Python 3.10 или выше
    pause
    exit /b 1
)

echo ✓ Python найден

REM Проверяем наличие requirements.txt
if not exist "requirements.txt" (
    echo ОШИБКА: requirements.txt не найден
    pause
    exit /b 1
)

REM Устанавливаем зависимости если нужно
echo.
echo Проверка зависимостей...
pip list | findstr "Django" >nul 2>&1
if errorlevel 1 (
    echo Установка зависимостей...
    pip install -r requirements.txt
    if errorlevel 1 (
        echo ОШИБКА: Не удалось установить зависимости
        pause
        exit /b 1
    )
)

echo ✓ Зависимости установлены

REM Применяем миграции
echo.
echo Применение миграций базы данных...
python manage.py migrate

if errorlevel 1 (
    echo ОШИБКА: Не удалось применить миграции
    pause
    exit /b 1
)

echo ✓ Миграции применены

REM Запускаем сервер
echo.
echo ========================================
echo Запуск сервера разработки...
echo ========================================
echo.
echo Приложение доступно по адресу:
echo   http://localhost:8000/
echo.
echo Admin панель:
echo   http://localhost:8000/admin/
echo   Логин: admin
echo   Пароль: установите с помощью: python manage.py changepassword admin
echo.
echo Для остановки сервера нажмите Ctrl+C
echo ========================================
echo.

python manage.py runserver 0.0.0.0:8000

pause
