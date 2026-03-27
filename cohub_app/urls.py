from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import RoomViewSet, TaskViewSet, ExpenseViewSet, ExpenseShareViewSet, ChatMessageViewSet

router = DefaultRouter()
router.register(r'rooms', RoomViewSet, basename='room')
router.register(r'tasks', TaskViewSet, basename='task')
router.register(r'expenses', ExpenseViewSet, basename='expense')
router.register(r'expense-shares', ExpenseShareViewSet, basename='expense-share')
router.register(r'chat-messages', ChatMessageViewSet, basename='chat-message')

urlpatterns = [
    path('', include(router.urls)),
]
