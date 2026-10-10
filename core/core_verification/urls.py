from django.urls import path

from . import views

app_name = "core_verification"

urlpatterns = [
    path("submit/", views.submit, name="submit"),
    path("status/", views.status, name="status"),
    path("welcome-seen/", views.welcome_seen, name="welcome_seen"),
]
