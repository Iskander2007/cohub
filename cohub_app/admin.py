from django.contrib import admin
from .models import Room, RoomMember, Task, Expense, ExpenseShare, UserProfile, DebtSettlement


@admin.register(Room)
class RoomAdmin(admin.ModelAdmin):
    list_display = ['name', 'code', 'owner', 'created_at']
    list_filter = ['created_at', 'owner']
    search_fields = ['name', 'code']
    readonly_fields = ['id', 'created_at', 'updated_at']


@admin.register(RoomMember)
class RoomMemberAdmin(admin.ModelAdmin):
    list_display = ['user', 'room', 'is_admin', 'joined_at']
    list_filter = ['room', 'is_admin', 'joined_at']
    search_fields = ['user__username', 'room__name']


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = ['title', 'room', 'status', 'priority', 'assigned_to', 'due_date']
    list_filter = ['status', 'priority', 'room', 'created_at']
    search_fields = ['title', 'room__name']
    readonly_fields = ['id', 'created_at', 'updated_at']


@admin.register(Expense)
class ExpenseAdmin(admin.ModelAdmin):
    list_display = ['description', 'category', 'amount', 'paid_by', 'room', 'date']
    list_filter = ['category', 'room', 'date']
    search_fields = ['description', 'room__name']
    readonly_fields = ['id', 'created_at', 'updated_at']


@admin.register(ExpenseShare)
class ExpenseShareAdmin(admin.ModelAdmin):
    list_display = ['expense', 'user', 'amount', 'is_settled']
    list_filter = ['is_settled', 'expense__room']
    search_fields = ['user__username', 'expense__description']


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ['user', 'avatar']
    search_fields = ['user__username', 'user__email']


@admin.register(DebtSettlement)
class DebtSettlementAdmin(admin.ModelAdmin):
    list_display = ['room', 'from_user', 'to_user', 'amount', 'settled_by', 'settled_at']
    list_filter = ['room', 'settled_at']
    search_fields = ['room__name', 'from_user__username', 'to_user__username', 'settled_by__username']
