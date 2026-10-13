from django.urls import path

from . import views

app_name = "core_admin"

urlpatterns = [
    path("", views.OverviewView.as_view(), name="overview"),
    path("activity/", views.ActivityDataView.as_view(), name="activity_data"),
    path("verification/", views.VerificationListView.as_view(), name="verification_list"),
    path("verification/<uuid:pk>/", views.VerificationDetailView.as_view(), name="verification_detail"),
    path("users/", views.UserListView.as_view(), name="user_list"),
    path("users/<uuid:pk>/", views.UserDetailView.as_view(), name="user_detail"),
    path("reports/", views.ReportListView.as_view(), name="report_list"),
    path("reports/<uuid:pk>/", views.ReportDetailView.as_view(), name="report_detail"),
]