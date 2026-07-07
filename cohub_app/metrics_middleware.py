"""
Middleware для мониторинга и метрик запросов.

Отслеживает:
- Время ответа (latency)
- Статус код
- Пользователя (user_id)
- Request ID для трейсинга

Дополнительно пишет структурированный JSON-лог по каждому обращению к
ключевым endpoint'ам (API, платежи, аутентификация, health) в logs/requests.json
— это «структурированное логирование ключевых endpoints» для разбора в Grafana/Loki.
"""

import logging
import re
import time
import uuid
from django.utils.deprecation import MiddlewareMixin
from .logging_utils import metrics, request_context

# Отдельный логгер запросов: пишет в logs/requests.json (см. LOGGING в settings).
request_logger = logging.getLogger('cohub.requests')

# Префиксы «ключевых» endpoint'ов, которые логируем структурированно.
# Всё остальное (статика, фавиконки, корень) пропускаем, чтобы не зашумлять лог.
KEY_ENDPOINT_PREFIXES = (
    '/api/',
    '/payments/',
    '/account/',
    '/register/',
    '/dashboard/',
    '/room/',
    '/subscription/',
    '/health/',
)

# request_id принимаем от клиента (заголовок X-Request-ID), но не доверяем ему
# вслепую: допускаем только безопасные символы и ограничиваем длину, иначе
# генерируем свой. Значение попадает в лог и в заголовок ответа.
_REQUEST_ID_RE = re.compile(r'^[A-Za-z0-9._\-]{1,128}$')

# Эти пути исключаем даже внутри ключевых префиксов: метрики скрейпит Prometheus
# каждые 15с — их попадание в лог приложения создавало бы постоянный шум.
EXCLUDED_PREFIXES = (
    '/api/metrics',
)


def _is_key_endpoint(path: str) -> bool:
    """Нужно ли структурированно логировать обращение к этому пути."""
    if any(path.startswith(p) for p in EXCLUDED_PREFIXES):
        return False
    return any(path.startswith(p) for p in KEY_ENDPOINT_PREFIXES)


def _client_ip(request) -> str:
    """IP клиента с учётом обратного прокси (X-Forwarded-For)."""
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', '')


class MetricsMiddleware(MiddlewareMixin):
    """Middleware для сбора метрик запросов (latency, status code, errors)."""

    def process_request(self, request):
        """Инициализировать контекст запроса и таймер."""
        request._start_time = time.time()

        # Генерируем или получаем request_id (клиентский — только если валиден).
        client_id = request.headers.get('X-Request-ID', '')
        request_id = client_id if _REQUEST_ID_RE.match(client_id) else str(uuid.uuid4())
        request.request_id = request_id

        # Устанавливаем контекст для логирования
        ctx = {
            'request_id': request_id,
            'user_id': getattr(request.user, 'id', None) if request.user.is_authenticated else None,
            'operation': f'{request.method} {request.path}',
        }
        request_context.set(ctx)

    def process_response(self, request, response):
        """Записать метрики ответа и структурированный лог ключевого endpoint'а.

        Вся телеметрия обёрнута в try/except: сбой логирования или метрик НЕ должен
        ломать уже сформированный ответ пользователю (иначе 200 превратился бы в 500).
        """
        try:
            if hasattr(request, '_start_time'):
                elapsed_ms = (time.time() - request._start_time) * 1000  # в миллисекундах
                status_code = response.status_code

                # Записываем метрику (учитывается в /api/metrics/ для Grafana)
                metrics.record_request(elapsed_ms, status_code)

                # Добавляем заголовок с request_id для трейсинга
                response['X-Request-ID'] = getattr(request, 'request_id', '')

                # Структурированный JSON-лог по ключевым endpoint'ам.
                if _is_key_endpoint(request.path):
                    self._log_request(request, status_code, elapsed_ms)
        except Exception:  # noqa: BLE001 — телеметрия не должна влиять на ответ
            request_logger.exception('metrics middleware failed (response preserved)')
        finally:
            # Сбрасываем контекст, чтобы он не «протёк» на повторно используемый поток.
            request_context.set({})

        return response

    def _log_request(self, request, status_code: int, elapsed_ms: float):
        """Пишет одну структурированную JSON-запись об обращении.

        Уровень выбирается по статусу: 5xx → ERROR, 4xx → WARNING, иначе INFO,
        чтобы серверные ошибки автоматически попадали и в errors.json.
        """
        if status_code >= 500:
            level = logging.ERROR
        elif status_code >= 400:
            level = logging.WARNING
        else:
            level = logging.INFO

        ctx = request_context.get()
        extra_data = {
            'event_type': 'http_request',
            'method': request.method,
            'path': request.path,
            'status_code': status_code,
            'latency_ms': round(elapsed_ms, 2),
            'user_id': ctx.get('user_id'),
            'request_id': getattr(request, 'request_id', None),
            'client_ip': _client_ip(request),
            'user_agent': request.META.get('HTTP_USER_AGENT', '')[:200],
        }

        record = request_logger.makeRecord(
            request_logger.name, level, 'metrics_middleware', 0,
            f'{request.method} {request.path} -> {status_code} ({extra_data["latency_ms"]}ms)',
            (), None, func='_log_request',
        )
        record.extra_data = extra_data
        request_logger.handle(record)
