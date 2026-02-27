from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
import uuid


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
    
    def __str__(self):
        return self.title


class Expense(models.Model):
    """Расход в комнате"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name='expenses', verbose_name="Комната")
    description = models.CharField(max_length=255, verbose_name="Описание")
    amount = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Сумма")
    paid_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='paid_expenses', verbose_name="Оплачено")
    date = models.DateField(default=timezone.now, verbose_name="Дата")
    category = models.CharField(max_length=100, verbose_name="Категория")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Дата создания")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Дата изменения")
    
    class Meta:
        verbose_name = "Расход"
        verbose_name_plural = "Расходы"
        ordering = ['-date']
    
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


class UserProfile(models.Model):
    """Дополнительная информация о пользователе (аватар и т.п.)"""
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    avatar = models.ImageField(upload_to='avatars/', blank=True, null=True)
    bio = models.TextField(blank=True, null=True, verbose_name="Биография")
    
    def __str__(self):
        return f"Профиль {self.user.username}"


# Signal to create profile automatically when a User is created
from django.db.models.signals import post_save
from django.dispatch import receiver

@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        UserProfile.objects.create(user=instance)
