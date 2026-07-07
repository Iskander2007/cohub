#!/usr/bin/env bash
#
# Резервное копирование данных CoHub (задача чек-листа: backup.sh).
#
# Делает сжатый JSON-дамп (пользователи + данные cohub_app) через Django-команду
# backup_data. Восстановление:  python manage.py restore_data <файл>
#
# Использование:
#   ./backup.sh                      # бэкап в ./backups (или $DJANGO_BACKUP_DIR)
#   BACKUP_DIR=/data/backups ./backup.sh
#
# Настройка cron (ежедневно в 02:00) — см. также сервис cohub-backup-daily в render.yaml:
#   0 2 * * * cd /path/to/cohub && ./backup.sh >> /var/log/cohub-backup.log 2>&1
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

PYTHON_BIN="${PYTHON_BIN:-python}"
BACKUP_DIR="${BACKUP_DIR:-${DJANGO_BACKUP_DIR:-$SCRIPT_DIR/backups}}"

echo "[backup.sh] $(date '+%Y-%m-%d %H:%M:%S') → каталог бэкапов: $BACKUP_DIR"
"$PYTHON_BIN" manage.py backup_data --output-dir "$BACKUP_DIR" --compress
echo "[backup.sh] Резервная копия создана. Для восстановления: $PYTHON_BIN manage.py restore_data"
