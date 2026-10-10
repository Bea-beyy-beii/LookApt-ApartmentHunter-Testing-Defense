from django.urls import path
from . import views

urlpatterns = [
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('signup/', views.signup_view, name='signup'),
    path('signup/check/', views.signup_check_view, name='signup_check'),
    path('otp/', views.otp_view, name='otp'),
    path('otp/resend/', views.otp_resend_view, name='otp_resend'),
    path('auth/google/', views.google_login_view, name='google_login'),
    path('auth/callback', views.google_callback_view, name='google_callback'),

    # Top bar: dark mode switch + notification bell
    path('account/theme/', views.theme_view, name='account_theme'),
    path('account/notifications/', views.notifications_view, name='account_notifications'),
    path('account/notifications/seen/', views.notifications_seen_view, name='account_notifications_seen'),
]   