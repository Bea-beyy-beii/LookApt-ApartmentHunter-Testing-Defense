from django.urls import path
from . import views

urlpatterns = [
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('signup/', views.signup_view, name='signup'),
    path('otp/', views.otp_view, name='otp'),

    # Top bar: dark mode switch + notification bell
    path('account/theme/', views.theme_view, name='account_theme'),
    path('account/notifications/', views.notifications_view, name='account_notifications'),
    path('account/notifications/seen/', views.notifications_seen_view, name='account_notifications_seen'),
]   