from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.contrib.auth.models import User
from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404
from django.db.models import Sum, Q, F
from django.contrib.auth.password_validation import validate_password
from decimal import Decimal
from PIL import Image, UnidentifiedImageError
import hashlib
import string
import random

from .models import Room, RoomMember, Task, Expense, ExpenseShare, UserProfile, ChatMessage, DebtSettlement
from .serializers import (
    RoomSerializer, RoomMemberSerializer, TaskSerializer, 
    ExpenseSerializer, ExpenseShareSerializer, UserSerializer, ChatMessageSerializer
)
from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.auth import authenticate, login
from django.utils.text import slugify
from datetime import timedelta


def get_client_ip(request):
    forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR', '')
    if forwarded_for:
        return forwarded_for.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', 'unknown')


def get_login_rate_limit_keys(request, email):
    client_ip = get_client_ip(request)
    email_hash = hashlib.sha256((email or '').encode('utf-8')).hexdigest()[:16]
    return [
        f'login-attempts:ip:{client_ip}',
        f'login-attempts:email:{email_hash}',
    ]


def is_login_rate_limited(request, email):
    limit = max(settings.LOGIN_RATE_LIMIT, 1)
    return any((cache.get(key) or 0) >= limit for key in get_login_rate_limit_keys(request, email))


def register_failed_login_attempt(request, email):
    timeout = max(settings.LOGIN_RATE_LIMIT_WINDOW, 60)
    for key in get_login_rate_limit_keys(request, email):
        if cache.add(key, 1, timeout=timeout):
            continue
        try:
            cache.incr(key)
        except ValueError:
            cache.set(key, 1, timeout=timeout)


def clear_failed_login_attempts(request, email):
    cache.delete_many(get_login_rate_limit_keys(request, email))


def validate_avatar_upload(avatar):
    if avatar.size > settings.AVATAR_MAX_UPLOAD_SIZE:
        max_size_mb = settings.AVATAR_MAX_UPLOAD_SIZE / (1024 * 1024)
        raise ValidationError(f'Аватар слишком большой. Максимум {max_size_mb:.1f} МБ.')

    allowed_content_types = {'image/jpeg', 'image/png', 'image/gif', 'image/webp'}
    content_type = (getattr(avatar, 'content_type', '') or '').lower()
    if content_type and content_type not in allowed_content_types:
        raise ValidationError('Допустимы только изображения JPG, PNG, GIF или WebP.')

    try:
        Image.open(avatar).verify()
    except (UnidentifiedImageError, OSError):
        raise ValidationError('Файл аватара поврежден или не является изображением.')
    finally:
        avatar.seek(0)


