from decimal import Decimal
import uuid

from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone

class Room(models.Model):
    """Комната/команда для совместного проживания"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255, verbose_name="Название комнаты")
    code = models.CharField(max_length=10, unique=True, verbose_name="Код комнаты")
    description = models.TextField(blank=True, null=True, verbose_name="Описание")
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name='owned_rooms', verbose_name="Владелец")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Дата создания")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Дата изменения")
    
    class Meta:
        verbose_name = "Комната"
        verbose_name_plural = "Комнаты"
        ordering = ['-created_at']
    
    def __str__(self):
        return self.name


class RoomMember(models.Model):
    """Участник комнаты"""
    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name='members', verbose_name="Комната")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='room_memberships', verbose_name="Пользователь")
    joined_at = models.DateTimeField(auto_now_add=True, verbose_name="Дата присоединения")
    is_admin = models.BooleanField(default=False, verbose_name="Администратор")
    
    class Meta:
        verbose_name = "Участник комнаты"
        verbose_name_plural = "Участники комнаты"
        unique_together = ['room', 'user']
    
    def __str__(self):
        return f"{self.user.username} в {self.room.name}"


class Task(models.Model):
    """Задача в комнате"""
    STATUS_CHOICES = [
        ('pending', 'В ожидании'),
        ('in_progress', 'В процессе'),
        ('completed', 'Завершено'),
    ]
    
    PRIORITY_CHOICES = [
        ('low', 'Низкая'),
        ('medium', 'Средняя'),
        ('high', 'Высокая'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name='tasks', verbose_name="Комната")
    title = models.CharField(max_length=255, verbose_name="Название")
    description = models.TextField(blank=True, null=True, verbose_name="Описание")
    assigned_to = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='assigned_tasks', verbose_name="Назначено кому")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending', verbose_name="Статус")
    priority = models.CharField(max_length=20, choices=PRIORITY_CHOICES, default='medium', verbose_name="Приоритет")
    due_date = models.DateTimeField(null=True, blank=True, verbose_name="Срок выполнения")
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='created_tasks', verbose_name="Создано")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Дата создания")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Дата изменения")
    completed_at = models.DateTimeField(null=True, blank=True, verbose_name="Дата завершения")
    
    class Meta:
        verbose_name = "Задача"
        verbose_name_plural = "Задачи"
        ordering = ['-created_at']
        indexes = [
            # Список задач комнаты с фильтром по статусу.
            models.Index(fields=['room', 'status'], name='task_room_status_idx'),
            # Задачи, назначенные конкретному пользователю.
            models.Index(fields=['assigned_to', 'status'], name='task_assignee_status_idx'),
        ]
    
    def __str__(self):
        return self.title

    def can_be_completed_by(self, user):
        if not user or not getattr(user, 'is_authenticated', False):
            return False

        has_accepted_transfer = self.reassignment_requests.filter(status='accepted').exists()
        if has_accepted_transfer:
            return self.assigned_to_id == user.id

        return self.created_by_id == user.id


class TaskReassignmentRequest(models.Model):
    """Запрос на передачу задачи другому участнику."""

    REASON_CHOICES = [
        ('illness', 'Заболел(а)'),
        ('family', 'Семейные обстоятельства'),
        ('exam', 'Экзамен / учеба'),
        ('work', 'Срочная работа'),
        ('trip', 'Отъезд / дорога'),
        ('other', 'Другая причина'),
    ]

    STATUS_CHOICES = [
        ('pending', 'Ожидает ответа'),
        ('accepted', 'Принят'),
        ('declined', 'Отклонён'),
        ('cancelled', 'Отменён'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name='task_reassignment_requests', verbose_name="Комната")
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name='reassignment_requests', verbose_name="Задача")
    requested_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='task_reassignment_requests_sent', verbose_name="Кто просит")
    requested_to = models.ForeignKey(User, on_delete=models.CASCADE, related_name='task_reassignment_requests_received', verbose_name="Кому отправлено")
    reason = models.CharField(max_length=20, choices=REASON_CHOICES, default='other', verbose_name="Причина")
    custom_message = models.CharField(max_length=255, blank=True, verbose_name="Комментарий")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending', verbose_name="Статус")
    response_note = models.CharField(max_length=255, blank=True, verbose_name="Ответ на запрос")
    responded_at = models.DateTimeField(null=True, blank=True, verbose_name="Когда ответили")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Дата создания")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Дата изменения")

    class Meta:
        verbose_name = "Запрос на передачу задачи"
        verbose_name_plural = "Запросы на передачу задач"
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.requested_by.username} → {self.requested_to.username}: {self.task.title}"


class Expense(models.Model):
    """Расход в комнате"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name='expenses', verbose_name="Комната")
    description = models.CharField(max_length=255, verbose_name="Описание")
    amount = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Сумма")
    paid_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='paid_expenses', verbose_name="Оплачено")
    is_shared = models.BooleanField(default=False, verbose_name="Общий расход")
    date = models.DateField(default=timezone.now, verbose_name="Дата")
    category = models.CharField(max_length=100, verbose_name="Категория")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Дата создания")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Дата изменения")
    
    class Meta:
        verbose_name = "Расход"
        verbose_name_plural = "Расходы"
        ordering = ['-date']
        indexes = [
            # Лента расходов комнаты, отсортированная по дате.
            models.Index(fields=['room', '-date'], name='expense_room_date_idx'),
        ]
    
    def __str__(self):
        return f"{self.description} ({self.amount}₸)"


