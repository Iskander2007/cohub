"""
URL configuration for cohub project.
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.views.generic import TemplateView
from cohub_app.views import register_view, create_room_view, join_room_view, dashboard_view, room_insights_view
from cohub_app.views import login_view, logout_view, profile_view, subscription_view

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', include('cohub_app.urls')),
    path('', TemplateView.as_view(template_name='index.html'), name='home'),
    path('register/', register_view, name='register'),
    path('account/login/', login_view, name='login'),
    path('account/logout/', logout_view, name='logout'),
    path('account/', profile_view, name='profile'),
    path('room/create/', create_room_view, name='create-room'),
    path('room/join/', join_room_view, name='join-room'),
    path('dashboard/', dashboard_view, name='dashboard'),
    path('dashboard/<uuid:room_id>/', dashboard_view, name='dashboard-room'),
    path('dashboard/<uuid:room_id>/insights/', room_insights_view, name='room-insights'),
    path('subscription/', subscription_view, name='subscription'),
]

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
