from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    RoomViewSet, TaskViewSet, TaskReassignmentRequestViewSet, ExpenseViewSet,
    ExpenseShareViewSet, ChatMessageViewSet, LoanViewSet, LoanPaymentViewSet,
    SubscriptionViewSet, TeacherMetricsView,
)
from .payment_views import OrderViewSet
from .monitoring import health_check, metrics_endpoint, metrics_prometheus_format, metrics_summary

router = DefaultRouter()
router.register(r'rooms', RoomViewSet, basename='room')
router.register(r'tasks', TaskViewSet, basename='task')
router.register(r'task-reassignment-requests', TaskReassignmentRequestViewSet, basename='task-reassignment-request')
router.register(r'expenses', ExpenseViewSet, basename='expense')
router.register(r'expense-shares', ExpenseShareViewSet, basename='expense-share')
router.register(r'loans', LoanViewSet, basename='loan')
router.register(r'loan-payments', LoanPaymentViewSet, basename='loan-payment')
router.register(r'chat-messages', ChatMessageViewSet, basename='chat-message')
router.register(r'subscription', SubscriptionViewSet, basename='subscription')
router.register(r'orders', OrderViewSet, basename='order')

urlpatterns = [
    path('teacher-metrics/', TeacherMetricsView.as_view(), name='teacher-metrics'),
    
    # Мониторинг и метрики
    path('health/', health_check, name='health_check'),
    path('metrics/', metrics_endpoint, name='metrics_endpoint'),
    path('metrics/prometheus/', metrics_prometheus_format, name='metrics_prometheus'),
    path('metrics/summary/', metrics_summary, name='metrics_summary'),
    
    path('', include(router.urls)),
]
