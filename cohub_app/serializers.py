from rest_framework import serializers
from django.contrib.auth.models import User
from django.utils import timezone
from .models import Room, RoomMember, Task, TaskReassignmentRequest, Expense, ExpenseShare, ChatMessage, Loan, LoanPayment, Subscription, Order, PaymentEvent


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'first_name', 'last_name']
        read_only_fields = ['id']


class RoomMemberSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)
    user_id = serializers.IntegerField(write_only=True)
    
    class Meta:
        model = RoomMember
        fields = ['id', 'user', 'user_id', 'room', 'is_admin', 'joined_at']
        read_only_fields = ['joined_at']


class RoomSerializer(serializers.ModelSerializer):
    owner = UserSerializer(read_only=True)
    members = RoomMemberSerializer(many=True, read_only=True)
    member_count = serializers.SerializerMethodField()
    
    class Meta:
        model = Room
        fields = ['id', 'name', 'code', 'description', 'owner', 'members', 'member_count', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']
    
    def get_member_count(self, obj):
        return obj.members.count()


class TaskSerializer(serializers.ModelSerializer):
    assigned_to = UserSerializer(read_only=True)
    assigned_to_id = serializers.IntegerField(write_only=True, required=False, allow_null=True)
    created_by = UserSerializer(read_only=True)
    can_complete = serializers.SerializerMethodField()
    completion_hint = serializers.SerializerMethodField()
    
    class Meta:
        model = Task
        fields = ['id', 'room', 'title', 'description', 'assigned_to', 'assigned_to_id', 'status',
                  'priority', 'due_date', 'created_by', 'created_at', 'updated_at', 'completed_at', 'can_complete', 'completion_hint']
        # `status` — read-only: завершение задачи идёт только через action `complete`
        # (с проверкой can_be_completed_by). Иначе любой участник комнаты мог бы
        # выставить status='completed' прямым PATCH, минуя проверку прав.
        read_only_fields = ['id', 'created_by', 'status', 'created_at', 'updated_at', 'completed_at', 'can_complete', 'completion_hint']

    def get_can_complete(self, obj):
        request = self.context.get('request')
        user = getattr(request, 'user', None)
        return obj.can_be_completed_by(user)

    def get_completion_hint(self, obj):
        request = self.context.get('request')
        user = getattr(request, 'user', None)
        accepted_transfer = obj.reassignment_requests.filter(status='accepted').order_by('-responded_at', '-created_at').first()

        if obj.status == 'completed':
            return 'Задача уже завершена'
        if obj.can_be_completed_by(user):
            if accepted_transfer and obj.assigned_to_id == getattr(user, 'id', None):
                return 'Задача передана вам — завершить её может только текущий исполнитель'
            return 'Вы создали эту задачу и можете закрыть её сами'

        if accepted_transfer and obj.assigned_to:
            assignee_name = obj.assigned_to.first_name or obj.assigned_to.username
            return f'После передачи завершить задачу может только {assignee_name}'

        creator_name = None
        if obj.created_by:
            creator_name = obj.created_by.first_name or obj.created_by.username

        if creator_name:
            return f'Закрыть задачу может только {creator_name}. Другой участник сможет сделать это только после принятой передачи'
        return 'Закрыть задачу может только создатель. После передачи — только текущий исполнитель'

    def validate(self, attrs):
        room = attrs.get('room') or getattr(self.instance, 'room', None)
        assigned_to_id = attrs.get('assigned_to_id')

        if room is None:
            raise serializers.ValidationError({'room': 'Комната обязательна'})

        request = self.context.get('request')
        if request and request.user.is_authenticated:
            if not RoomMember.objects.filter(room=room, user=request.user).exists():
                raise serializers.ValidationError({'room': 'Вы не состоите в этой комнате'})

        if assigned_to_id is not None:
            if not RoomMember.objects.filter(room=room, user_id=assigned_to_id).exists():
                raise serializers.ValidationError({'assigned_to_id': 'Исполнитель должен быть участником комнаты'})

        return attrs


class TaskReassignmentRequestSerializer(serializers.ModelSerializer):
    task = TaskSerializer(read_only=True)
    task_id = serializers.UUIDField(write_only=True)
    requested_by = UserSerializer(read_only=True)
    requested_to = UserSerializer(read_only=True)
    requested_to_id = serializers.IntegerField(write_only=True)
    reason_display = serializers.CharField(source='get_reason_display', read_only=True)
    task_title = serializers.CharField(source='task.title', read_only=True)

    class Meta:
        model = TaskReassignmentRequest
        fields = [
            'id', 'room', 'task', 'task_id', 'task_title',
            'requested_by', 'requested_to', 'requested_to_id',
            'reason', 'reason_display', 'custom_message',
            'status', 'response_note', 'created_at', 'updated_at', 'responded_at'
        ]
        read_only_fields = [
            'id', 'room', 'task', 'task_title', 'requested_by', 'requested_to',
            'reason_display', 'status', 'response_note', 'created_at', 'updated_at', 'responded_at'
        ]

    def validate(self, attrs):
        request = self.context.get('request')
        task_id = attrs.get('task_id')
        requested_to_id = attrs.get('requested_to_id')
        task = Task.objects.filter(id=task_id).select_related('room', 'assigned_to', 'created_by').first()

        if not request or not request.user.is_authenticated:
            raise serializers.ValidationError({'task_id': 'Не удалось определить пользователя'})
        if task is None:
            raise serializers.ValidationError({'task_id': 'Задача не найдена'})
        if task.status == 'completed':
            raise serializers.ValidationError({'task_id': 'Нельзя передать уже выполненную задачу'})
        if task.assigned_to_id != request.user.id:
            raise serializers.ValidationError({'task_id': 'Передачу может запросить только текущий исполнитель'})
        if requested_to_id == request.user.id:
            raise serializers.ValidationError({'requested_to_id': 'Нельзя отправить запрос самому себе'})
        if not RoomMember.objects.filter(room=task.room, user=request.user).exists():
            raise serializers.ValidationError({'task_id': 'У вас нет доступа к этой комнате'})
        if not RoomMember.objects.filter(room=task.room, user_id=requested_to_id).exists():
            raise serializers.ValidationError({'requested_to_id': 'Получатель должен быть участником комнаты'})
        if TaskReassignmentRequest.objects.filter(task=task, status='pending').exists():
            raise serializers.ValidationError({'task_id': 'Для этой задачи уже есть активный запрос'})

        attrs['task'] = task
        attrs['room'] = task.room
        attrs['custom_message'] = (attrs.get('custom_message') or '').strip()
        return attrs

    def create(self, validated_data):
        request = self.context.get('request')
        validated_data.pop('task_id', None)
        requested_to_id = validated_data.pop('requested_to_id')
        return TaskReassignmentRequest.objects.create(
            requested_by=request.user,
            requested_to_id=requested_to_id,
            **validated_data,
        )


class ExpenseShareSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)
    
    class Meta:
        model = ExpenseShare
        fields = ['id', 'expense', 'user', 'amount', 'is_settled']


