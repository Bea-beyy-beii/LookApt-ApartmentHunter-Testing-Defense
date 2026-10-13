from django.urls import path
from . import views

app_name = "core_reports"

urlpatterns = [
    path("reports/create/", views.CreateReportView.as_view(), name="create"),
]