class ExpenseShare(models.Model):
    """Доля расхода для участника"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    expense = models.ForeignKey(Expense, on_delete=models.CASCADE, related_name='shares', verbose_name="Расход")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='expense_shares', verbose_name="Пользователь")
    amount = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Сумма")
    is_settled = models.BooleanField(default=False, verbose_name="Расчеты произведены")
    
    class Meta:
        verbose_name = "Доля расхода"
        verbose_name_plural = "Доли расходов"
        unique_together = ['expense', 'user']
    
    def __str__(self):
        return f"{self.user.username} - {self.amount}₸"


class DebtSettlement(models.Model):
    """Запись о погашении долга между участниками комнаты"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name='debt_settlements', verbose_name="Комната")
    from_user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='debt_settlements_from', verbose_name="Кто погасил")
    to_user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='debt_settlements_to', verbose_name="Кому погасили")
    amount = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Сумма")
    settled_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='debt_settlements_done', verbose_name="Отметил погашение")
    settled_at = models.DateTimeField(auto_now_add=True, verbose_name="Дата погашения")

    class Meta:
        verbose_name = "Погашение долга"
        verbose_name_plural = "История погашений"
        ordering = ['-settled_at']

    def __str__(self):
        return f"{self.from_user.username} -> {self.to_user.username}: {self.amount}₸"


class Loan(models.Model):
    """Ручной долг/заем между участниками комнаты."""

    STATUS_CHOICES = [
        ('active', 'Активен'),
        ('partially_paid', 'Частично погашен'),
        ('paid', 'Полностью погашен'),
        ('overdue', 'Просрочен'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name='loans', verbose_name="Комната")
    lender = models.ForeignKey(User, on_delete=models.CASCADE, related_name='loans_given', verbose_name="Кто дал деньги")
    borrower = models.ForeignKey(User, on_delete=models.CASCADE, related_name='loans_taken', verbose_name="Кто взял деньги")
    amount_total = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Сумма долга")
    amount_returned = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name="Сколько уже вернули")
    due_date = models.DateField(null=True, blank=True, verbose_name="Срок возврата")
    note = models.CharField(max_length=255, blank=True, verbose_name="Комментарий")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active', verbose_name="Статус")
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='created_loans', verbose_name="Кто создал запись")
    last_reminder_sent_at = models.DateTimeField(null=True, blank=True, verbose_name="Последнее напоминание")
    reminder_count = models.PositiveIntegerField(default=0, verbose_name="Сколько раз напоминали")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Дата создания")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Дата обновления")

    class Meta:
        verbose_name = "Ручной долг"
        verbose_name_plural = "Ручные долги"
        ordering = ['status', 'due_date', '-created_at']

    def __str__(self):
        return f"{self.borrower.username} должен {self.lender.username} {self.amount_total}₸"

    @property
    def remaining_amount(self):
        return max((self.amount_total or Decimal('0')) - (self.amount_returned or Decimal('0')), Decimal('0'))

    @property
    def is_overdue(self):
        return bool(self.due_date and self.remaining_amount > 0 and self.due_date < timezone.localdate())

    def refresh_status(self, save=True):
        if self.amount_returned is None:
            self.amount_returned = Decimal('0')
        if self.amount_returned > self.amount_total:
            self.amount_returned = self.amount_total

        remaining = self.remaining_amount
        if remaining <= 0:
            self.status = 'paid'
        elif self.is_overdue:
            self.status = 'overdue'
        elif self.amount_returned > 0:
            self.status = 'partially_paid'
        else:
            self.status = 'active'

        if save:
            self.save(update_fields=['amount_returned', 'status', 'updated_at'])
        return remaining