class ExpenseSerializer(serializers.ModelSerializer):
    paid_by = UserSerializer(read_only=True)
    paid_by_id = serializers.IntegerField(write_only=True, required=False, allow_null=True)
    is_shared = serializers.BooleanField(read_only=True)
    shared_with_room = serializers.BooleanField(write_only=True, required=False, default=False)
    mark_as_paid = serializers.BooleanField(write_only=True, required=False, default=False)
    shares = ExpenseShareSerializer(many=True, read_only=True)
    
    class Meta:
        model = Expense
        fields = ['id', 'room', 'description', 'amount', 'paid_by', 'paid_by_id', 'is_shared', 'shared_with_room', 'mark_as_paid', 'date', 
                  'category', 'shares', 'created_at', 'updated_at']
        read_only_fields = ['id', 'shares', 'created_at', 'updated_at', 'is_shared']

    def validate(self, attrs):
        room = attrs.get('room') or getattr(self.instance, 'room', None)
        paid_by_id = attrs.get('paid_by_id')
        shared_with_room = bool(attrs.get('shared_with_room'))

        if room is None:
            raise serializers.ValidationError({'room': 'Комната обязательна'})

        request = self.context.get('request')
        if request and request.user.is_authenticated:
            if not RoomMember.objects.filter(room=room, user=request.user).exists():
                raise serializers.ValidationError({'room': 'Вы не состоите в этой комнате'})

            if shared_with_room:
                attrs['paid_by_id'] = None
                attrs['is_shared'] = True
                paid_by_id = None
            elif paid_by_id is None:
                # If payer is omitted, default to the current user for better UX.
                paid_by_id = request.user.id
                attrs['paid_by_id'] = paid_by_id
                attrs['is_shared'] = False

        if not shared_with_room and paid_by_id is None:
            raise serializers.ValidationError({'paid_by_id': 'Укажите плательщика или выберите общий расход'})

        if paid_by_id is not None and not RoomMember.objects.filter(room=room, user_id=paid_by_id).exists():
            raise serializers.ValidationError({'paid_by_id': 'Плательщик должен быть участником комнаты'})

        if paid_by_id is not None:
            attrs['is_shared'] = False

        attrs.pop('shared_with_room', None)
        attrs.pop('mark_as_paid', None)

        category = (attrs.get('category') or '').strip()
        attrs['category'] = category or 'прочее'

        if attrs.get('date') is None:
            attrs['date'] = timezone.localdate()

        return attrs


