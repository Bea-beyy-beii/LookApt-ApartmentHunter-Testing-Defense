from django.urls import path
from . import views

app_name = "core_rentals"

urlpatterns = [
    path("units/<uuid:unit_pk>/assign/", views.assign_tenant, name="assign_tenant"),
    path("tenancies/<uuid:pk>/pay/", views.mark_paid, name="mark_paid"),
    path("tenancies/<uuid:pk>/end/", views.end_tenancy, name="end_tenancy"),
    path("tenancies/<uuid:pk>/renew/", views.renew_tenancy, name="renew_tenancy"),
]