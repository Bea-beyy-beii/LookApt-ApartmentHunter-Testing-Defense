from django.urls import path
from . import views

urlpatterns = [
    path('login/', views.LoginView.as_view(), name='login'),
    path('logout/', views.LogoutView.as_view(), name='logout'),
    path('signup/', views.SignUpView.as_view(), name='signup'),
    path('signup/check/', views.SignUpCheckView.as_view(), name='signup_check'),
    path('terms/', views.TermsView.as_view(), name='terms'),
    path('privacy/', views.PrivacyView.as_view(), name='privacy'),
    path('otp/', views.SignUpCodeView.as_view(), name='otp'),
    path('otp/resend/', views.SignUpResendView.as_view(), name='otp_resend'),

    # Forgot password: account -> emailed code -> new password
    path('forgot-password/', views.ForgotPasswordView.as_view(), name='forgot_password'),
    path('forgot-password/code/', views.ForgotPasswordCodeView.as_view(), name='forgot_password_code'),
    path('forgot-password/code/resend/', views.ForgotPasswordResendView.as_view(), name='forgot_password_resend'),
    path('forgot-password/new/', views.ForgotPasswordNewView.as_view(), name='forgot_password_new'),
    path('auth/google/', views.GoogleLoginView.as_view(), name='google_login'),
    path('auth/callback', views.GoogleCallbackView.as_view(), name='google_callback'),

    # Top bar: dark mode switch + notification bell
    path('account/theme/', views.ThemeView.as_view(), name='account_theme'),
    path('account/avatar/', views.AvatarView.as_view(), name='account_avatar'),
    path('account/contact/', views.ContactSharingView.as_view(), name='account_contact'),
    path('account/password/', views.ChangePasswordView.as_view(), name='account_password'),
    path('account/notifications/', views.NotificationsView.as_view(), name='account_notifications'),
    path('account/notifications/seen/', views.NotificationsSeenView.as_view(), name='account_notifications_seen'),
    path('account/notifications/clear/', views.NotificationsClearView.as_view(), name='account_notifications_clear'),
]