class LoanSerializer(serializers.ModelSerializer):
    lender = UserSerializer(read_only=True)
    lender_id = serializers.IntegerField(write_only=True, required=False, allow_null=True)
    borrower = UserSerializer(read_only=True)
    borrower_id = serializers.IntegerField(write_only=True)
    created_by = UserSerializer(read_only=True)
    remaining_amount = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    is_overdue = serializers.SerializerMethodField()

    class Meta:
        model = Loan
        fields = [
            'id', 'room', 'lender', 'lender_id', 'borrower', 'borrower_id',
            'amount_total', 'amount_returned', 'remaining_amount', 'due_date', 'note',
            'status', 'is_overdue', 'reminder_count', 'last_reminder_sent_at',
            'created_by', 'created_at', 'updated_at'
        ]
        read_only_fields = [
            'id', 'amount_returned', 'remaining_amount', 'status', 'is_overdue',
            'reminder_count', 'last_reminder_sent_at', 'created_by', 'created_at', 'updated_at'
        ]

    def validate(self, attrs):
        room = attrs.get('room') or getattr(self.instance, 'room', None)
        borrower_id = attrs.get('borrower_id')
        lender_id = attrs.get('lender_id')
        amount_total = attrs.get('amount_total')

        if room is None:
            raise serializers.ValidationError({'room': 'Комната обязательна'})

        request = self.context.get('request')
        if request and request.user.is_authenticated:
            if not RoomMember.objects.filter(room=room, user=request.user).exists():
                raise serializers.ValidationError({'room': 'Вы не состоите в этой комнате'})
            if lender_id is None:
                lender_id = request.user.id
                attrs['lender_id'] = lender_id

        if borrower_id is None:
            raise serializers.ValidationError({'borrower_id': 'Укажите, кто берет деньги'})

        if lender_id == borrower_id:
            raise serializers.ValidationError({'borrower_id': 'Нельзя выдать долг самому себе'})

        if not RoomMember.objects.filter(room=room, user_id=borrower_id).exists():
            raise serializers.ValidationError({'borrower_id': 'Получатель должен быть участником комнаты'})

        if lender_id is not None and not RoomMember.objects.filter(room=room, user_id=lender_id).exists():
            raise serializers.ValidationError({'lender_id': 'Кредитор должен быть участником комнаты'})

        if amount_total is None or amount_total <= 0:
            raise serializers.ValidationError({'amount_total': 'Сумма долга должна быть больше нуля'})

        attrs['note'] = (attrs.get('note') or '').strip()
        return attrs

    def get_is_overdue(self, obj):
        return obj.is_overdue


