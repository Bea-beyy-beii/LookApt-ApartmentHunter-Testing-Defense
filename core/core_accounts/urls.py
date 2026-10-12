from django.urls import path
from . import views

urlpatterns = [
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('signup/', views.signup_view, name='signup'),
    path('signup/check/', views.signup_check_view, name='signup_check'),
    path('terms/', views.terms_view, name='terms'),
    path('privacy/', views.privacy_view, name='privacy'),
    path('otp/', views.otp_view, name='otp'),
    path('otp/resend/', views.otp_resend_view, name='otp_resend'),

    # Forgot password: account -> emailed code -> new password
    path('forgot-password/', views.forgot_password_view, name='forgot_password'),
    path('forgot-password/code/', views.forgot_password_code_view, name='forgot_password_code'),
    path('forgot-password/code/resend/', views.forgot_password_resend_view, name='forgot_password_resend'),
    path('forgot-password/new/', views.forgot_password_new_view, name='forgot_password_new'),
    path('auth/google/', views.google_login_view, name='google_login'),
    path('auth/callback', views.google_callback_view, name='google_callback'),

    # Top bar: dark mode switch + notification bell
    path('account/theme/', views.theme_view, name='account_theme'),
    path('account/notifications/', views.notifications_view, name='account_notifications'),
    path('account/notifications/seen/', views.notifications_seen_view, name='account_notifications_seen'),
]   