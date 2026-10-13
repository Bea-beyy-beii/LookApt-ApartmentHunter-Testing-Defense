from django.urls import path
from . import views

app_name = "core_rentals"

urlpatterns = [
    path("units/<uuid:unit_pk>/assign/", views.AssignTenantView.as_view(), name="assign_tenant"),
    path("tenancies/<uuid:pk>/pay/", views.MarkPaidView.as_view(), name="mark_paid"),
    path("tenancies/<uuid:pk>/end/", views.EndTenancyView.as_view(), name="end_tenancy"),
    path("tenancies/<uuid:pk>/renew/", views.RenewTenancyView.as_view(), name="renew_tenancy"),
]
