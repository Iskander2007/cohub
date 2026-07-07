# CoHub — образ Django-приложения (веб + Celery-воркер запускаются из этого же образа).
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_SETTINGS_MODULE=cohub_settings.settings

WORKDIR /app

# curl нужен для healthcheck веб-сервиса (GET /health/).
# Компилятор не требуется: psycopg2-binary и psutil ставятся из wheel'ов.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN python -m pip install --upgrade pip && pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

# Значение по умолчанию — веб-сервер. Миграции и collectstatic делает
# docker-compose (команда web-сервиса) либо стартовый скрипт платформы.
CMD ["gunicorn", "cohub_settings.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3"]