class RoomViewSet(viewsets.ModelViewSet):
    """ViewSet для управления комнатами"""
    queryset = Room.objects.all()
    serializer_class = RoomSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        """Возвращает комнаты, в которых участвует пользователь"""
        user = self.request.user
        return Room.objects.filter(
            Q(owner=user) | Q(members__user=user)
        ).distinct()
    
    def perform_create(self, serializer):
        """Создает комнату с текущим пользователем как владельцем"""
        code = self.generate_room_code()
        room = serializer.save(owner=self.request.user, code=code)
        # Добавляем владельца как участника
        RoomMember.objects.create(room=room, user=self.request.user, is_admin=True)
    
    @staticmethod
    def generate_room_code():
        """Генерирует уникальный код комнаты"""
        while True:
            code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
            if not Room.objects.filter(code=code).exists():
                return code
    
    @action(detail=False, methods=['post'])
    def join_room(self, request):
        """Присоединиться к комнате по коду"""
        code = (request.data.get('code') or '').strip().upper()
        if not code:
            return Response({'error': 'Код комнаты не предоставлен'}, status=status.HTTP_400_BAD_REQUEST)
        
        room = get_object_or_404(Room, code=code)
        
        # Проверяем, не является ли пользователь уже участником
        if room.members.filter(user=request.user).exists():
            return Response({'error': 'Вы уже участник этой комнаты'}, status=status.HTTP_400_BAD_REQUEST)
        
        RoomMember.objects.create(room=room, user=request.user)
        serializer = self.get_serializer(room)
        return Response(serializer.data)
    
    @action(detail='pk', methods=['get'])
    def statistics(self, request, pk=None):
        """Получить статистику по комнате"""
        room = self.get_object()
        
        # Проверяем доступ
        if not (room.owner == request.user or room.members.filter(user=request.user).exists()):
            return Response({'error': 'Нет доступа'}, status=status.HTTP_403_FORBIDDEN)
        
        tasks_count = room.tasks.count()
        completed_tasks = room.tasks.filter(status='completed').count()
        total_expenses = room.expenses.aggregate(Sum('amount'))['amount__sum'] or Decimal('0')
        
        # Открытые долги считаем только по незакрытым долям расходов.
        members = list(room.members.select_related('user'))
        user_display = {
            member.user_id: (member.user.get_full_name() or member.user.username)
            for member in members
        }
        user_username = {
            member.user_id: member.user.username
            for member in members
        }
        user_balances = {member.user_id: Decimal('0') for member in members}

        open_shares = ExpenseShare.objects.filter(
            expense__room=room,
            is_settled=False,
            expense__paid_by__isnull=False,
        ).exclude(user=F('expense__paid_by')).select_related('expense__paid_by', 'user')

        debts_map = {}
        for share in open_shares:
            debtor_id = share.user_id
            creditor_id = share.expense.paid_by_id
            amount = share.amount or Decimal('0')

            user_balances[debtor_id] = user_balances.get(debtor_id, Decimal('0')) - amount
            user_balances[creditor_id] = user_balances.get(creditor_id, Decimal('0')) + amount

            pair = (debtor_id, creditor_id)
            debts_map[pair] = debts_map.get(pair, Decimal('0')) + amount

        balances = {
            user_username[user_id]: float(balance)
            for user_id, balance in user_balances.items()
            if user_id in user_username
        }

        debts = []
        for (debtor_id, creditor_id), amount in debts_map.items():
            if amount <= Decimal('0'):
                continue
            debts.append({
                'from_user_id': debtor_id,
                'from_name': user_display.get(debtor_id, str(debtor_id)),
                'to_user_id': creditor_id,
                'to_name': user_display.get(creditor_id, str(creditor_id)),
                'amount': float(amount),
            })

        debts.sort(key=lambda item: item['amount'], reverse=True)

        recent_settlements = []
        for settlement in room.debt_settlements.select_related('from_user', 'to_user', 'settled_by')[:8]:
            recent_settlements.append({
                'id': str(settlement.id),
                'from_user_id': settlement.from_user_id,
                'from_name': settlement.from_user.get_full_name() or settlement.from_user.username,
                'to_user_id': settlement.to_user_id,
                'to_name': settlement.to_user.get_full_name() or settlement.to_user.username,
                'amount': float(settlement.amount),
                'settled_by': (
                    (settlement.settled_by.get_full_name() or settlement.settled_by.username)
                    if settlement.settled_by else None
                ),
                'settled_at': settlement.settled_at.isoformat(),
            })
        
        return Response({
            'tasks': {
                'total': tasks_count,
                'completed': completed_tasks,
                'pending': room.tasks.filter(status='pending').count(),
            },
            'expenses': {
                'total': float(total_expenses),
                'by_category': list(room.expenses.values('category').annotate(total=Sum('amount'))),
            },
            'balances': balances,
            'debts': debts,
            'recent_settlements': recent_settlements,
        })

    @action(detail=True, methods=['get'])
    def assistant(self, request, pk=None):
        """Мини-помощник: советы по покупкам, задачам и расходам."""
        room = self.get_object()

        try:
            days = int(request.query_params.get('days', 30))
        except (TypeError, ValueError):
            days = 30
        days = max(7, min(days, 90))
        period_start = timezone.localdate() - timedelta(days=days - 1)

        members = list(room.members.select_related('user'))
        member_names = {
            member.user_id: (member.user.get_full_name() or member.user.username)
            for member in members
        }

        expenses = list(room.expenses.filter(date__gte=period_start))
        total_expenses = sum((expense.amount or Decimal('0')) for expense in expenses)

        food_keywords = ('еда', 'food', 'продукт', 'продукты')
        food_expenses = sum(
            (expense.amount or Decimal('0'))
            for expense in expenses
            if any(keyword in (expense.category or '').lower() for keyword in food_keywords)
        )

        expense_insights = []
        shopping_list = ['Крупы/макароны', 'Овощи на неделю', 'Бытовая химия', 'Мыло и бумага']

        if total_expenses > 0:
            food_share = food_expenses / total_expenses
            if food_share >= Decimal('0.45'):
                expense_insights.append('Вы тратите много на еду. Попробуйте покупать продукты оптом.')
                shopping_list = [
                    'Крупы (рис, гречка) оптом',
                    'Макароны большими пачками',
                    'Заморозка (овощи/курица)',
                    'Базовые специи и масло',
                ]
            else:
                expense_insights.append('Расходы по категориям выглядят относительно сбалансированно.')
        else:
            expense_insights.append('Пока мало данных по расходам. Добавьте траты, и я дам точные советы.')

        tasks = list(room.tasks.all())
        pending_tasks = [task for task in tasks if task.status != 'completed']
        unassigned_count = sum(1 for task in pending_tasks if not task.assigned_to_id)

        member_load = {member.user_id: 0 for member in members}
        for task in pending_tasks:
            if task.assigned_to_id in member_load:
                member_load[task.assigned_to_id] += 1

        task_suggestions = []
        if member_load:
            least_loaded_id = min(member_load, key=member_load.get)
            most_loaded_id = max(member_load, key=member_load.get)
            load_diff = member_load[most_loaded_id] - member_load[least_loaded_id]

            if unassigned_count > 0:
                task_suggestions.append(
                    f'Есть непривязанные задачи ({unassigned_count}). Назначьте часть на {member_names.get(least_loaded_id, "участника")}. '
                )

            if load_diff >= 2:
                task_suggestions.append(
                    f'Задачи распределены неравномерно: у {member_names.get(most_loaded_id, "одного участника")} заметно больше дел. '
                    f'Перераспределите часть задач на {member_names.get(least_loaded_id, "другого участника")}. '
                )

        if not task_suggestions:
            task_suggestions.append('Распределение задач выглядит ровным. Продолжайте в том же темпе.')

        open_shares = ExpenseShare.objects.filter(
            expense__room=room,
            is_settled=False,
            expense__paid_by__isnull=False,
        ).exclude(user=F('expense__paid_by')).select_related('expense__paid_by')
        member_debt = {member.user_id: Decimal('0') for member in members}
        member_credit = {member.user_id: Decimal('0') for member in members}
        for share in open_shares:
            amount = share.amount or Decimal('0')
            member_debt[share.user_id] = member_debt.get(share.user_id, Decimal('0')) + amount
            member_credit[share.expense.paid_by_id] = member_credit.get(share.expense.paid_by_id, Decimal('0')) + amount

        average_load = (sum(member_load.values()) / len(member_load)) if member_load else 0
        personal_suggestions = []
        for member in members:
            uid = member.user_id
            advice = []
            load = member_load.get(uid, 0)
            debt_value = member_debt.get(uid, Decimal('0'))
            credit_value = member_credit.get(uid, Decimal('0'))

            if load == 0 and pending_tasks:
                advice.append('Можно взять 1-2 задачи из общего пула, чтобы разгрузить команду.')
            elif load > average_load + 1:
                advice.append('Сейчас у вас повышенная нагрузка по задачам. Лучше делегировать часть дел.')

            if debt_value > Decimal('0'):
                advice.append(f'Открытый долг: {float(debt_value):.2f}₸. Закройте его в ближайшее время.')
            elif credit_value > Decimal('0'):
                advice.append(f'Вам должны: {float(credit_value):.2f}₸. Проверьте, что все долги зафиксированы.')

            if not advice:
                advice.append('Все выглядит стабильно: продолжайте в том же ритме.')

            personal_suggestions.append({
                'user_id': uid,
                'name': member_names.get(uid, str(uid)),
                'advice': advice,
            })

        return Response({
            'advice_title': 'Совет',
            'expense_insights': expense_insights,
            'shopping_list': shopping_list,
            'task_suggestions': task_suggestions,
            'personal_suggestions': personal_suggestions,
            'metrics': {
                'period_days': days,
                'total_expenses': float(total_expenses),
                'food_expenses': float(food_expenses),
                'pending_tasks': len(pending_tasks),
                'unassigned_tasks': unassigned_count,
            },
        })

    @action(detail=True, methods=['post'])
    def assistant_apply_shopping(self, request, pk=None):
        """Создает задачи покупки на основе рекомендаций помощника."""
        room = self.get_object()
        shopping_list = request.data.get('shopping_list') or []
        if not isinstance(shopping_list, list) or not shopping_list:
            shopping_list = ['Крупы/макароны', 'Овощи на неделю', 'Бытовая химия', 'Мыло и бумага']

        created_count = 0
        skipped_count = 0
        created_tasks = []

        for item in shopping_list:
            label = str(item).strip()
            if not label:
                continue
            title = f'Купить: {label}'
            exists = room.tasks.filter(title=title).exclude(status='completed').exists()
            if exists:
                skipped_count += 1
                continue

            task = Task.objects.create(
                room=room,
                title=title,
                description='Создано AI-помощником из списка покупок.',
                status='pending',
                priority='medium',
                created_by=request.user,
                assigned_to=request.user,
            )
            created_tasks.append(str(task.id))
            created_count += 1

        return Response({
            'created_count': created_count,
            'skipped_count': skipped_count,
            'created_task_ids': created_tasks,
        })

    @action(detail=True, methods=['post'])
    def assistant_apply_tasks(self, request, pk=None):
        """Авто-распределяет незавершенные задачи между участниками комнаты."""
        room = self.get_object()
        members = list(room.members.select_related('user'))
        member_ids = [member.user_id for member in members]
        if not member_ids:
            return Response({'updated_count': 0})

        pending_tasks = list(room.tasks.filter(status__in=['pending', 'in_progress']).select_related('assigned_to'))
        member_load = {uid: 0 for uid in member_ids}
        for task in pending_tasks:
            if task.assigned_to_id in member_load:
                member_load[task.assigned_to_id] += 1

        updated_count = 0

        unassigned = [task for task in pending_tasks if not task.assigned_to_id]
        for task in unassigned:
            target_user_id = min(member_load, key=member_load.get)
            task.assigned_to_id = target_user_id
            task.save(update_fields=['assigned_to'])
            member_load[target_user_id] += 1
            updated_count += 1

        # Мягкое выравнивание: переносим только часть задач при сильной разнице нагрузки.
        if member_load:
            while True:
                most_loaded = max(member_load, key=member_load.get)
                least_loaded = min(member_load, key=member_load.get)
                if member_load[most_loaded] - member_load[least_loaded] < 2:
                    break

                task_to_move = room.tasks.filter(
                    status__in=['pending', 'in_progress'],
                    assigned_to_id=most_loaded,
                ).order_by('created_at').first()
                if not task_to_move:
                    break

                task_to_move.assigned_to_id = least_loaded
                task_to_move.save(update_fields=['assigned_to'])
                member_load[most_loaded] -= 1
                member_load[least_loaded] += 1
                updated_count += 1

        return Response({'updated_count': updated_count})

    @action(detail=True, methods=['post'])
    def assistant_apply_personal(self, request, pk=None):
        """Применяет персональный совет: назначает или переносит одну задачу на выбранного участника."""
        room = self.get_object()
        user_id = request.data.get('user_id')

        if not user_id:
            return Response({'error': 'user_id обязателен'}, status=status.HTTP_400_BAD_REQUEST)

        target_member = room.members.filter(user_id=user_id).select_related('user').first()
        if not target_member:
            return Response({'error': 'Участник не найден в комнате'}, status=status.HTTP_400_BAD_REQUEST)

        target_user_id = target_member.user_id
        target_name = target_member.user.get_full_name() or target_member.user.username

        pending_tasks = list(room.tasks.filter(status__in=['pending', 'in_progress']).select_related('assigned_to'))
        member_ids = list(room.members.values_list('user_id', flat=True))
        member_load = {uid: 0 for uid in member_ids}
        for task in pending_tasks:
            if task.assigned_to_id in member_load:
                member_load[task.assigned_to_id] += 1

        unassigned_task = next((task for task in pending_tasks if not task.assigned_to_id), None)
        if unassigned_task:
            unassigned_task.assigned_to_id = target_user_id
            unassigned_task.save(update_fields=['assigned_to'])
            return Response({
                'updated_count': 1,
                'target_user_id': target_user_id,
                'target_name': target_name,
                'task_title': unassigned_task.title,
            })

        most_loaded_user = max(member_load, key=member_load.get) if member_load else None
        if most_loaded_user is None or most_loaded_user == target_user_id:
            return Response({'updated_count': 0, 'target_user_id': target_user_id, 'target_name': target_name})

        if member_load[most_loaded_user] - member_load.get(target_user_id, 0) < 2:
            return Response({'updated_count': 0, 'target_user_id': target_user_id, 'target_name': target_name})

        task_to_move = room.tasks.filter(
            status__in=['pending', 'in_progress'],
            assigned_to_id=most_loaded_user,
        ).order_by('created_at').first()

        if not task_to_move:
            return Response({'updated_count': 0, 'target_user_id': target_user_id, 'target_name': target_name})

        task_to_move.assigned_to_id = target_user_id
        task_to_move.save(update_fields=['assigned_to'])

        return Response({
            'updated_count': 1,
            'target_user_id': target_user_id,
            'target_name': target_name,
            'task_title': task_to_move.title,
        })


