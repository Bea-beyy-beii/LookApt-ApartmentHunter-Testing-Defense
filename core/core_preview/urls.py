from django.urls import path

from . import views

app_name = "core_preview"

urlpatterns = [
    path("", views.LandingView.as_view(), name="landing"),
    path("preview/renter/", views.RenterPreviewView.as_view(), name="renter"),
    path("preview/landlord/", views.LandlordPreviewView.as_view(), name="landlord"),
]
