from django.urls import path

from . import views

app_name = "core_admin"

urlpatterns = [
    path("", views.overview, name="overview"),
    path("activity/", views.activity_data, name="activity_data"),
    path("verification/", views.verification_list, name="verification_list"),
    path("verification/<uuid:pk>/", views.verification_detail, name="verification_detail"),
    path("users/", views.user_list, name="user_list"),
    path("users/<uuid:pk>/", views.user_detail, name="user_detail"),
    path("reports/", views.report_list, name="report_list"),
    path("reports/<uuid:pk>/", views.report_detail, name="report_detail"),
]