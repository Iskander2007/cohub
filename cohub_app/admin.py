from django.contrib import admin
from django.urls import path
from django.template.response import TemplateResponse
from .models import Room, RoomMember, Task, Expense, ExpenseShare, UserProfile, DebtSettlement, BackgroundTask, Order, PaymentEvent


# --- KPI на панели администратора (Week 5) ---------------------------------
# Добавляем в стандартный admin.site отдельную страницу /admin/kpi/ с теми же
# продуктовыми метриками, что и на сайте (compute_kpis). Ссылка на неё выводится
# в шапке всех страниц админки через переопределённый admin/base_site.html.

def admin_kpi_view(request):
    # Импорт внутри функции — чтобы не тянуть тяжёлый views.py при загрузке admin.
    from .views import compute_kpis
    context = {
        **admin.site.each_context(request),
        'title': 'KPI Dashboard',
        'kpi': compute_kpis(),
    }
    return TemplateResponse(request, 'admin/kpi.html', context)


_original_admin_get_urls = admin.site.get_urls


def _get_urls_with_kpi():
    # Кастомные маршруты идут первыми, чтобы не перехватывались catch-all админки.
    custom = [
        path('kpi/', admin.site.admin_view(admin_kpi_view), name='kpi'),
    ]
    return custom + _original_admin_get_urls()


admin.site.get_urls = _get_urls_with_kpi


# Панель KPI прямо на главной странице админки (/admin/): оборачиваем index,
# чтобы прокинуть посчитанные метрики в контекст, и подменяем шаблон на свой,
# который рендерит карточки KPI над стандартным списком приложений.
_original_admin_index = admin.site.index


def _index_with_kpi(request, extra_context=None):
    extra_context = extra_context or {}
    try:
        from .views import compute_kpis
        extra_context['kpi'] = compute_kpis()
    except Exception:  # KPI-панель не должна ломать саму админку
        extra_context['kpi'] = None
    return _original_admin_index(request, extra_context)


admin.site.index = _index_with_kpi
admin.site.index_template = 'admin/index_with_kpi.html'
# ---------------------------------------------------------------------------


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
    list_display = ['description', 'category', 'amount', 'is_shared', 'paid_by', 'room', 'date']
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
    list_display = ['user', 'role', 'avatar']
    list_filter = ['role']
    list_editable = ['role']
    search_fields = ['user__username', 'user__email']


@admin.register(DebtSettlement)
class DebtSettlementAdmin(admin.ModelAdmin):
    list_display = ['room', 'from_user', 'to_user', 'amount', 'settled_by', 'settled_at']
    list_filter = ['room', 'settled_at']
    search_fields = ['room__name', 'from_user__username', 'to_user__username', 'settled_by__username']


@admin.register(BackgroundTask)
class BackgroundTaskAdmin(admin.ModelAdmin):
    list_display = ['task_name', 'status', 'attempts', 'created_at', 'finished_at']
    list_filter = ['status', 'task_name', 'created_at']
    search_fields = ['task_name', 'result']
    readonly_fields = ['id', 'created_at', 'started_at', 'finished_at']


class PaymentEventInline(admin.TabularInline):
    model = PaymentEvent
    extra = 0
    can_delete = False
    readonly_fields = ['event_type', 'from_status', 'to_status', 'message', 'created_at']
    fields = ['event_type', 'from_status', 'to_status', 'message', 'created_at']


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ['number', 'user', 'provider', 'amount', 'currency', 'status', 'created_at', 'paid_at']
    list_filter = ['status', 'provider', 'currency', 'created_at']
    search_fields = ['number', 'user__username', 'provider_order_id', 'provider_payment_id']
    readonly_fields = ['id', 'number', 'idempotency_key', 'provider_order_id', 'provider_payment_id',
                       'created_at', 'updated_at', 'paid_at']
    inlines = [PaymentEventInline]


@admin.register(PaymentEvent)
class PaymentEventAdmin(admin.ModelAdmin):
    list_display = ['order', 'event_type', 'from_status', 'to_status', 'created_at']
    list_filter = ['event_type', 'created_at']
    search_fields = ['order__number', 'message']
    readonly_fields = ['id', 'order', 'event_type', 'from_status', 'to_status', 'message', 'payload', 'created_at']