class LoanPayment(models.Model):
    """Фиксирует возврат части или всей суммы по ручному долгу."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    loan = models.ForeignKey(Loan, on_delete=models.CASCADE, related_name='payments', verbose_name="Долг")
    amount = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Сумма возврата")
    paid_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='loan_payments_made', verbose_name="Кто вернул")
    note = models.CharField(max_length=255, blank=True, verbose_name="Комментарий")
    paid_at = models.DateTimeField(auto_now_add=True, verbose_name="Дата возврата")

    class Meta:
        verbose_name = "Платеж по долгу"
        verbose_name_plural = "Платежи по долгам"
        ordering = ['-paid_at']

    def __str__(self):
        return f"{self.paid_by.username} вернул {self.amount}₸"


class ChatMessage(models.Model):
    """Сообщение чата в комнате"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name='chat_messages', verbose_name="Комната")
    author = models.ForeignKey(User, on_delete=models.CASCADE, related_name='chat_messages', verbose_name="Автор")
    text = models.TextField(verbose_name="Текст сообщения")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Создано")

    class Meta:
        verbose_name = "Сообщение чата"
        verbose_name_plural = "Сообщения чата"
        ordering = ['-created_at']
        indexes = [
            # История сообщений комнаты по времени (пагинация чата).
            models.Index(fields=['room', '-created_at'], name='chat_room_created_idx'),
        ]

    def __str__(self):
        return f"{self.author.username}: {self.text[:30]}"


