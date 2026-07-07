"""
API endpoint для мониторинга и метрик (для Grafana, Prometheus-совместимо).

Предоставляет:
- /api/health/ - Проверка живости (healthcheck)
- /api/metrics/ - Текущие метрики (request rate, error rate, p95 latency, CPU/memory)
- /api/metrics/summary/ - Краткая сводка метрик
"""

import json
import os
import secrets
import psutil
from datetime import datetime, timezone
from django.conf import settings
from django.http import JsonResponse, HttpResponse
from django.views.decorators.http import require_http_methods
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from django.core.cache import cache

from .logging_utils import metrics


METRICS_CACHE_KEY = 'cohub:metrics_payload'


def _get_cached_metrics():
    """Собранные метрики (бизнес + CPU/RAM) с кэшированием на несколько секунд.

    psutil.cpu_percent(interval=0.1) на каждом запросе блокирует ~100 мс, а
    Grafana и дашборд дёргают метрики часто. Кэш (Redis, если задан REDIS_URL,
    иначе локальный) отдаёт готовый payload и убирает эту задержку — это и есть
    кэширование эндпоинтов метрик (/api/metrics/, /api/metrics/prometheus/,
    /api/metrics/summary/). Замер curl до/после — см. CACHING.md.
    """
    ttl = int(getattr(settings, 'METRICS_CACHE_SECONDS', 5) or 5)
    payload = cache.get(METRICS_CACHE_KEY)
    if payload is None:
        payload = metrics.get_metrics()
        _add_system_metrics(payload)
        cache.set(METRICS_CACHE_KEY, payload, timeout=ttl)
    return dict(payload)


def _metrics_token_ok(request) -> bool:
    """Опциональная проверка токена доступа к эндпоинтам метрик.

    settings.METRICS_TOKEN пуст (по умолчанию) → доступ открыт: локальный стек
    Prometheus+Grafana скрейпит метрики без токена. Если токен задан (прод) —
    требуем его в заголовке 'Authorization: Bearer <token>' или query '?token='.
    Сравнение постоянным временем (secrets.compare_digest) против тайминг-атак.
    """
    token = getattr(settings, 'METRICS_TOKEN', '') or ''
    if not token:
        return True
    provided = ''
    auth = request.META.get('HTTP_AUTHORIZATION', '')
    if auth.startswith('Bearer '):
        provided = auth[len('Bearer '):].strip()
    if not provided:
        provided = request.GET.get('token', '')
    return bool(provided) and secrets.compare_digest(provided, token)


def _add_system_metrics(metrics_dict):
    """Безопасно добавить CPU/RAM/диск в словарь метрик.

    Каждый замер psutil обёрнут отдельно: сбой одного (например, disk_usage на
    нестандартной ФС) не должен обнулять уже снятые CPU и память.
    """
    probes = (
        ('cpu_usage', lambda: psutil.cpu_percent(interval=0.1)),
        ('memory_usage', lambda: psutil.virtual_memory().percent),
        # Корень текущего диска: '/' на Unix, 'C:\\' на Windows.
        ('disk_usage', lambda: psutil.disk_usage(os.path.abspath(os.sep)).percent),
    )
    for key, probe in probes:
        try:
            metrics_dict[key] = probe()
        except Exception:
            metrics_dict.setdefault(key, None)
    return metrics_dict


@require_http_methods(["GET"])
def health_check(request):
    """
    Эндпоинт для проверки живости приложения.
    
    Возвращает 200, если приложение работает, 503 если есть проблемы.
    Используется мониторингом (Grafana, Render, load balancer).
    """
    checks = {
        'status': 'healthy',
        'timestamp': datetime.now(tz=timezone.utc).isoformat(),
    }
    
    try:
        # Проверяем подключение к БД
        from django.db import connection
        connection.ensure_connection()
        checks['database'] = 'ok'
    except Exception as e:
        checks['database'] = f'error: {str(e)}'
        checks['status'] = 'unhealthy'
    
    try:
        # Проверяем кеш
        from django.core.cache import cache
        cache.set('health_check', 'ok', 30)
        checks['cache'] = 'ok'
    except Exception as e:
        checks['cache'] = f'error: {str(e)}'
        checks['status'] = 'unhealthy'
    
    status_code = 200 if checks['status'] == 'healthy' else 503
    return JsonResponse(checks, status=status_code)


@api_view(['GET'])
@permission_classes([AllowAny])
def metrics_endpoint(request):
    """
    Эндпоинт метрик для Grafana.

    Возвращает 4 золотых сигнала:
    - request_rate: количество запросов в минуту
    - error_rate: % ошибок (status >= 400)
    - p95_latency: 95-й перцентиль времени ответа в мс
    - cpu_memory: CPU и память в %

    Токен проверяется ДО кэша, а сам payload берётся из кэша (_get_cached_metrics),
    поэтому кэш не «залипает» на 403/200 при защите токеном.
    """
    if not _metrics_token_ok(request):
        return Response({'detail': 'metrics access denied'}, status=403)

    current_metrics = _get_cached_metrics()
    current_metrics['timestamp'] = datetime.now(tz=timezone.utc).isoformat()

    return Response(current_metrics)


