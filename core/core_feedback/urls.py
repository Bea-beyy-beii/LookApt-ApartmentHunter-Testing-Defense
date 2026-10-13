from django.urls import path

from . import views

app_name = "core_feedback"

urlpatterns = [
    path("send/", views.SubmitFeedbackView.as_view(), name="submit"),
]