class TaskViewSet(viewsets.ModelViewSet):
    """ViewSet для управления задачами"""
    queryset = Task.objects.all()
    serializer_class = TaskSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        """Возвращает задачи из комнат пользователя"""
        user = self.request.user
        rooms = Room.objects.filter(
            Q(owner=user) | Q(members__user=user)
        ).values_list('id', flat=True)
        queryset = Task.objects.filter(room__id__in=rooms)

        room_id = self.request.query_params.get('room')
        status_filter = self.request.query_params.get('status')

        if room_id:
            queryset = queryset.filter(room_id=room_id)
        if status_filter:
            queryset = queryset.filter(status=status_filter)

        return queryset.select_related('assigned_to', 'created_by', 'room')
    
    def perform_create(self, serializer):
        """Создает задачу с текущим пользователем"""
        serializer.save(created_by=self.request.user)
    
    @action(detail=True, methods=['post'])
    def complete(self, request, pk=None):
        """Отметить задачу как завершенную"""
        task = self.get_object()
        task.status = 'completed'
        task.completed_at = timezone.now()
        task.save()
        serializer = self.get_serializer(task)
        return Response(serializer.data)


class ExpenseViewSet(viewsets.ModelViewSet):
    """ViewSet для управления расходами"""
    queryset = Expense.objects.all()
    serializer_class = ExpenseSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        """Возвращает расходы из комнат пользователя"""
        user = self.request.user
        rooms = Room.objects.filter(
            Q(owner=user) | Q(members__user=user)
        ).values_list('id', flat=True)
        queryset = Expense.objects.filter(room__id__in=rooms)

        room_id = self.request.query_params.get('room')
        category = self.request.query_params.get('category')

        if room_id:
            queryset = queryset.filter(room_id=room_id)
        if category:
            queryset = queryset.filter(category=category)

        return queryset.select_related('paid_by', 'room').prefetch_related('shares__user')
    
    def perform_create(self, serializer):
        """Создает расход и распределяет доли"""
        expense = serializer.save()
        
        # Автоматически распределяем расход на всех участников комнаты поровну
        room = expense.room
        members = room.members.all()
        if members.exists():
            share_amount = expense.amount / members.count()
            for member in members:
                ExpenseShare.objects.create(
                    expense=expense,
                    user=member.user,
                    amount=share_amount
                )


