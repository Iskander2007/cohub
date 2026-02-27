from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.contrib.auth.models import User
from django.shortcuts import get_object_or_404
from django.db.models import Sum, Q
from decimal import Decimal
import string
import random

from .models import Room, RoomMember, Task, Expense, ExpenseShare, UserProfile
from .serializers import (
    RoomSerializer, RoomMemberSerializer, TaskSerializer, 
    ExpenseSerializer, ExpenseShareSerializer, UserSerializer
)
from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.auth import authenticate, login
from django.utils.text import slugify


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
        code = request.data.get('code')
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
        
        # Расчеты участников
        balances = {}
        for member in room.members.all():
            # Сколько оплачено
            paid = room.expenses.filter(paid_by=member.user).aggregate(Sum('amount'))['amount__sum'] or Decimal('0')
            # Сколько должен
            owes = room.expenses.filter(shares__user=member.user).aggregate(Sum('shares__amount'))['shares__amount__sum'] or Decimal('0')
            balances[member.user.username] = float(paid - owes)
        
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
        return Task.objects.filter(room__id__in=rooms)
    
    def perform_create(self, serializer):
        """Создает задачу с текущим пользователем"""
        serializer.save(created_by=self.request.user)
    
    @action(detail='pk', methods=['post'])
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
        return Expense.objects.filter(room__id__in=rooms)
    
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
    
    @action(detail='pk', methods=['post'])
    def settle(self, request, pk=None):
        """Отметить долю как расчеты произведены"""
        share = self.get_object()
        share.is_settled = True
        share.save()
        serializer = self.get_serializer(share)
        return Response(serializer.data)


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
        if password and len(password) < 8:
            errors.append('Пароль должен содержать как минимум 8 символов')
        if password != password_confirm:
            errors.append('Пароли не совпадают')
        if not terms:
            errors.append('Необходимо согласиться с условиями')

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
            profile = user.profile
            profile.avatar = avatar
            profile.save()

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
        user = authenticate(request, username=email, password=password)
        if user is not None:
            login(request, user)
            messages.success(request, 'Вы успешно вошли в систему')
            return redirect('profile')
        else:
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
            elif len(newp) < 8:
                messages.error(request, 'Новый пароль слишком короткий (минимум 8)')
            elif newp != confirm:
                messages.error(request, 'Новые пароли не совпадают')
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
                user.email = email
                user.username = email
            user.save()
            info_success = True
        elif action == 'upload_avatar':
            avatar = request.FILES.get('avatar')
            if avatar:
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
