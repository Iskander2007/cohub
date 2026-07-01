#!/usr/bin/env bash
# Запускает нагрузочный тест COHUB (Locust, 100 пользователей) и формирует HTML-отчёт.
#
# Приложение должно быть уже запущено, например:
#   cd cohub && python manage.py runserver 0.0.0.0:8000   (или gunicorn)
#
# Использование:
#   ./loadtest/run_loadtest.sh                       # 100 users, 2m, localhost
#   USERS=100 RUN_TIME=2m HOST=http://127.0.0.1:8000 ./loadtest/run_loadtest.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

USERS="${USERS:-100}"
SPAWN_RATE="${SPAWN_RATE:-10}"
RUN_TIME="${RUN_TIME:-2m}"
HOST="${HOST:-http://127.0.0.1:8000}"
REPORT="${REPORT:-loadtest_report.html}"

PYTHON="${PYTHON:-python}"
if [ -x "$ROOT/.venv/bin/python" ]; then PYTHON="$ROOT/.venv/bin/python"; fi
if [ -x "$ROOT/.venv/Scripts/python.exe" ]; then PYTHON="$ROOT/.venv/Scripts/python.exe"; fi

echo "==> Locust: $USERS пользователей, разгон $SPAWN_RATE/с, время $RUN_TIME, host $HOST"

"$PYTHON" -m locust \
  -f "$ROOT/locust_loadtest.py" \
  --headless \
  --users "$USERS" \
  --spawn-rate "$SPAWN_RATE" \
  --run-time "$RUN_TIME" \
  --host "$HOST" \
  --html "$ROOT/$REPORT" \
  --csv "$ROOT/loadtest_stats"

echo "==> Готово. HTML-отчёт: $REPORT"
