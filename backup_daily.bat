@echo off
REM Windows Task Scheduler Script for Daily Backup
REM Используйте этот скрипт для планирования daily backups через Windows Task Scheduler
REM 
REM Инструкции по добавлению в Task Scheduler:
REM 1. Откройте Task Scheduler (taskschd.msc)
REM 2. Создайте новую задачу (Create Basic Task...)
REM 3. Назовите её "COHUB Daily Backup"
REM 4. В Trigger выберите ежедневно в нужное время (например, 2:00 AM)
REM 5. В Action выберите "Start a program" и укажите:
REM    Program/script: cmd.exe
REM    Add arguments: /c call "%~dp0backup_daily.bat"
REM    Start in: C:\Users\Iskander\Downloads\cohub\cohub
REM 6. На вкладке Settings отметьте "Run task as soon as possible after a scheduled start is missed"

cd /d "%~dp0"

REM Активировать виртуальное окружение, если оно используется
if exist .venv\Scripts\activate.bat (
    call .venv\Scripts\activate.bat
)

REM Запустить backup_data команду
python manage.py backup_data --compress

REM Опционально: отправить логи (раскомментируйте если нужно)
REM echo Backup completed at %date% %time% >> logs\backup.log
