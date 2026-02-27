#!/usr/bin/env python
"""
Скрипт инициализации COHUB при первом запуске
Создает тестовые данные и конфигурирует приложение
"""

import os
import django
import sys

# Настройка Django окружения
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'cohub_settings.settings')
django.setup()

from django.contrib.auth.models import User
from cohub_app.models import Room, RoomMember, Task, Expense, ExpenseShare
from django.utils import timezone
import uuid

def create_sample_data():
    """Создает примеры данных для тестирования"""
    
    print("🔧 Инициализация COHUB...")
    print("-" * 50)
    
    # Создаем тестовых пользователей
    print("\n📝 Создание пользователей...")
    users = []
    for i, name in enumerate(['Alex', 'Anna', 'Maxim'], 1):
        try:
            user = User.objects.create_user(
                username=name.lower(),
                email=f'{name.lower()}@cohub.local',
                first_name=name,
                password='testpass123'
            )
            users.append(user)
            print(f"  ✓ Пользователь {name} создан")
        except:
            user = User.objects.get(username=name.lower())
            users.append(user)
            print(f"  ✓ Пользователь {name} уже существует")
    
    # Создаем тестовую комнату
    print("\n🏠 Создание комнаты...")
    try:
        room = Room.objects.create(
            name="Комната 401",
            code="ABC123",
            description="Уютная квартира в центре города",
            owner=users[0]
        )
        print(f"  ✓ Комната создана (код: {room.code})")
    except:
        room = Room.objects.get(code="ABC123")
        print(f"  ✓ Комната уже существует (код: {room.code})")
    
    # Добавляем участников
    print("\n👥 Добавление участников...")
    for user in users:
        try:
            member = RoomMember.objects.create(
                room=room,
                user=user,
                is_admin=(user == users[0])
            )
            role = "администратор" if member.is_admin else "участник"
            print(f"  ✓ {user.first_name} добавлен как {role}")
        except:
            print(f"  ✓ {user.first_name} уже участник комнаты")
    
    # Создаем тестовые задачи
    print("\n📋 Создание задач...")
    tasks_data = [
        ("Уборка кухни", "Помыть посуду и вытереть столы", users[0]),
        ("Покупка продуктов", "Купить молоко, хлеб и масло", users[1]),
        ("Уборка ванной", "Почистить ванну и раковину", users[2]),
    ]
    
    for title, desc, assigned_to in tasks_data:
        try:
            task = Task.objects.create(
                room=room,
                title=title,
                description=desc,
                assigned_to=assigned_to,
                created_by=users[0],
                status='pending',
                priority='medium'
            )
            print(f"  ✓ Задача '{title}' создана")
        except:
            print(f"  ✓ Задача '{title}' уже существует")
    
    # Создаем тестовые расходы
    print("\n💰 Создание расходов...")
    expenses_data = [
        ("Коммунальные услуги", 4500, "коммунальные"),
        ("Продукты", 2300, "еда"),
        ("Чистящие средства", 800, "бытовые"),
    ]
    
    for desc, amount, category in expenses_data:
        try:
            expense = Expense.objects.create(
                room=room,
                description=desc,
                amount=amount,
                paid_by=users[0],
                category=category,
                date=timezone.now().date()
            )
            
            # Распределяем расход поровну
            share_amount = amount / len(users)
            for user in users:
                ExpenseShare.objects.create(
                    expense=expense,
                    user=user,
                    amount=share_amount
                )
            
            print(f"  ✓ Расход '{desc}' ({amount}₸) создан")
        except:
            print(f"  ✓ Расход '{desc}' уже существует")
    
    print("\n" + "=" * 50)
    print("✅ Инициализация завершена!")
    print("=" * 50)
    print("\n📍 Тестовые данные:")
    print(f"  Комната: {room.name}")
    print(f"  Код для присоединения: {room.code}")
    print(f"  Участники: {', '.join([u.first_name for u in users])}")
    print("\n🔐 Учетные данные для входа:")
    for user in users:
        print(f"  {user.first_name.lower()}: testpass123")
    print(f"\n👨‍💼 Администратор:")
    print(f"  admin: (установить пароль командой: python manage.py changepassword admin)")
    print("\n🌐 Ссылки:")
    print(f"  Главная: http://localhost:8000/")
    print(f"  Панель: http://localhost:8000/dashboard/")
    print(f"  Admin: http://localhost:8000/admin/")
    print("\n💡 Совет: Вернитесь в терминал для запуска сервера")

if __name__ == '__main__':
    try:
        create_sample_data()
    except Exception as e:
        print(f"\n❌ Ошибка: {e}")
        sys.exit(1)
