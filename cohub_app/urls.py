from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import RoomViewSet, TaskViewSet, ExpenseViewSet, ExpenseShareViewSet

router = DefaultRouter()
router.register(r'rooms', RoomViewSet, basename='room')
router.register(r'tasks', TaskViewSet, basename='task')
router.register(r'expenses', ExpenseViewSet, basename='expense')
router.register(r'expense-shares', ExpenseShareViewSet, basename='expense-share')

urlpatterns = [
    path('', include(router.urls)),
]