class LoanPaymentSerializer(serializers.ModelSerializer):
    loan_id = serializers.UUIDField(write_only=True)
    paid_by = UserSerializer(read_only=True)
    loan_remaining_amount = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)

    class Meta:
        model = LoanPayment
        fields = ['id', 'loan_id', 'amount', 'note', 'paid_by', 'paid_at', 'loan_remaining_amount']
        read_only_fields = ['id', 'paid_by', 'paid_at', 'loan_remaining_amount']

    def validate(self, attrs):
        loan_id = attrs.pop('loan_id', None)
        loan = Loan.objects.filter(id=loan_id).select_related('room').first()
        if loan is None:
            raise serializers.ValidationError({'loan_id': 'Долг не найден'})

        request = self.context.get('request')
        if request and request.user.is_authenticated:
            if not RoomMember.objects.filter(room=loan.room, user=request.user).exists():
                raise serializers.ValidationError({'loan_id': 'Нет доступа к этой комнате'})

        amount = attrs.get('amount')
        if amount is None or amount <= 0:
            raise serializers.ValidationError({'amount': 'Сумма возврата должна быть больше нуля'})
        if amount > loan.remaining_amount:
            raise serializers.ValidationError({'amount': 'Сумма возврата превышает остаток долга'})

        attrs['loan'] = loan
        attrs['note'] = (attrs.get('note') or '').strip()
        return attrs

    def create(self, validated_data):
        request = self.context.get('request')
        loan = validated_data['loan']
        payment = LoanPayment.objects.create(
            loan=loan,
            amount=validated_data['amount'],
            note=validated_data.get('note', ''),
            paid_by=request.user if request and request.user.is_authenticated else loan.borrower,
        )
        loan.amount_returned = (loan.amount_returned or 0) + payment.amount
        remaining = loan.refresh_status(save=True)
        payment.loan_remaining_amount = remaining
        return payment

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data['loan_remaining_amount'] = f"{instance.loan.remaining_amount:.2f}"
        return data


class ChatMessageSerializer(serializers.ModelSerializer):
    author = UserSerializer(read_only=True)
    author_name = serializers.SerializerMethodField()

    class Meta:
        model = ChatMessage
        fields = ['id', 'room', 'author', 'author_name', 'text', 'created_at']
        read_only_fields = ['id', 'author', 'author_name', 'created_at']

    def validate(self, attrs):
        room = attrs.get('room') or getattr(self.instance, 'room', None)
        text = (attrs.get('text') or '').strip()

        if room is None:
            raise serializers.ValidationError({'room': 'Комната обязательна'})

        request = self.context.get('request')
        if request and request.user.is_authenticated:
            if not RoomMember.objects.filter(room=room, user=request.user).exists():
                raise serializers.ValidationError({'room': 'Вы не состоите в этой комнате'})

        if not text:
            raise serializers.ValidationError({'text': 'Сообщение не может быть пустым'})

        attrs['text'] = text
        return attrs

    def get_author_name(self, obj):
        return obj.author.get_full_name() or obj.author.username


class SubscriptionSerializer(serializers.ModelSerializer):
    """Сериализатор для работы с подписками"""
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    is_active = serializers.BooleanField(read_only=True)
    days_remaining = serializers.IntegerField(read_only=True)
    trial_days_remaining = serializers.IntegerField(read_only=True)
    
    class Meta:
        model = Subscription
        fields = [
            'id', 'user', 'status', 'status_display', 'is_active',
            'trial_start', 'trial_end', 'paid_start', 'paid_end',
            'amount', 'days_remaining', 'trial_days_remaining',
            'created_at', 'updated_at'
        ]
        read_only_fields = [
            'id', 'user', 'created_at', 'updated_at',
            'status_display', 'is_active', 'days_remaining', 'trial_days_remaining'
        ]


class PaymentEventSerializer(serializers.ModelSerializer):
    """Событие из аудита платежа (PAY-004)."""

    class Meta:
        model = PaymentEvent
        fields = ['id', 'event_type', 'from_status', 'to_status', 'message', 'created_at']
        read_only_fields = fields


class OrderSerializer(serializers.ModelSerializer):
    """Заказ на разовую оплату с историей переходов статуса."""

    status_display = serializers.CharField(source='get_status_display', read_only=True)
    provider_display = serializers.CharField(source='get_provider_display', read_only=True)
    events = PaymentEventSerializer(many=True, read_only=True)
    is_paid = serializers.BooleanField(read_only=True)

    class Meta:
        model = Order
        fields = [
            'id', 'number', 'purpose', 'description', 'subscription_months',
            'amount', 'currency', 'provider', 'provider_display',
            'status', 'status_display', 'is_paid',
            'provider_order_id', 'created_at', 'updated_at', 'paid_at', 'events',
        ]
        read_only_fields = fields