class ExpenseShareViewSet(viewsets.ModelViewSet):
    """ViewSet для управления долями расходов"""
    queryset = ExpenseShare.objects.all()
    serializer_class = ExpenseShareSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """Возвращает доли только по комнатам пользователя"""
        user = self.request.user
        rooms = Room.objects.filter(
            Q(owner=user) | Q(members__user=user)
        ).values_list('id', flat=True)
        return ExpenseShare.objects.filter(expense__room__id__in=rooms).select_related('user', 'expense').order_by('-expense__date', 'id')

    @action(detail=True, methods=['post'])
    def settle(self, request, pk=None):
        """Отметить долю как расчеты произведены"""
        share = self.get_object()
        share.is_settled = True
        share.save()
        serializer = self.get_serializer(share)
        return Response(serializer.data)

    @action(detail=False, methods=['post'])
    def settle_between(self, request):
        """Закрывает все незакрытые доли между двумя пользователями в комнате."""
        room_id = request.data.get('room')
        from_user_id = request.data.get('from_user_id')
        to_user_id = request.data.get('to_user_id')

        if not room_id or not from_user_id or not to_user_id:
            return Response(
                {'error': 'room, from_user_id и to_user_id обязательны'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        room = get_object_or_404(Room, id=room_id)
        if not room.members.filter(user=request.user).exists():
            return Response({'error': 'Нет доступа к комнате'}, status=status.HTTP_403_FORBIDDEN)

        from_in_room = room.members.filter(user_id=from_user_id).exists()
        to_in_room = room.members.filter(user_id=to_user_id).exists()
        if not (from_in_room and to_in_room):
            return Response({'error': 'Пользователи должны быть участниками комнаты'}, status=status.HTTP_400_BAD_REQUEST)

        shares_to_settle = ExpenseShare.objects.filter(
            expense__room=room,
            user_id=from_user_id,
            expense__paid_by_id=to_user_id,
            is_settled=False,
        )

        settled_amount = shares_to_settle.aggregate(total=Sum('amount'))['total'] or Decimal('0')
        settled_count = shares_to_settle.update(is_settled=True)

        if settled_count > 0:
            DebtSettlement.objects.create(
                room=room,
                from_user_id=from_user_id,
                to_user_id=to_user_id,
                amount=settled_amount,
                settled_by=request.user,
            )

        return Response({
            'settled_count': settled_count,
            'settled_amount': float(settled_amount),
        })


class ChatMessageViewSet(viewsets.ModelViewSet):
    """ViewSet для сообщений чата"""
    queryset = ChatMessage.objects.all()
    serializer_class = ChatMessageSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        rooms = Room.objects.filter(
            Q(owner=user) | Q(members__user=user)
        ).values_list('id', flat=True)
        queryset = ChatMessage.objects.filter(room__id__in=rooms)

        room_id = self.request.query_params.get('room')
        if room_id:
            queryset = queryset.filter(room_id=room_id)

        return queryset.select_related('author', 'room').order_by('-created_at')

    def perform_create(self, serializer):
        serializer.save(author=self.request.user)


from django.utils import timezone


def register_view(request):
    """Обработка регистрации пользователя (формой POST)."""
    if request.method == 'POST':
        full_name = request.POST.get('full_name', '').strip()
        email = request.POST.get('email', '').strip().lower()
        password = request.POST.get('password', '')
        password_confirm = request.POST.get('password_confirm', '')
        terms = request.POST.get('terms')

        errors = []
        if not full_name:
            errors.append('Пожалуйста, укажите полное имя')
        if not email:
            errors.append('Пожалуйста, укажите email')
        if not password or not password_confirm:
            errors.append('Пожалуйста, укажите пароль и подтвердите его')
        if password != password_confirm:
            errors.append('Пароли не совпадают')
        if not terms:
            errors.append('Необходимо согласиться с условиями')

        if password:
            temp_user = User(username=email, email=email)
            try:
                validate_password(password, user=temp_user)
            except ValidationError as exc:
                errors.extend(exc.messages)

        if email and User.objects.filter(username=email).exists():
            errors.append('Пользователь с таким email уже существует')

        if errors:
            return render(request, 'register.html', {
                'errors': errors,
                'full_name': full_name,
                'email': email,
            })

        # Создаем пользователя

        # Создаем пользователя
        first_name = full_name.split(' ', 1)[0]
        last_name = full_name.split(' ', 1)[1] if ' ' in full_name else ''
        user = User.objects.create_user(username=email, email=email, password=password,
                                        first_name=first_name, last_name=last_name)

        # профиль/аватар (сигнал уже создаст пустой профиль)
        avatar = request.FILES.get('avatar')
        if avatar:
            try:
                validate_avatar_upload(avatar)
                profile = user.profile
                profile.avatar = avatar
                profile.save()
            except ValidationError as exc:
                user.delete()
                return render(request, 'register.html', {
                    'errors': list(exc.messages),
                    'full_name': full_name,
                    'email': email,
                })

        # Аутентифицируем и логиним сразу
        user = authenticate(request, username=email, password=password)
        if user is not None:
            login(request, user)
            messages.success(request, 'Регистрация прошла успешно')
            return redirect('dashboard')

        # На случай если аутентификация не удалась
        messages.error(request, 'Не удалось выполнить вход автоматически. Войдите вручную.')
        return redirect('home')

    # GET
    return render(request, 'register.html')


def login_view(request):
    """Простой вход пользователя по email (username == email)."""
    if request.method == 'POST':
        email = request.POST.get('email', '').strip().lower()
        password = request.POST.get('password', '')

        if is_login_rate_limited(request, email):
            return render(
                request,
                'login.html',
                {
                    'error': 'Слишком много неудачных попыток входа. Попробуйте снова позже.',
                    'email': email,
                },
                status=429,
            )

        user = authenticate(request, username=email, password=password)
        if user is not None:
            clear_failed_login_attempts(request, email)
            login(request, user)
            messages.success(request, 'Вы успешно вошли в систему')
            return redirect('profile')
        else:
            register_failed_login_attempt(request, email)
            return render(request, 'login.html', {'error': 'Неверный email или пароль', 'email': email})

    return render(request, 'login.html')


from django.contrib.auth import logout


def logout_view(request):
    logout(request)
    messages.info(request, 'Вы вышли из аккаунта')
    return redirect('home')


from django.contrib.auth.decorators import login_required


@login_required
def create_room_view(request):
    """Создание новой комнаты пользователем."""
    if request.method == 'POST':
        room_name = request.POST.get('room_name', '').strip()
        room_description = request.POST.get('room_description', '').strip()
        
        if not room_name:
            messages.error(request, 'Пожалуйста, введите название комнаты')
            return redirect('create-room')
        
        # Генерируем уникальный код
        code = RoomViewSet.generate_room_code()
        
        # Создаем комнату
        room = Room.objects.create(
            name=room_name,
            description=room_description,
            owner=request.user,
            code=code
        )
        
        # Добавляем владельца как администратора
        RoomMember.objects.create(room=room, user=request.user, is_admin=True)
        
        messages.success(request, f'Комната "{room_name}" создана! Код: {code}')
        return redirect('dashboard-room', room_id=room.id)
    
    return render(request, 'create_room.html')


@login_required
def join_room_view(request):
    """Присоединение к комнате по коду."""
    if request.method == 'POST':
        room_code = request.POST.get('room_code', '').strip().upper()
        
        if not room_code:
            messages.error(request, 'Пожалуйста, введите код комнаты')
            return redirect('join-room')
        
        try:
            room = Room.objects.get(code=room_code)
        except Room.DoesNotExist:
            messages.error(request, 'Комната с таким кодом не найдена')
            return redirect('join-room')
        
        # Проверяем, не участник ли уже
        if room.members.filter(user=request.user).exists():
            messages.info(request, 'Вы уже участник этой комнаты')
            return redirect('dashboard-room', room_id=room.id)
        
        # Добавляем как участника
        RoomMember.objects.create(room=room, user=request.user, is_admin=False)
        messages.success(request, f'Вы присоединились к комнате "{room.name}"!')
        return redirect('dashboard-room', room_id=room.id)
    
    return render(request, 'join_room.html')



@login_required
def dashboard_view(request, room_id=None):
    """Панель управления комнатой."""
    user = request.user
    
    # Получить все комнаты пользователя
    rooms = Room.objects.filter(Q(owner=user) | Q(members__user=user)).distinct()
    
    # Если нет комнат
    if not rooms.exists():
        return render(request, 'no_rooms.html')
    
    # Если room_id не указан, используем первую комнату
    if room_id is None:
        room = rooms.first()
    else:
        try:
            room = rooms.get(id=room_id)
        except Room.DoesNotExist:
            return render(request, 'no_rooms.html')
    
    return render(request, 'dashboard.html', {
        'room': room,
        'rooms': rooms,
        'is_owner': room.owner == user,
        'members': room.members.select_related('user', 'user__profile').all(),
    })


@login_required
def profile_view(request):
    """Личный кабинет пользователя: информация, комнаты, смена пароля."""
    user = request.user
    profile, _ = UserProfile.objects.get_or_create(user=user)
    # Комнаты где владелец или участник
    rooms = Room.objects.filter(Q(owner=user) | Q(members__user=user)).distinct()

    change_success = None
    info_success = None
    avatar_success = None

    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'change_password':
            current = request.POST.get('current_password', '')
            newp = request.POST.get('new_password', '')
            confirm = request.POST.get('confirm_password', '')
            if not user.check_password(current):
                messages.error(request, 'Текущий пароль неверен')
            elif newp != confirm:
                messages.error(request, 'Новые пароли не совпадают')
            else:
                try:
                    validate_password(newp, user=user)
                except ValidationError as exc:
                    for message in exc.messages:
                        messages.error(request, message)
                else:
                    user.set_password(newp)
                    user.save()
                    # Переаутентифицируем
                    user = authenticate(request, username=user.username, password=newp)
                    if user:
                        login(request, user)
                    change_success = True
        elif action == 'update_info':
            full_name = request.POST.get('full_name', '').strip()
            email = request.POST.get('email', '').strip().lower()
            if full_name:
                user.first_name = full_name.split(' ', 1)[0]
                user.last_name = full_name.split(' ', 1)[1] if ' ' in full_name else ''
            if email:
                if User.objects.exclude(pk=user.pk).filter(username=email).exists():
                    messages.error(request, 'Пользователь с таким email уже существует')
                    return render(request, 'profile.html', {
                        'user_obj': user,
                        'profile': profile,
                        'rooms': rooms,
                        'change_success': change_success,
                        'info_success': info_success,
                        'avatar_success': avatar_success,
                    })
                user.email = email
                user.username = email
            user.save()
            info_success = True
        elif action == 'upload_avatar':
            avatar = request.FILES.get('avatar')
            if avatar:
                try:
                    validate_avatar_upload(avatar)
                except ValidationError as exc:
                    for message in exc.messages:
                        messages.error(request, message)
                else:
                    profile.avatar = avatar
                    profile.save()
                    avatar_success = True

    return render(request, 'profile.html', {
        'user_obj': user,
        'profile': profile,
        'rooms': rooms,
        'change_success': change_success,
        'info_success': info_success,
        'avatar_success': avatar_success,
    })