class UserProfile(models.Model):
    """Дополнительная информация о пользователе (аватар, био и личный статус)"""

    # RBAC: роль пользователя на уровне всего сервиса.
    ROLE_USER = 'user'
    ROLE_ADMIN = 'admin'
    ROLE_CHOICES = [
        (ROLE_USER, 'Пользователь'),
        (ROLE_ADMIN, 'Администратор'),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    avatar = models.ImageField(upload_to='avatars/', blank=True, null=True)
    bio = models.TextField(blank=True, null=True, verbose_name="Биография")
    role = models.CharField(
        max_length=10,
        choices=ROLE_CHOICES,
        default=ROLE_USER,
        verbose_name="Роль (RBAC)",
        help_text="Глобальная роль пользователя: user или admin.",
    )
    mood_key = models.CharField(max_length=20, default='calm', blank=True, verbose_name="Текущее настроение")
    mood_note = models.CharField(max_length=120, blank=True, verbose_name="Короткая заметка к настроению")
    mood_updated_at = models.DateTimeField(blank=True, null=True, verbose_name="Когда обновили настроение")

    def __str__(self):
        return f"Профиль {self.user.username}"


class Subscription(models.Model):
    """Подписка пользователя на сервис"""
    
    STATUS_CHOICES = [
        ('trial', 'Пробный период'),
        ('active', 'Активна'),
        ('expired', 'Истекла'),
        ('cancelled', 'Отменена'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='subscription', verbose_name="Пользователь")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='trial', verbose_name="Статус подписки")
    trial_start = models.DateTimeField(null=True, blank=True, verbose_name="Начало пробного периода")
    trial_end = models.DateTimeField(null=True, blank=True, verbose_name="Конец пробного периода")
    paid_start = models.DateTimeField(null=True, blank=True, verbose_name="Начало оплаченного периода")
    paid_end = models.DateTimeField(null=True, blank=True, verbose_name="Конец оплаченного периода")
    amount = models.DecimalField(max_digits=10, decimal_places=2, default=5000, verbose_name="Сумма подписки (₸)")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Дата создания")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Дата обновления")
    
    class Meta:
        verbose_name = "Подписка"
        verbose_name_plural = "Подписки"
    
    def __str__(self):
        return f"Подписка {self.user.username} - {self.get_status_display()}"
    
    @property
    def is_active(self):
        """Проверяет, активна ли подписка"""
        if self.status == 'active' and self.paid_end:
            return timezone.now() <= self.paid_end
        if self.status == 'trial' and self.trial_end:
            return timezone.now() <= self.trial_end
        return False
    
    @property
    def days_remaining(self):
        """Количество оставшихся дней подписки"""
        if self.status == 'active' and self.paid_end:
            delta = self.paid_end - timezone.now()
            return max(delta.days, 0)
        if self.status == 'trial' and self.trial_end:
            delta = self.trial_end - timezone.now()
            return max(delta.days, 0)
        return 0
    
    @property
    def trial_days_remaining(self):
        """Количество оставшихся дней пробного периода"""
        if self.trial_end:
            delta = self.trial_end - timezone.now()
            return max(delta.days, 0)
        return 0
    
    def start_trial(self, trial_days=7):
        """Начинает пробный период"""
        now = timezone.now()
        self.trial_start = now
        self.trial_end = now + timezone.timedelta(days=trial_days)
        self.status = 'trial'
        self.save()
    
    def activate_paid(self, months=1):
        """Активирует платную подписку"""
        now = timezone.now()
        
        # Если текущая подписка еще активна, продлеваем от текущей даты окончания
        if self.paid_end and self.paid_end > now:
            self.paid_end = self.paid_end + timezone.timedelta(days=30 * months)
        else:
            self.paid_start = now
            self.paid_end = now + timezone.timedelta(days=30 * months)
        
        self.status = 'active'
        self.save()
    
    def cancel(self):
        """Отменяет подписку"""
        self.status = 'cancelled'
        self.save()
    
    def expire(self):
        """Истекает подписку"""
        self.status = 'expired'
        self.save()


