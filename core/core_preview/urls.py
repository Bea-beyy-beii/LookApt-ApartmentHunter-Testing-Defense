from django.urls import path

from . import views

app_name = "core_preview"

urlpatterns = [
    path("", views.landing, name="landing"),
    path("preview/renter/", views.renter_preview, name="renter"),
    path("preview/landlord/", views.landlord_preview, name="landlord"),
]
