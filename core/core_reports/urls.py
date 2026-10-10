from django.urls import path
from . import views

app_name = "core_reports"

urlpatterns = [
    path("reports/create/", views.create_report, name="create"),
]