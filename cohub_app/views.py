from collections import defaultdict

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

from .models import Room, RoomMember, Task, TaskReassignmentRequest, Expense, ExpenseShare, UserProfile, ChatMessage, DebtSettlement, Loan, LoanPayment, Subscription
from .serializers import (
    RoomSerializer, RoomMemberSerializer, TaskSerializer, TaskReassignmentRequestSerializer,
    ExpenseSerializer, ExpenseShareSerializer, UserSerializer, ChatMessageSerializer,
    LoanSerializer, LoanPaymentSerializer, SubscriptionSerializer,
)
from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.auth import authenticate, login
from django.utils.text import slugify
from datetime import timedelta, datetime
from django.utils import timezone
from rest_framework.views import APIView
from django.http import JsonResponse, HttpResponse
import csv


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


def get_user_display_name(user):
    return user.get_full_name() or user.username


PARTICIPANT_MOOD_MAP = {
    'great': {
        'label': 'На подъёме',
        'emoji': '😄',
        'message': 'Полон(а) энергии и готов(а) быстро закрывать бытовые дела.',
    },
    'calm': {
        'label': 'Спокойно',
        'emoji': '🙂',
        'message': 'Спокойный режим: всё под контролем, можно идти в обычном темпе.',
    },
    'focus': {
        'label': 'Нужен фокус',
        'emoji': '🤔',
        'message': 'Лучше не отвлекать без необходимости — сейчас хочется сосредоточиться.',
    },
    'tired': {
        'label': 'Нужна пауза',
        'emoji': '😴',
        'message': 'Сил сегодня меньше обычного, поэтому нужен более мягкий темп.',
    },
}


def build_participant_mood_context(room, viewer=None, members=None):
    members = list(members or room.members.select_related('user', 'user__profile').all())
    participant_moods = []
    shared_people = []
    mood_counts = defaultdict(int)

    for member in members:
        profile = getattr(member.user, 'profile', None)
        mood_key = (getattr(profile, 'mood_key', '') or 'calm').strip().lower()
        mood_meta = PARTICIPANT_MOOD_MAP.get(mood_key, PARTICIPANT_MOOD_MAP['calm'])
        mood_note = (getattr(profile, 'mood_note', '') or '').strip()
        mood_updated_at = getattr(profile, 'mood_updated_at', None)
        has_shared = mood_updated_at is not None
        display_name = get_user_display_name(member.user)

        if has_shared:
            mood_counts[mood_key] += 1
            shared_people.append(f"{mood_meta['emoji']} {display_name}")

        participant_moods.append({
            'user_id': member.user_id,
            'username': member.user.username,
            'name': display_name,
            'is_me': viewer is not None and member.user_id == getattr(viewer, 'id', None),
            'mood_key': mood_key if has_shared else 'unknown',
            'label': mood_meta['label'] if has_shared else 'Пока без статуса',
            'emoji': mood_meta['emoji'] if has_shared else '🫥',
            'message': mood_meta['message'] if has_shared else 'Участник ещё не поделился своим текущим настроением.',
            'note': mood_note,
            'updated_text': (
                f"Обновлено {timezone.localtime(mood_updated_at).strftime('%d.%m в %H:%M')}"
                if mood_updated_at else 'Статус пока не выбран'
            ),
        })

    if mood_counts:
        dominant_key = max(mood_counts.items(), key=lambda item: (item[1], item[0]))[0]
        visible_people = ', '.join(shared_people[:3])
        extra_count = max(len(shared_people) - 3, 0)
        if extra_count:
            visible_people += f' и ещё {extra_count}'
        if len(shared_people) < len(members):
            visible_people += '. Остальные пока без статуса.'

        mood_overview = {
            'key': dominant_key,
            'label': 'Настроение участников',
            'message': visible_people,
        }
    else:
        mood_overview = {
            'key': 'calm',
            'label': 'Настроение участников',
            'message': 'Пока никто не отметил своё состояние. Ниже можно выбрать личный статус, и его увидят все участники комнаты.',
        }

    return participant_moods, mood_overview