class BackgroundTask(models.Model):
    """Задача в очереди. Хранится в БД; выполняется воркером (run_worker)."""

    STATUS_CHOICES = [
        ('pending', 'В очереди'),
        ('running', 'Выполняется'),
        ('done', 'Выполнена'),
        ('failed', 'Ошибка'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    task_name = models.CharField(max_length=100, verbose_name="Имя задачи")
    payload = models.JSONField(default=dict, blank=True, verbose_name="Параметры")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending', verbose_name="Статус")
    attempts = models.PositiveIntegerField(default=0, verbose_name="Сделано попыток")
    max_attempts = models.PositiveIntegerField(default=3, verbose_name="Максимум попыток")
    result = models.TextField(blank=True, verbose_name="Результат или текст ошибки")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Создана")
    started_at = models.DateTimeField(null=True, blank=True, verbose_name="Начата")
    finished_at = models.DateTimeField(null=True, blank=True, verbose_name="Завершена")

    class Meta:
        verbose_name = "Фоновая задача"
        verbose_name_plural = "Фоновые задачи (очередь)"
        ordering = ['created_at']
        indexes = [
            # Воркер выбирает старейшие pending-задачи — индекс ускоряет это.
            models.Index(fields=['status', 'created_at'], name='bgtask_status_created_idx'),
        ]

    def __str__(self):
        return f"{self.task_name} [{self.status}]"


class Order(models.Model):
    """Заказ на разовую оплату (PAY-004).

    Модель жизненного цикла платежа с явным автоматом состояний. Один заказ —
    одна попытка оплаты PRO-подписки через внешний провайдер (Bereke / PayPal).

    Допустимые переходы описаны в ALLOWED_TRANSITIONS и проверяются методом
    transition_to(): нельзя, например, из 'paid' уйти в 'pending'. Каждый переход
    фиксируется в PaymentEvent — получается полный аудит платежа.
    """

    # --- Состояния жизненного цикла ---
    STATUS_CREATED = 'created'        # заказ создан, оплата ещё не начата
    STATUS_PENDING = 'pending'        # пользователь ушёл на платёжную форму
    STATUS_PAID = 'paid'              # оплата подтверждена провайдером
    STATUS_FAILED = 'failed'          # оплата отклонена/ошибка
    STATUS_CANCELLED = 'cancelled'    # пользователь отменил оплату
    STATUS_EXPIRED = 'expired'        # истёк срок оплаты
    STATUS_REFUNDED = 'refunded'      # возврат после успешной оплаты

    STATUS_CHOICES = [
        (STATUS_CREATED, 'Создан'),
        (STATUS_PENDING, 'Ожидает оплаты'),
        (STATUS_PAID, 'Оплачен'),
        (STATUS_FAILED, 'Ошибка оплаты'),
        (STATUS_CANCELLED, 'Отменён'),
        (STATUS_EXPIRED, 'Истёк'),
        (STATUS_REFUNDED, 'Возврат'),
    ]

    # Автомат состояний: из какого статуса в какие можно перейти.
    ALLOWED_TRANSITIONS = {
        STATUS_CREATED: {STATUS_PENDING, STATUS_CANCELLED, STATUS_EXPIRED, STATUS_FAILED},
        STATUS_PENDING: {STATUS_PAID, STATUS_FAILED, STATUS_CANCELLED, STATUS_EXPIRED},
        STATUS_FAILED: {STATUS_PENDING},          # можно повторить попытку
        STATUS_PAID: {STATUS_REFUNDED},
        STATUS_CANCELLED: set(),                  # терминальное состояние
        STATUS_EXPIRED: set(),                    # терминальное состояние
        STATUS_REFUNDED: set(),                   # терминальное состояние
    }
    # Статусы, после которых заказ уже нельзя оплатить.
    TERMINAL_STATUSES = {STATUS_PAID, STATUS_CANCELLED, STATUS_EXPIRED, STATUS_REFUNDED}

    PROVIDER_BEREKE = 'bereke'
    PROVIDER_PAYPAL = 'paypal'
    PROVIDER_CHOICES = [
        (PROVIDER_BEREKE, 'Bereke Bank'),
        (PROVIDER_PAYPAL, 'PayPal'),
    ]

    PURPOSE_SUBSCRIPTION = 'subscription'
    PURPOSE_CHOICES = [
        (PURPOSE_SUBSCRIPTION, 'PRO-подписка'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # Человекочитаемый номер заказа (ORD-XXXXXXXX) — удобно для платёжных форм и поддержки.
    number = models.CharField(max_length=20, unique=True, editable=False, verbose_name="Номер заказа")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='orders', verbose_name="Пользователь")

    purpose = models.CharField(max_length=20, choices=PURPOSE_CHOICES, default=PURPOSE_SUBSCRIPTION, verbose_name="Назначение")
    description = models.CharField(max_length=255, blank=True, verbose_name="Описание")
    subscription_months = models.PositiveIntegerField(default=1, verbose_name="Месяцев подписки")

    amount = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Сумма")
    currency = models.CharField(max_length=3, default='KZT', verbose_name="Валюта")
    provider = models.CharField(max_length=20, choices=PROVIDER_CHOICES, default=PROVIDER_BEREKE, verbose_name="Провайдер")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_CREATED, verbose_name="Статус")

    # PAY-005: ключ идемпотентности. Уникален — две одинаковые отправки checkout
    # не создадут два заказа (повторная отправка вернёт тот же заказ).
    idempotency_key = models.CharField(max_length=64, unique=True, verbose_name="Ключ идемпотентности")

    # Идентификаторы на стороне провайдера (invoice id, capture id и т.п.).
    provider_order_id = models.CharField(max_length=128, blank=True, verbose_name="ID заказа у провайдера")
    provider_payment_id = models.CharField(max_length=128, blank=True, verbose_name="ID платежа у провайдера")

    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Создан")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Обновлён")
    paid_at = models.DateTimeField(null=True, blank=True, verbose_name="Оплачен")

    class Meta:
        verbose_name = "Заказ (платёж)"
        verbose_name_plural = "Заказы (платежи)"
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'status'], name='order_user_status_idx'),
            models.Index(fields=['provider', 'provider_order_id'], name='order_provider_ref_idx'),
        ]

    def __str__(self):
        return f"{self.number} [{self.get_status_display()}] {self.amount}{self.currency}"

    def save(self, *args, **kwargs):
        if not self.number:
            self.number = self._generate_number()
        super().save(*args, **kwargs)

    @staticmethod
    def _generate_number():
        while True:
            number = 'ORD-' + uuid.uuid4().hex[:8].upper()
            if not Order.objects.filter(number=number).exists():
                return number

    @property
    def is_paid(self):
        return self.status == self.STATUS_PAID

    @property
    def is_open(self):
        """Заказ ещё можно оплатить (не в терминальном статусе)."""
        return self.status not in self.TERMINAL_STATUSES

    def can_transition_to(self, new_status):
        return new_status in self.ALLOWED_TRANSITIONS.get(self.status, set())

    def transition_to(self, new_status, message='', payload=None, event_type='transition', save=True):
        """Перевести заказ в новый статус по правилам автомата.

        Возвращает True, если переход выполнен; False — если он недопустим или
        статус уже совпадает (идемпотентность повторных колбэков). Любая попытка
        перехода логируется в PaymentEvent.
        """
        if new_status == self.status:
            # Повторный колбэк с тем же статусом — не ошибка, просто фиксируем.
            PaymentEvent.objects.create(
                order=self, event_type='duplicate', from_status=self.status,
                to_status=new_status, message=message or 'Повторное событие, статус не изменился',
                payload=payload or {},
            )
            return False

        if not self.can_transition_to(new_status):
            PaymentEvent.objects.create(
                order=self, event_type='rejected', from_status=self.status,
                to_status=new_status,
                message=message or f'Недопустимый переход {self.status} → {new_status}',
                payload=payload or {},
            )
            return False

        from_status = self.status
        self.status = new_status
        update_fields = ['status', 'updated_at']
        if new_status == self.STATUS_PAID and not self.paid_at:
            self.paid_at = timezone.now()
            update_fields.append('paid_at')

        if save:
            self.save(update_fields=update_fields)

        PaymentEvent.objects.create(
            order=self, event_type=event_type, from_status=from_status,
            to_status=new_status, message=message, payload=payload or {},
        )
        return True


