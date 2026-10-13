from django.urls import path

from . import views

app_name = "core_verification"

urlpatterns = [
    path("submit/", views.SubmitView.as_view(), name="submit"),
    path("status/", views.StatusView.as_view(), name="status"),
    path("welcome-seen/", views.WelcomeSeenView.as_view(), name="welcome_seen"),
]