def create_task_reassignment_chat_message(task_request, action, actor=None):
    actor = actor or task_request.requested_by
    requester_name = get_user_display_name(task_request.requested_by)
    requested_to_name = get_user_display_name(task_request.requested_to)
    task_title = task_request.task.title
    reason_label = task_request.get_reason_display()
    custom_message = (task_request.custom_message or '').strip()
    response_note = (task_request.response_note or '').strip()

    if action == 'created':
        text = (
            f'🔁 {requester_name} просит передать задачу "{task_title}" участнику '
            f'{requested_to_name}. Причина: {reason_label}.'
        )
        if custom_message:
            text += f' Комментарий: {custom_message}'
    elif action == 'accepted':
        text = f'✅ {requested_to_name} принял(а) задачу "{task_title}" и теперь отвечает за неё.'
        if response_note:
            text += f' Ответ: {response_note}'
    elif action == 'declined':
        text = f'❌ {requested_to_name} отклонил(а) запрос по задаче "{task_title}".'
        if response_note:
            text += f' Ответ: {response_note}'
    elif action == 'cancelled':
        text = f'↩️ {requester_name} отменил(а) запрос на передачу задачи "{task_title}".'
        if response_note:
            text += f' Комментарий: {response_note}'
    else:
        text = f'ℹ️ Запрос на передачу задачи "{task_title}" был закрыт.'

    ChatMessage.objects.create(
        room=task_request.room,
        author=actor,
        text=text,
    )


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

        manual_loans_payload = []
        loan_notifications = []
        today = timezone.localdate()
        for loan in room.loans.select_related('lender', 'borrower').all():
            remaining_amount = loan.refresh_status(save=True)
            debtor_id = loan.borrower_id
            creditor_id = loan.lender_id

            if remaining_amount > Decimal('0'):
                user_balances[debtor_id] = user_balances.get(debtor_id, Decimal('0')) - remaining_amount
                user_balances[creditor_id] = user_balances.get(creditor_id, Decimal('0')) + remaining_amount

                pair = (debtor_id, creditor_id)
                debts_map[pair] = debts_map.get(pair, Decimal('0')) + remaining_amount

            manual_loans_payload.append({
                'id': str(loan.id),
                'from_user_id': debtor_id,
                'from_name': user_display.get(debtor_id, str(debtor_id)),
                'to_user_id': creditor_id,
                'to_name': user_display.get(creditor_id, str(creditor_id)),
                'amount_total': float(loan.amount_total),
                'amount_returned': float(loan.amount_returned),
                'remaining_amount': float(remaining_amount),
                'amount': float(remaining_amount),
                'status': loan.status,
                'due_date': loan.due_date.isoformat() if loan.due_date else None,
                'note': loan.note,
                'is_overdue': loan.is_overdue,
                'reminder_count': loan.reminder_count,
            })

            if remaining_amount > Decimal('0') and loan.due_date:
                days_delta = (loan.due_date - today).days
                if days_delta < 0:
                    loan_notifications.append(
                        f'Долг {user_display.get(debtor_id, str(debtor_id))} → {user_display.get(creditor_id, str(creditor_id))} просрочен на {abs(days_delta)} дн.'
                    )
                elif days_delta <= 1:
                    due_word = 'сегодня' if days_delta == 0 else 'завтра'
                    loan_notifications.append(
                        f'Возврат долга {user_display.get(debtor_id, str(debtor_id))} → {user_display.get(creditor_id, str(creditor_id))} ожидается {due_word}.'
                    )

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

        loan_payment_queryset = LoanPayment.objects.filter(loan__room=room).select_related('loan__borrower', 'loan__lender', 'paid_by')
        total_loan_payments = loan_payment_queryset.aggregate(total=Sum('amount'))['total'] or Decimal('0')
        total_debt_settlements = room.debt_settlements.aggregate(total=Sum('amount'))['total'] or Decimal('0')
        total_payment_count = loan_payment_queryset.count() + room.debt_settlements.count()
        total_paid_amount = total_loan_payments + total_debt_settlements

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

        for payment in loan_payment_queryset[:8]:
            recent_settlements.append({
                'id': str(payment.id),
                'from_user_id': payment.loan.borrower_id,
                'from_name': payment.loan.borrower.get_full_name() or payment.loan.borrower.username,
                'to_user_id': payment.loan.lender_id,
                'to_name': payment.loan.lender.get_full_name() or payment.loan.lender.username,
                'amount': float(payment.amount),
                'settled_by': payment.paid_by.get_full_name() or payment.paid_by.username,
                'settled_at': payment.paid_at.isoformat(),
            })

        recent_settlements.sort(key=lambda item: item['settled_at'], reverse=True)
        recent_settlements = recent_settlements[:8]

        payment_insights = {
            'total_paid_amount': float(total_paid_amount),
            'settlement_count': total_payment_count,
            'loan_payment_total': float(total_loan_payments),
            'debt_settlement_total': float(total_debt_settlements),
            'recent_payments': recent_settlements,
        }

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
            'manual_loans': manual_loans_payload,
            'loan_notifications': loan_notifications,
            'recent_settlements': recent_settlements,
            'payment_insights': payment_insights,
        })

    @action(detail=True, methods=['post'])
    def clear_debt_history(self, request, pk=None):
        """Очищает историю погашений по комнате, не затрагивая активные долги."""
        room = self.get_object()

        if not (room.owner == request.user or room.members.filter(user=request.user).exists()):
            return Response({'error': 'Нет доступа к истории долгов этой комнаты'}, status=status.HTTP_403_FORBIDDEN)

        deleted_settlements, _ = DebtSettlement.objects.filter(room=room).delete()
        deleted_payments, _ = LoanPayment.objects.filter(loan__room=room).delete()

        deleted_closed_loans = 0
        for loan in room.loans.all():
            if loan.refresh_status(save=True) <= Decimal('0'):
                loan.delete()
                deleted_closed_loans += 1

        return Response({
            'deleted_settlements': deleted_settlements,
            'deleted_payments': deleted_payments,
            'deleted_closed_loans': deleted_closed_loans,
        })

    @action(detail=True, methods=['post'])
    def update_my_mood(self, request, pk=None):
        """Сохраняет личное настроение участника, видимое всей комнате."""
        room = self.get_object()

        if not (room.owner == request.user or room.members.filter(user=request.user).exists()):
            return Response({'error': 'Нет доступа к этой комнате'}, status=status.HTTP_403_FORBIDDEN)

        mood_key = (request.data.get('mood_key') or '').strip().lower()
        mood_note = (request.data.get('mood_note') or '').strip()

        if mood_key not in PARTICIPANT_MOOD_MAP:
            return Response({'error': 'Неизвестный вариант настроения'}, status=status.HTTP_400_BAD_REQUEST)
        if len(mood_note) > 120:
            return Response({'error': 'Комментарий к настроению должен быть не длиннее 120 символов'}, status=status.HTTP_400_BAD_REQUEST)

        profile, _ = UserProfile.objects.get_or_create(user=request.user)
        profile.mood_key = mood_key
        profile.mood_note = mood_note
        profile.mood_updated_at = timezone.now()
        profile.save(update_fields=['mood_key', 'mood_note', 'mood_updated_at'])

        participant_moods, mood_overview = build_participant_mood_context(room, viewer=request.user)
        return Response({
            'message': 'Ваше настроение сохранено и видно участникам комнаты',
            'mood': {
                'key': mood_key,
                'label': PARTICIPANT_MOOD_MAP[mood_key]['label'],
                'emoji': PARTICIPANT_MOOD_MAP[mood_key]['emoji'],
                'note': mood_note,
            },
            'participant_moods': participant_moods,
            'mood_overview': mood_overview,
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


class TaskReassignmentRequestViewSet(viewsets.ModelViewSet):
    """Запросы на передачу задач между участниками комнаты."""

    queryset = TaskReassignmentRequest.objects.all()
    serializer_class = TaskReassignmentRequestSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ['get', 'post', 'head', 'options']

    def get_queryset(self):
        user = self.request.user
        rooms = Room.objects.filter(
            Q(owner=user) | Q(members__user=user)
        ).values_list('id', flat=True)
        queryset = TaskReassignmentRequest.objects.filter(room__id__in=rooms)

        room_id = self.request.query_params.get('room')
        status_filter = self.request.query_params.get('status')
        scope = self.request.query_params.get('scope')

        if room_id:
            queryset = queryset.filter(room_id=room_id)
        if status_filter:
            queryset = queryset.filter(status=status_filter)

        if scope == 'incoming':
            queryset = queryset.filter(requested_to=user)
        elif scope == 'outgoing':
            queryset = queryset.filter(requested_by=user)
        else:
            queryset = queryset.filter(
                Q(requested_by=user) | Q(requested_to=user) | Q(room__owner=user)
            ).distinct()

        return queryset.select_related(
            'room', 'task', 'task__assigned_to', 'task__created_by', 'requested_by', 'requested_to'
        )

    def perform_create(self, serializer):
        task_request = serializer.save()
        create_task_reassignment_chat_message(task_request, 'created', actor=self.request.user)

    @action(detail=True, methods=['post'])
    def accept(self, request, pk=None):
        task_request = self.get_object()

        if request.user != task_request.requested_to:
            return Response({'error': 'Принять запрос может только указанный участник'}, status=status.HTTP_403_FORBIDDEN)
        if task_request.status != 'pending':
            return Response({'error': 'Этот запрос уже обработан'}, status=status.HTTP_400_BAD_REQUEST)
        if task_request.task.status == 'completed':
            return Response({'error': 'Задача уже выполнена и не требует передачи'}, status=status.HTTP_400_BAD_REQUEST)

        response_note = (request.data.get('response_note') or '').strip()
        now = timezone.now()

        task_request.status = 'accepted'
        task_request.response_note = response_note
        task_request.responded_at = now
        task_request.save(update_fields=['status', 'response_note', 'responded_at', 'updated_at'])

        task = task_request.task
        task.assigned_to = task_request.requested_to
        task.save(update_fields=['assigned_to', 'updated_at'])

        TaskReassignmentRequest.objects.filter(task=task, status='pending').exclude(id=task_request.id).update(
            status='cancelled',
            responded_at=now,
            response_note='Закрыто после принятия другого запроса',
        )

        create_task_reassignment_chat_message(task_request, 'accepted', actor=request.user)
        return Response(self.get_serializer(task_request).data)

    @action(detail=True, methods=['post'])
    def decline(self, request, pk=None):
        task_request = self.get_object()

        if request.user != task_request.requested_to:
            return Response({'error': 'Отклонить запрос может только указанный участник'}, status=status.HTTP_403_FORBIDDEN)
        if task_request.status != 'pending':
            return Response({'error': 'Этот запрос уже обработан'}, status=status.HTTP_400_BAD_REQUEST)

        task_request.status = 'declined'
        task_request.response_note = (request.data.get('response_note') or '').strip()
        task_request.responded_at = timezone.now()
        task_request.save(update_fields=['status', 'response_note', 'responded_at', 'updated_at'])

        create_task_reassignment_chat_message(task_request, 'declined', actor=request.user)
        return Response(self.get_serializer(task_request).data)

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        task_request = self.get_object()

        if request.user not in {task_request.requested_by, task_request.room.owner}:
            return Response({'error': 'Отменить запрос может только отправитель или владелец комнаты'}, status=status.HTTP_403_FORBIDDEN)
        if task_request.status != 'pending':
            return Response({'error': 'Можно отменить только активный запрос'}, status=status.HTTP_400_BAD_REQUEST)

        task_request.status = 'cancelled'
        task_request.response_note = (request.data.get('response_note') or '').strip()
        task_request.responded_at = timezone.now()
        task_request.save(update_fields=['status', 'response_note', 'responded_at', 'updated_at'])

        create_task_reassignment_chat_message(task_request, 'cancelled', actor=request.user)
        return Response(self.get_serializer(task_request).data)

    @action(detail=False, methods=['post'])
    def clear_history(self, request):
        room_id = request.data.get('room') or request.query_params.get('room')
        if not room_id:
            return Response({'error': 'Не указана комната'}, status=status.HTTP_400_BAD_REQUEST)

        room = get_object_or_404(Room, id=room_id)
        is_member = room.owner_id == request.user.id or room.members.filter(user=request.user).exists()
        if not is_member:
            return Response({'error': 'У вас нет доступа к этой комнате'}, status=status.HTTP_403_FORBIDDEN)

        history_qs = self.get_queryset().filter(room=room).exclude(status='pending')
        deleted_count = history_qs.count()
        if deleted_count:
            history_qs.delete()

        return Response({
            'deleted_count': deleted_count,
            'message': 'История запросов очищена' if deleted_count else 'История уже пустая',
        })


class TeacherMetricsView(APIView):
    """Возвращает агрегированные метрики для учителя или экспорт в CSV.

    Если передан параметр `room`, проверяется доступ к комнате (владелец/участник).
    Если `room` отсутствует, доступ разрешён только staff/superuser.
    Поддерживает `?format=csv` для скачивания CSV.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        room_id = request.query_params.get('room')
        format_ = (request.query_params.get('format') or '').lower()

        # Доступ
        if room_id:
            try:
                room = Room.objects.get(id=room_id)
            except Room.DoesNotExist:
                return Response({'error': 'Комната не найдена'}, status=status.HTTP_404_NOT_FOUND)

            is_member = room.owner_id == request.user.id or room.members.filter(user=request.user).exists()
            if not is_member and not request.user.is_staff:
                return Response({'error': 'Нет доступа к метрикам этой комнаты'}, status=status.HTTP_403_FORBIDDEN)
        else:
            if not (request.user.is_staff or request.user.is_superuser):
                return Response({'error': 'Только преподаватель/админ может запрашивать глобальные метрики'}, status=status.HTTP_403_FORBIDDEN)

        days = 30
        period_start = timezone.localdate() - timedelta(days=days - 1)

        # Базовые агрегаты
        rooms_qs = Room.objects.all() if (request.user.is_staff or request.user.is_superuser) and not room_id else Room.objects.filter(id=room_id)
        total_rooms = rooms_qs.count()
        total_users = User.objects.count()
        active_users_30d = User.objects.filter(last_login__date__gte=period_start).count()

        expenses_qs = Expense.objects.filter(date__gte=period_start)
        if room_id:
            expenses_qs = expenses_qs.filter(room_id=room_id)

        total_expenses = expenses_qs.aggregate(total=Sum('amount'))['total'] or Decimal('0')

        # Топ категорий
        top_categories = list(
            expenses_qs.values('category').annotate(total=Sum('amount')).order_by('-total')[:6]
        )

        # Тренд по дням
        trend_qs = expenses_qs.values('date').annotate(total=Sum('amount')).order_by('date')
        trend_by_day = []
        # build map for last N days to ensure zeros
        trend_map = {row['date'].isoformat(): float(row['total']) for row in trend_qs}
        for i in range(days):
            d = period_start + timedelta(days=i)
            trend_by_day.append({'date': d.isoformat(), 'total': float(trend_map.get(d.isoformat(), 0))})

        # Задачи завершённые за период
        tasks_qs = Task.objects.filter(completed_at__date__gte=period_start)
        if room_id:
            tasks_qs = tasks_qs.filter(room_id=room_id)
        tasks_completed = tasks_qs.count()

        payload = {
            'rooms_count': total_rooms,
            'total_users': total_users,
            'active_users_30d': active_users_30d,
            'tasks_completed_last_30d': tasks_completed,
            'total_expenses': float(total_expenses),
            'avg_expense_per_person': float(total_expenses) / (rooms_qs.first().members.count() or 1) if room_id and rooms_qs.exists() else None,
            'top_categories': top_categories,
            'expenses_trend': trend_by_day,
        }

        if format_ == 'csv':
            # Формируем CSV — первая часть: общие метрики, затем топ категорий и тренд
            filename = f"metrics_{room_id or 'global'}_{datetime.now().strftime('%Y%m%d')}.csv"
            response = HttpResponse(content_type='text/csv')
            response['Content-Disposition'] = f'attachment; filename="{filename}"'
            writer = csv.writer(response)
            writer.writerow(['Metric', 'Value'])
            writer.writerow(['rooms_count', payload['rooms_count']])
            writer.writerow(['total_users', payload['total_users']])
            writer.writerow(['active_users_30d', payload['active_users_30d']])
            writer.writerow(['tasks_completed_last_30d', payload['tasks_completed_last_30d']])
            writer.writerow(['total_expenses', payload['total_expenses']])
            writer.writerow(['avg_expense_per_person', payload['avg_expense_per_person'] or ''])
            writer.writerow([])
            writer.writerow(['Top categories', 'Total'])
            for cat in payload['top_categories']:
                writer.writerow([cat.get('category'), float(cat.get('total') or 0)])
            writer.writerow([])
            writer.writerow(['Date', 'Expenses'])
            for row in payload['expenses_trend']:
                writer.writerow([row['date'], row['total']])
            return response

        return Response(payload)


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

        return queryset.select_related('assigned_to', 'created_by', 'room').prefetch_related('reassignment_requests')
    
    def perform_create(self, serializer):
        """Создает задачу с текущим пользователем"""
        serializer.save(created_by=self.request.user)
    
    @action(detail=True, methods=['post'])
    def complete(self, request, pk=None):
        """Отметить задачу как завершенную"""
        task = self.get_object()

        if task.status == 'completed':
            return Response({'error': 'Задача уже завершена'}, status=status.HTTP_400_BAD_REQUEST)

        if not task.can_be_completed_by(request.user):
            return Response(
                {'error': 'После передачи завершить задачу может только тот участник, у которого она сейчас находится'},
                status=status.HTTP_403_FORBIDDEN,
            )

        task.status = 'completed'
        task.completed_at = timezone.now()
        task.save(update_fields=['status', 'completed_at', 'updated_at'])
        TaskReassignmentRequest.objects.filter(task=task, status='pending').update(
            status='cancelled',
            responded_at=timezone.now(),
            response_note='Запрос закрыт, потому что задача уже выполнена.',
        )
        serializer = self.get_serializer(task)
        return Response(serializer.data)


class ExpenseViewSet(viewsets.ModelViewSet):
    """ViewSet для управления расходами"""
    queryset = Expense.objects.all()
    serializer_class = ExpenseSerializer
    permission_classes = [IsAuthenticated]

    @staticmethod
    def _as_bool(value):
        if isinstance(value, bool):
            return value
        if value is None:
            return False
        return str(value).strip().lower() in {'1', 'true', 'yes', 'on', 'y'}
    
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
        mark_as_paid = self._as_bool(self.request.data.get('mark_as_paid'))
        expense = serializer.save()

        if expense.is_shared and expense.paid_by_id is not None:
            expense.paid_by = None
            expense.save(update_fields=['paid_by', 'updated_at'])
        
        # Автоматически распределяем расход на всех участников комнаты поровну
        room = expense.room
        members = room.members.all()
        if members.exists():
            share_amount = expense.amount / members.count()
            for member in members:
                ExpenseShare.objects.create(
                    expense=expense,
                    user=member.user,
                    amount=share_amount,
                    is_settled=mark_as_paid,
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


class LoanViewSet(viewsets.ModelViewSet):
    """Ручные долги между участниками комнаты."""

    queryset = Loan.objects.all()
    serializer_class = LoanSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        rooms = Room.objects.filter(
            Q(owner=user) | Q(members__user=user)
        ).values_list('id', flat=True)
        queryset = Loan.objects.filter(room__id__in=rooms).select_related('room', 'lender', 'borrower', 'created_by')

        room_id = self.request.query_params.get('room')
        if room_id:
            queryset = queryset.filter(room_id=room_id)

        return queryset

    def perform_create(self, serializer):
        loan = serializer.save(created_by=self.request.user)
        loan.refresh_status(save=True)

    @action(detail=True, methods=['post'])
    def send_reminder(self, request, pk=None):
        loan = self.get_object()
        if loan.remaining_amount <= Decimal('0'):
            return Response({'error': 'Этот долг уже закрыт'}, status=status.HTTP_400_BAD_REQUEST)

        if request.user not in {loan.lender, loan.room.owner}:
            return Response({'error': 'Напоминание может отправить только кредитор или владелец комнаты'}, status=status.HTTP_403_FORBIDDEN)

        loan.last_reminder_sent_at = timezone.now()
        loan.reminder_count += 1
        loan.save(update_fields=['last_reminder_sent_at', 'reminder_count', 'updated_at'])

        borrower_name = loan.borrower.get_full_name() or loan.borrower.username
        return Response({
            'loan_id': str(loan.id),
            'message': f'Напоминание для {borrower_name} отмечено. Напоминаний: {loan.reminder_count}.',
            'reminder_count': loan.reminder_count,
        })


class LoanPaymentViewSet(viewsets.ModelViewSet):
    """Частичные и полные возвраты по ручным долгам."""

    queryset = LoanPayment.objects.all()
    serializer_class = LoanPaymentSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ['get', 'post', 'head', 'options']

    def get_queryset(self):
        user = self.request.user
        rooms = Room.objects.filter(
            Q(owner=user) | Q(members__user=user)
        ).values_list('id', flat=True)
        queryset = LoanPayment.objects.filter(loan__room__id__in=rooms).select_related('loan', 'loan__borrower', 'loan__lender', 'paid_by')

        loan_id = self.request.query_params.get('loan')
        if loan_id:
            queryset = queryset.filter(loan_id=loan_id)

        return queryset

    def perform_create(self, serializer):
        serializer.save()


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


class SubscriptionViewSet(viewsets.ViewSet):
    """ViewSet для управления подписками пользователей"""
    permission_classes = [IsAuthenticated]
    serializer_class = SubscriptionSerializer

    def list(self, request):
        """Получить информацию о подписке текущего пользователя"""
        try:
            subscription = request.user.subscription
        except Subscription.DoesNotExist:
            # Создаем подписку если её нет
            subscription = Subscription.objects.create(user=request.user)
            subscription.start_trial(trial_days=7)
        
        serializer = self.serializer_class(subscription)
        return Response(serializer.data)

    def retrieve(self, request, pk=None):
        """Получить информацию о подписке (алиас для list)"""
        return self.list(request)

    @action(detail=False, methods=['post'])
    def activate(self, request):
        """Активировать платную подписку (симуляция оплаты)"""
        try:
            subscription = request.user.subscription
        except Subscription.DoesNotExist:
            return Response({'error': 'Подписка не найдена'}, status=status.HTTP_404_NOT_FOUND)
        
        months = int(request.data.get('months', 1))
        if months < 1 or months > 12:
            return Response({'error': 'Количество месяцев должно быть от 1 до 12'}, status=status.HTTP_400_BAD_REQUEST)
        
        subscription.activate_paid(months=months)
        
        return Response({
            'message': f'Подписка активирована на {months} мес.',
            'paid_end': subscription.paid_end.isoformat() if subscription.paid_end else None,
            'days_remaining': subscription.days_remaining,
        })

    @action(detail=False, methods=['post'])
    def cancel(self, request):
        """Отменить подписку"""
        try:
            subscription = request.user.subscription
        except Subscription.DoesNotExist:
            return Response({'error': 'Подписка не найдена'}, status=status.HTTP_404_NOT_FOUND)
        
        subscription.cancel()
        
        return Response({
            'message': 'Подписка отменена',
            'status': subscription.get_status_display(),
        })

    @action(detail=False, methods=['get'])
    def check(self, request):
        """Проверить статус подписки"""
        try:
            subscription = request.user.subscription
        except Subscription.DoesNotExist:
            return Response({
                'is_active': False,
                'status': 'no_subscription',
                'message': 'Подписка не найдена',
            })
        
        return Response({
            'is_active': subscription.is_active,
            'status': subscription.status,
            'status_display': subscription.get_status_display(),
            'days_remaining': subscription.days_remaining,
            'trial_days_remaining': subscription.trial_days_remaining,
            'paid_end': subscription.paid_end.isoformat() if subscription.paid_end else None,
        })


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
    next_url = (request.POST.get('next') or request.GET.get('next') or '').strip()

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
                    'next': next_url,
                },
                status=429,
            )

        user = authenticate(request, username=email, password=password)
        if user is not None:
            clear_failed_login_attempts(request, email)
            login(request, user)
            messages.success(request, 'Вы успешно вошли в систему')
            if next_url.startswith('/'):
                return redirect(next_url)
            return redirect('dashboard')
        else:
            register_failed_login_attempt(request, email)
            return render(request, 'login.html', {
                'error': 'Неверный email или пароль',
                'email': email,
                'next': next_url,
            })

    return render(request, 'login.html', {'next': next_url})


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



def build_dashboard_insights_preview(room):
    """Короткие инсайты комнаты для первого экрана на dashboard."""
    members = list(room.members.select_related('user', 'user__profile').all())
    member_names = {
        member.user_id: (member.user.get_full_name() or member.user.username)
        for member in members
    }
    _, mood_overview = build_participant_mood_context(room, members=members)

    tasks = list(room.tasks.select_related('assigned_to').all())
    expenses = list(room.expenses.select_related('paid_by').all())
    total_tasks = len(tasks)
    completed_tasks = sum(1 for task in tasks if task.status == 'completed')
    pending_tasks = sum(1 for task in tasks if task.status != 'completed')
    high_priority_pending = sum(1 for task in tasks if task.status != 'completed' and task.priority == 'high')
    unassigned_tasks = sum(1 for task in tasks if task.status != 'completed' and not task.assigned_to_id)
    completion_rate = int(round((completed_tasks / total_tasks) * 100)) if total_tasks else 0

    completed_totals = defaultdict(int)
    payment_totals = defaultdict(lambda: Decimal('0'))
    for task in tasks:
        if task.assigned_to_id and task.status == 'completed':
            completed_totals[task.assigned_to_id] += 1

    for expense in expenses:
        if expense.paid_by_id:
            payment_totals[expense.paid_by_id] += expense.amount or Decimal('0')

    month_start = timezone.localdate().replace(day=1)
    expense_pool = [expense for expense in expenses if expense.date >= month_start] or expenses
    expense_total = sum((expense.amount or Decimal('0')) for expense in expense_pool)
    category_totals = defaultdict(lambda: Decimal('0'))
    for expense in expense_pool:
        category_totals[(expense.category or 'Прочее').strip() or 'Прочее'] += expense.amount or Decimal('0')

    open_shares = list(
        ExpenseShare.objects.filter(
            expense__room=room,
            is_settled=False,
            expense__paid_by__isnull=False,
        ).select_related('user', 'expense__paid_by')
    )
    open_debt_amount = sum((share.amount or Decimal('0')) for share in open_shares)

    open_loan_amount = Decimal('0')
    open_loan_count = 0
    overdue_loan_count = 0
    for loan in room.loans.select_related('borrower', 'lender').all():
        remaining_amount = loan.refresh_status(save=True)
        if remaining_amount > 0:
            open_loan_amount += remaining_amount
            open_loan_count += 1
        if loan.is_overdue:
            overdue_loan_count += 1

    top_cleaner = max(completed_totals.items(), key=lambda item: item[1], default=(None, 0))
    top_budget = max(payment_totals.items(), key=lambda item: item[1], default=(None, Decimal('0')))

    achievements = [
        {
            'icon': '🏆',
            'title': 'Чистюля недели',
            'winner': member_names.get(top_cleaner[0], 'Команда набирает темп'),
            'description': (
                f'Закрыто задач: {top_cleaner[1]}'
                if top_cleaner[0] and top_cleaner[1] > 0
                else 'Станет видно, кто быстрее всех закрывает бытовые дела.'
            ),
        },
        {
            'icon': '💸',
            'title': 'Опора бюджета',
            'winner': member_names.get(top_budget[0], 'Общий баланс'),
            'description': (
                f'Больше всех оплатил(а): {float(top_budget[1]):.0f}₸'
                if top_budget[0] and top_budget[1] > 0
                else 'Пока траты небольшие — бюджет выглядит спокойно.'
            ),
        },
    ]

    reminders = []
    if high_priority_pending:
        reminders.append(f'Срочных задач в работе: {high_priority_pending}. Лучше закрыть их сегодня.')
    if unassigned_tasks:
        reminders.append(f'Нераспределённых задач: {unassigned_tasks}. Назначьте ответственных.')
    if open_debt_amount > 0 or open_loan_amount > 0:
        reminders.append(f'Незакрытые долги и займы: {float(open_debt_amount + open_loan_amount):.0f}₸.')
    if overdue_loan_count:
        reminders.append(f'Просроченных ручных долгов: {overdue_loan_count}.')
    if expense_total > 0 and category_totals:
        top_category, top_amount = max(category_totals.items(), key=lambda item: item[1])
        top_share = int(round((top_amount / expense_total) * 100)) if expense_total else 0
        if top_share >= 45:
            reminders.append(f'Категория "{top_category}" занимает {top_share}% расходов — её стоит проверить.')
    if not reminders:
        reminders.append('Сейчас всё стабильно: срочных напоминаний для комнаты нет.')

    headline_metrics = [
        {
            'label': 'Выполнение задач',
            'value': f'{completion_rate}%',
            'note': f'{completed_tasks} из {total_tasks} задач уже закрыто',
        },
        {
            'label': 'Расходы за период',
            'value': f'{float(expense_total):.0f}₸',
            'note': 'Текущий месяц' if expense_pool and all(exp.date >= month_start for exp in expense_pool) else 'Все расходы',
        },
        {
            'label': 'Открытые долги',
            'value': f'{float(open_debt_amount + open_loan_amount):.0f}₸',
            'note': f'Незакрытых записей: {len(open_shares) + open_loan_count}',
        },
    ]

    return {
        'headline_metrics': headline_metrics,
        'achievements': achievements,
        'reminders': reminders,
        'mood_overview': mood_overview,
        'pending_tasks': pending_tasks,
    }


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

    insights_preview = build_dashboard_insights_preview(room)
    
    return render(request, 'dashboard.html', {
        'room': room,
        'rooms': rooms,
        'is_owner': room.owner == user,
        'members': room.members.select_related('user', 'user__profile').all(),
        'insights_preview': insights_preview,
        'show_insights_first': True,
        'show_budget_editor': True,
        'budget_button_label': 'Изменить сумму',
    })


@login_required
def room_insights_view(request, room_id):
    """Отдельная страница с достижениями, настроением и обзором комнаты."""
    user = request.user
    rooms = Room.objects.filter(Q(owner=user) | Q(members__user=user)).distinct()

    if not rooms.exists():
        return render(request, 'no_rooms.html')

    try:
        room = rooms.get(id=room_id)
    except Room.DoesNotExist:
        messages.error(request, 'Комната не найдена или недоступна')
        return redirect('dashboard')

    members = list(room.members.select_related('user', 'user__profile').all())
    tasks = list(room.tasks.select_related('assigned_to').all())
    expenses = list(room.expenses.select_related('paid_by').all())
    open_shares = list(
        ExpenseShare.objects.filter(
            expense__room=room,
            is_settled=False,
            expense__paid_by__isnull=False,
        ).select_related('user', 'expense__paid_by')
    )

    member_names = {
        member.user_id: (member.user.get_full_name() or member.user.username)
        for member in members
    }
    participant_moods, mood_overview = build_participant_mood_context(room, viewer=user, members=members)
    current_user_profile, _ = UserProfile.objects.get_or_create(user=user)
    assigned_totals = defaultdict(int)
    completed_totals = defaultdict(int)
    payment_totals = defaultdict(lambda: Decimal('0'))
    finance_profiles = {
        member.user_id: {
            'name': member_names[member.user_id],
            'paid': Decimal('0'),
            'owes': Decimal('0'),
            'owed_to_others': Decimal('0'),
            'loan_given': Decimal('0'),
            'loan_borrowed': Decimal('0'),
            'loan_remaining': Decimal('0'),
            'loan_overdue_count': 0,
        }
        for member in members
    }

    for task in tasks:
        if task.assigned_to_id:
            assigned_totals[task.assigned_to_id] += 1
            if task.status == 'completed':
                completed_totals[task.assigned_to_id] += 1

    for expense in expenses:
        if expense.paid_by_id:
            payment_totals[expense.paid_by_id] += expense.amount or Decimal('0')
            finance_profiles[expense.paid_by_id]['paid'] += expense.amount or Decimal('0')

    for share in open_shares:
        if share.user_id:
            finance_profiles[share.user_id]['owes'] += share.amount or Decimal('0')
        if share.expense and share.expense.paid_by_id:
            finance_profiles[share.expense.paid_by_id]['owed_to_others'] += share.amount or Decimal('0')

    for loan in room.loans.select_related('borrower', 'lender').all():
        finance_profiles[loan.lender_id]['loan_given'] += loan.amount_total or Decimal('0')
        finance_profiles[loan.borrower_id]['loan_borrowed'] += loan.amount_total or Decimal('0')
        remaining_amount = loan.refresh_status(save=True)
        finance_profiles[loan.borrower_id]['loan_remaining'] += remaining_amount
        if loan.is_overdue:
            finance_profiles[loan.borrower_id]['loan_overdue_count'] += 1

    finance_profiles_list = sorted(
        finance_profiles.values(),
        key=lambda profile: profile['paid'],
        reverse=True,
    )

    recent_finance_activity = []
    for settlement in room.debt_settlements.select_related('from_user', 'to_user', 'settled_by').order_by('-settled_at')[:6]:
        recent_finance_activity.append({
            'type': 'settlement',
            'description': f'{settlement.from_user.get_full_name() or settlement.from_user.username} → {settlement.to_user.get_full_name() or settlement.to_user.username}',
            'amount': float(settlement.amount),
            'detail': (settlement.settled_by.get_full_name() or settlement.settled_by.username) if settlement.settled_by else '',
            'date': settlement.settled_at,
        })
    for payment in LoanPayment.objects.filter(loan__room=room).select_related('loan__borrower', 'loan__lender', 'paid_by').order_by('-paid_at')[:6]:
        recent_finance_activity.append({
            'type': 'loan_payment',
            'description': f'{payment.loan.borrower.get_full_name() or payment.loan.borrower.username} → {payment.loan.lender.get_full_name() or payment.loan.lender.username}',
            'amount': float(payment.amount),
            'detail': payment.paid_by.get_full_name() or payment.paid_by.username,
            'date': payment.paid_at,
        })
    recent_finance_activity.sort(key=lambda item: item['date'], reverse=True)
    recent_finance_activity = recent_finance_activity[:6]

    total_tasks = len(tasks)
    completed_tasks = sum(1 for task in tasks if task.status == 'completed')
    pending_tasks = sum(1 for task in tasks if task.status != 'completed')
    high_priority_pending = sum(1 for task in tasks if task.status != 'completed' and task.priority == 'high')
    unassigned_tasks = sum(1 for task in tasks if task.status != 'completed' and not task.assigned_to_id)
    completion_rate = int(round((completed_tasks / total_tasks) * 100)) if total_tasks else 0

    month_start = timezone.localdate().replace(day=1)
    expense_pool = [expense for expense in expenses if expense.date >= month_start] or expenses
    expense_total = sum((expense.amount or Decimal('0')) for expense in expense_pool)
    category_totals = defaultdict(lambda: Decimal('0'))
    for expense in expense_pool:
        category_totals[(expense.category or 'Прочее').strip() or 'Прочее'] += expense.amount or Decimal('0')

    open_debt_amount = sum((share.amount or Decimal('0')) for share in open_shares)
    manual_loans = list(room.loans.select_related('borrower', 'lender').all())
    open_loan_amount = Decimal('0')
    open_loan_count = 0
    overdue_loan_count = 0
    for loan in manual_loans:
        remaining_amount = loan.refresh_status(save=True)
        if remaining_amount > 0:
            open_loan_amount += remaining_amount
            open_loan_count += 1
        if loan.is_overdue:
            overdue_loan_count += 1

    top_cleaner = max(completed_totals.items(), key=lambda item: item[1], default=(None, 0))
    top_budget = max(payment_totals.items(), key=lambda item: item[1], default=(None, Decimal('0')))

    achievements = [
        {
            'icon': '🏆',
            'title': 'Чистюля недели',
            'winner': member_names.get(top_cleaner[0], 'Комната набирает темп'),
            'description': (
                f'Закрыто задач: {top_cleaner[1]}'
                if top_cleaner[0] and top_cleaner[1] > 0
                else 'Как только задачи начнут закрываться, здесь появится герой недели.'
            ),
        },
        {
            'icon': '💸',
            'title': 'Опора бюджета',
            'winner': member_names.get(top_budget[0], 'Общий баланс'),
            'description': (
                f'Больше всего оплатил(а): {float(top_budget[1]):.0f}₸'
                if top_budget[0] and top_budget[1] > 0
                else 'Пока расходов немного — бюджет выглядит спокойно.'
            ),
        },
        {
            'icon': '⚡',
            'title': 'Ритм команды',
            'winner': f'{completion_rate}% задач выполнено',
            'description': 'Отличный темп!' if completion_rate >= 70 else 'Есть куда ускориться, но всё под контролем.',
        },
    ]

    reminders = []
    if high_priority_pending:
        reminders.append(f'Срочных задач в работе: {high_priority_pending}. Лучше закрыть их сегодня.')
    if unassigned_tasks:
        reminders.append(f'Нераспределённых задач: {unassigned_tasks}. Назначьте исполнителей, чтобы не было путаницы.')
    if open_debt_amount > 0 or open_loan_amount > 0:
        reminders.append(f'Незакрытые долги и займы: {float(open_debt_amount + open_loan_amount):.0f}₸. Стоит отметить расчёты в комнате.')
    if overdue_loan_count:
        reminders.append(f'Просроченных ручных долгов: {overdue_loan_count}. Стоит отправить напоминание должникам.')
    if expense_total > 0 and category_totals:
        top_category, top_amount = max(category_totals.items(), key=lambda item: item[1])
        top_share = int(round((top_amount / expense_total) * 100)) if expense_total else 0
        if top_share >= 45:
            reminders.append(f'Категория "{top_category}" занимает {top_share}% расходов. Проверьте, можно ли сократить траты.')
    if not reminders:
        reminders.append('Сейчас всё выглядит стабильно: срочных напоминаний для комнаты нет.')

    member_chart = []
    for member in members:
        total_for_member = assigned_totals.get(member.user_id, 0)
        completed_for_member = completed_totals.get(member.user_id, 0)
        width = int(round((completed_for_member / total_for_member) * 100)) if total_for_member else 0
        member_chart.append({
            'name': member_names.get(member.user_id, str(member.user_id)),
            'completed': completed_for_member,
            'total': total_for_member,
            'width': width,
        })

    expense_chart = []
    for category, total in sorted(category_totals.items(), key=lambda item: item[1], reverse=True)[:5]:
        width = int(round((total / expense_total) * 100)) if expense_total else 0
        expense_chart.append({
            'label': category,
            'value': float(total),
            'width': width,
        })

    headline_metrics = [
        {
            'label': 'Выполнение задач',
            'value': f'{completion_rate}%',
            'note': f'{completed_tasks} из {total_tasks} задач уже закрыто',
        },
        {
            'label': 'Расходы за период',
            'value': f'{float(expense_total):.0f}₸',
            'note': 'Текущий месяц' if expense_pool and all(exp.date >= month_start for exp in expense_pool) else 'Все расходы',
        },
        {
            'label': 'Открытые долги',
            'value': f'{float(open_debt_amount + open_loan_amount):.0f}₸',
            'note': f'Незакрытых записей: {len(open_shares) + open_loan_count}',
        },
    ]

    return render(request, 'room_insights.html', {
        'room': room,
        'rooms': rooms,
        'members': members,
        'is_owner': room.owner == user,
        'achievements': achievements,
        'reminders': reminders,
        'mood_overview': mood_overview,
        'participant_moods': participant_moods,
        'available_moods': [
            {'key': key, 'label': value['label'], 'emoji': value['emoji']}
            for key, value in PARTICIPANT_MOOD_MAP.items()
        ],
        'current_user_mood': {
            'key': (current_user_profile.mood_key or 'calm'),
            'note': current_user_profile.mood_note or '',
        },
        'member_chart': member_chart,
        'expense_chart': expense_chart,
        'headline_metrics': headline_metrics,
        'pending_tasks': pending_tasks,
        'finance_profiles': finance_profiles_list,
        'recent_finance_activity': recent_finance_activity,
        'expense_total': float(expense_total),
        'open_debt_amount': float(open_debt_amount),
        'open_loan_amount': float(open_loan_amount),
        'overdue_loan_count': overdue_loan_count,
        'category_totals': [
            {'label': category, 'value': float(total)}
            for category, total in sorted(category_totals.items(), key=lambda item: item[1], reverse=True)[:6]
        ],
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


@login_required
def subscription_view(request):
    """Страница управления подпиской"""
    return render(request, 'subscription.html')