class PaymentEvent(models.Model):
    """Событие по заказу: переход статуса или входящий колбэк провайдера.

    Полный аудит платежа — кто, когда и с какими данными менял состояние заказа.
    Сюда же складываем сырой payload провайдера (полезно при отладке через ngrok).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='events', verbose_name="Заказ")
    event_type = models.CharField(max_length=30, verbose_name="Тип события")
    from_status = models.CharField(max_length=20, blank=True, verbose_name="Из статуса")
    to_status = models.CharField(max_length=20, blank=True, verbose_name="В статус")
    message = models.CharField(max_length=255, blank=True, verbose_name="Сообщение")
    payload = models.JSONField(default=dict, blank=True, verbose_name="Данные провайдера")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Время")

    class Meta:
        verbose_name = "Событие платежа"
        verbose_name_plural = "События платежей"
        ordering = ['created_at']
        indexes = [
            models.Index(fields=['order', 'created_at'], name='payevent_order_time_idx'),
        ]

    def __str__(self):
        return f"{self.order.number}: {self.event_type} {self.from_status}→{self.to_status}"


# Signal to create profile and subscription automatically when a User is created
from django.db.models.signals import post_save
from django.dispatch import receiver

@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    # raw=True означает загрузку фикстуры/бэкапа (loaddata): объекты приходят
    # «как есть», и профиль/подписка обычно уже содержатся в дампе. В этом случае
    # не создаём их сами — иначе вставка соответствующих строк дампа упадёт с
    # IntegrityError на уникальном user_id (OneToOne).
    if kwargs.get('raw'):
        return
    if created:
        # get_or_create — на случай, если строка уже существует (идемпотентность).
        UserProfile.objects.get_or_create(user=instance)
        subscription, sub_created = Subscription.objects.get_or_create(user=instance)
        if sub_created:
            # Пробный период запускаем только для действительно новой подписки.
            subscription.start_trial(trial_days=7)