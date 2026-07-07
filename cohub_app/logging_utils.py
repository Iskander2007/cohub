"""
Утилиты для структурированного JSON логирования платежей и операций COHUB.

Предоставляет:
- JSON-логгер для платежных операций (user_id, event, timestamp, status, details)
- Контекстный логер для отслеживания запросов (request_id, user_id, operation)
- Метрики для Grafana (request rate, error rate, latency)
"""

import json
import logging
import threading
import traceback
import uuid
from collections import deque
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from contextvars import ContextVar

import logging.handlers

# Сколько последних замеров времени ответа храним для расчёта p95/avg.
# Ограничение обязательно: без него список рос бы бесконечно (утечка памяти)
# и сортировка на каждый scrape метрик становилась бы всё дороже.
RESPONSE_TIMES_MAXLEN = 2000

# Контекстные переменные для отслеживания запросов
request_context = ContextVar('request_context', default={})


class JSONFormatter(logging.Formatter):
    """Форматер логов в JSON с метаданными для парсинга."""

    def format(self, record: logging.LogRecord) -> str:
        """Преобразует запись в JSON структуру."""
        log_obj = {
            'timestamp': datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
            'module': record.module,
            'function': record.funcName,
            'line': record.lineno,
        }

        # Добавляем контекст запроса, если есть
        ctx = request_context.get()
        if ctx:
            log_obj['request_id'] = ctx.get('request_id')
            log_obj['user_id'] = ctx.get('user_id')
            log_obj['operation'] = ctx.get('operation')

        # Если в логе передана дополнительная информация (extra)
        if hasattr(record, 'extra_data'):
            log_obj.update(record.extra_data)

        # Добавляем исключение, если есть
        if record.exc_info:
            log_obj['exception'] = self.formatException(record.exc_info)

        return json.dumps(log_obj, ensure_ascii=False, default=str)


class PaymentLogger:
    """Логгер для операций с платежами. Выводит структурированные JSON логи."""

    def __init__(self, logger_name: str = 'cohub.payments'):
        self.logger = logging.getLogger(logger_name)

    def _log_payment_event(
        self,
        level: int,
        event_type: str,
        user_id: Optional[int],
        order_id: Optional[str],
        status: str,
        message: str,
        **extra
    ):
        """Внутренний метод логирования платежного события."""
        ctx = request_context.get()
        
        payment_event = {
            'event_type': event_type,
            'user_id': user_id or ctx.get('user_id'),
            'order_id': order_id,
            'status': status,
            'timestamp': datetime.now(tz=timezone.utc).isoformat(),
            **extra
        }

        record = self.logger.makeRecord(
            self.logger.name,
            level,
            'payments',
            0,
            message,
            (),
            None,
            func='payment_event'
        )
        record.extra_data = payment_event
        self.logger.handle(record)

    def payment_initiated(
        self,
        user_id: int,
        order_id: str,
        provider: str,
        amount: float,
        currency: str,
        **extra
    ):
        """Лог: платеж инициирован."""
        self._log_payment_event(
            logging.INFO,
            'payment_initiated',
            user_id,
            order_id,
            'initiated',
            f'Payment initiated: user_id={user_id}, order_id={order_id}, provider={provider}',
            provider=provider,
            amount=amount,
            currency=currency,
            **extra
        )

    def payment_pending(
        self,
        user_id: int,
        order_id: str,
        provider: str,
        **extra
    ):
        """Лог: платеж в статусе pending (ожидает подтверждения)."""
        self._log_payment_event(
            logging.INFO,
            'payment_pending',
            user_id,
            order_id,
            'pending',
            f'Payment pending: user_id={user_id}, order_id={order_id}',
            provider=provider,
            **extra
        )

    def payment_confirmed(
        self,
        user_id: int,
        order_id: str,
        provider: str,
        provider_order_id: str,
        amount: float,
        currency: str,
        **extra
    ):
        """Лог: платеж подтвержден (успешно обработан)."""
        self._log_payment_event(
            logging.INFO,
            'payment_confirmed',
            user_id,
            order_id,
            'confirmed',
            f'Payment confirmed: user_id={user_id}, order_id={order_id}, provider_order_id={provider_order_id}',
            provider=provider,
            provider_order_id=provider_order_id,
            amount=amount,
            currency=currency,
            **extra
        )

    def payment_failed(
        self,
        user_id: int,
        order_id: str,
        provider: str,
        reason: str,
        **extra
    ):
        """Лог: платеж отклонен."""
        self._log_payment_event(
            logging.WARNING,
            'payment_failed',
            user_id,
            order_id,
            'failed',
            f'Payment failed: user_id={user_id}, order_id={order_id}, reason={reason}',
            provider=provider,
            reason=reason,
            **extra
        )

    def payment_error(
        self,
        user_id: Optional[int],
        order_id: Optional[str],
        error_type: str,
        error_message: str,
        **extra
    ):
        """Лог: ошибка при обработке платежа."""
        self._log_payment_event(
            logging.ERROR,
            'payment_error',
            user_id,
            order_id,
            'error',
            f'Payment error: {error_type} - {error_message}',
            error_type=error_type,
            error_message=error_message,
            **extra
        )

    def subscription_activated(
        self,
        user_id: int,
        order_id: str,
        months: int,
        expires_at: str,
        **extra
    ):
        """Лог: подписка активирована."""
        self._log_payment_event(
            logging.INFO,
            'subscription_activated',
            user_id,
            order_id,
            'activated',
            f'Subscription activated: user_id={user_id}, months={months}',
            months=months,
            expires_at=expires_at,
            **extra
        )