@api_view(['GET'])
@permission_classes([AllowAny])
def metrics_prometheus_format(request):
    """
    Метрики в формате Prometheus (для совместимости с Grafana).
    
    Пример вывода:
    # HELP cohub_requests_total Total requests
    # TYPE cohub_requests_total counter
    cohub_requests_total 1523
    """
    if not _metrics_token_ok(request):
        return HttpResponse('metrics access denied\n', status=403,
                            content_type='text/plain; charset=utf-8')

    # Кэшированный payload уже содержит дозаполненные CPU/RAM (_add_system_metrics).
    current_metrics = _get_cached_metrics()

    output = []
    output.append('# HELP cohub_requests_total Total HTTP requests processed')
    output.append('# TYPE cohub_requests_total counter')
    output.append(f'cohub_requests_total {current_metrics["request_rate"]}')
    
    output.append('\n# HELP cohub_errors_total Total errors')
    output.append('# TYPE cohub_errors_total counter')
    output.append(f'cohub_errors_total {current_metrics["total_errors"]}')
    
    output.append('\n# HELP cohub_error_rate_percent Error rate in percent')
    output.append('# TYPE cohub_error_rate_percent gauge')
    output.append(f'cohub_error_rate_percent {current_metrics["error_rate"]:.2f}')
    
    output.append('\n# HELP cohub_p95_latency_ms P95 latency in milliseconds')
    output.append('# TYPE cohub_p95_latency_ms gauge')
    output.append(f'cohub_p95_latency_ms {current_metrics["p95_latency"]:.2f}')
    
    output.append('\n# HELP cohub_avg_latency_ms Average latency in milliseconds')
    output.append('# TYPE cohub_avg_latency_ms gauge')
    output.append(f'cohub_avg_latency_ms {current_metrics["avg_latency"]:.2f}')
    
    output.append('\n# HELP cohub_payments_total Total payment transactions')
    output.append('# TYPE cohub_payments_total counter')
    output.append(f'cohub_payments_total {current_metrics["total_payments"]}')
    
    output.append('\n# HELP cohub_payments_successful Successful payments')
    output.append('# TYPE cohub_payments_successful counter')
    output.append(f'cohub_payments_successful {current_metrics["successful_payments"]}')
    
    output.append('\n# HELP cohub_payments_failed Failed payments')
    output.append('# TYPE cohub_payments_failed counter')
    output.append(f'cohub_payments_failed {current_metrics["failed_payments"]}')
    
    output.append('\n# HELP cohub_payment_success_rate Payment success rate in percent')
    output.append('# TYPE cohub_payment_success_rate gauge')
    output.append(f'cohub_payment_success_rate {current_metrics["payment_success_rate"]:.2f}')
    
    if current_metrics['cpu_usage'] is not None:
        output.append('\n# HELP cohub_cpu_usage CPU usage in percent')
        output.append('# TYPE cohub_cpu_usage gauge')
        output.append(f'cohub_cpu_usage {current_metrics["cpu_usage"]:.2f}')
    
    if current_metrics['memory_usage'] is not None:
        output.append('\n# HELP cohub_memory_usage Memory usage in percent')
        output.append('# TYPE cohub_memory_usage gauge')
        output.append(f'cohub_memory_usage {current_metrics["memory_usage"]:.2f}')
    
    response_text = '\n'.join(output)
    # ВАЖНО: возвращаем именно Django HttpResponse, а не DRF Response. DRF прогнал
    # бы строку через JSONRenderer и отдал бы JSON-строку в кавычках с \n —
    # Prometheus такой ответ не распарсит. Нужен сырой text/plain.
    return HttpResponse(response_text, content_type='text/plain; version=0.0.4; charset=utf-8')


@api_view(['GET'])
@permission_classes([AllowAny])
def metrics_summary(request):
    """Краткая сводка ключевых метрик для дашборда."""
    if not _metrics_token_ok(request):
        return Response({'detail': 'metrics access denied'}, status=403)

    current_metrics = _get_cached_metrics()

    summary = {
        'status': 'ok',
        'timestamp': datetime.now(tz=timezone.utc).isoformat(),
        'golden_signals': {
            'request_rate': current_metrics['request_rate'],
            'error_rate_percent': f"{current_metrics['error_rate']:.2f}%",
            'p95_latency_ms': f"{current_metrics['p95_latency']:.2f}ms",
            'cpu_usage_percent': f"{current_metrics['cpu_usage']:.1f}%" if current_metrics['cpu_usage'] is not None else "N/A",
            'memory_usage_percent': f"{current_metrics['memory_usage']:.1f}%" if current_metrics['memory_usage'] is not None else "N/A",
        },
        'payments': {
            'total_transactions': current_metrics['total_payments'],
            'successful': current_metrics['successful_payments'],
            'failed': current_metrics['failed_payments'],
            'success_rate_percent': f"{current_metrics['payment_success_rate']:.2f}%",
        },
        'alerts': {
            'service_down': current_metrics['error_rate'] > 50,
            'high_error_rate': current_metrics['error_rate'] > 5,
            'high_latency': current_metrics['p95_latency'] > 5000,
            'high_cpu': current_metrics['cpu_usage'] > 80 if current_metrics['cpu_usage'] is not None else False,
            'high_memory': current_metrics['memory_usage'] > 85 if current_metrics['memory_usage'] is not None else False,
        }
    }
    
    return Response(summary)