class MetricsCollector:
    """Сборщик метрик для Grafana: request rate, error rate, latency."""

    _instance = None
    # Один общий замок на процесс: счётчики обновляются из каждого запроса
    # (MetricsMiddleware), поэтому read-modify-write нужно синхронизировать,
    # иначе под многопоточным сервером часть инкрементов теряется.
    _lock = threading.Lock()
    _metrics = {
        'total_requests': 0,
        'total_errors': 0,
        'total_payments': 0,
        'successful_payments': 0,
        'failed_payments': 0,
        'response_times': deque(maxlen=RESPONSE_TIMES_MAXLEN),  # для расчета p95
    }

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def record_request(self, elapsed_ms: float, status_code: int = 200):
        """Записать метрику запроса."""
        with self._lock:
            self._metrics['total_requests'] += 1
            self._metrics['response_times'].append(elapsed_ms)
            if status_code >= 400:
                self._metrics['total_errors'] += 1

    def record_payment(self, success: bool):
        """Записать метрику платежа."""
        with self._lock:
            self._metrics['total_payments'] += 1
            if success:
                self._metrics['successful_payments'] += 1
            else:
                self._metrics['failed_payments'] += 1

    def get_metrics(self) -> Dict[str, Any]:
        """Получить текущие метрики для Grafana."""
        # Снимок под замком, чтобы не сортировать список во время его изменения.
        with self._lock:
            response_times = list(self._metrics['response_times'])
            total_requests_raw = self._metrics['total_requests']
            total_errors = self._metrics['total_errors']
            total_payments = self._metrics['total_payments']
            successful_payments = self._metrics['successful_payments']
            failed_payments = self._metrics['failed_payments']

        # Расчет p95 (95-й перцентиль)
        if response_times:
            sorted_times = sorted(response_times)
            p95_index = min(int(len(sorted_times) * 0.95), len(sorted_times) - 1)
            p95_latency = sorted_times[p95_index]
            avg_latency = sum(response_times) / len(response_times)
        else:
            p95_latency = 0
            avg_latency = 0

        total_requests = total_requests_raw or 1
        error_rate = (total_errors / total_requests) * 100 if total_requests > 0 else 0

        return {
            'request_rate': total_requests_raw,
            'error_rate': error_rate,
            'p95_latency': p95_latency,
            'avg_latency': avg_latency,
            'total_errors': total_errors,
            'cpu_usage': None,  # Заполнится системными метриками (см. monitoring.py)
            'memory_usage': None,
            'total_payments': total_payments,
            'successful_payments': successful_payments,
            'failed_payments': failed_payments,
            'payment_success_rate': (
                successful_payments / total_payments * 100 if total_payments > 0 else 0
            ),
        }

    def reset_metrics(self):
        """Сбросить метрики (для тестирования)."""
        with self._lock:
            self._metrics = {
                'total_requests': 0,
                'total_errors': 0,
                'total_payments': 0,
                'successful_payments': 0,
                'failed_payments': 0,
                'response_times': deque(maxlen=RESPONSE_TIMES_MAXLEN),
            }


# Глобальный экземпляр логгера платежей
payment_logger = PaymentLogger()
metrics = MetricsCollector()
