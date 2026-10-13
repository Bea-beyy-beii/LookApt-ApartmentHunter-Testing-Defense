# core_reviews/urls.py
from django.urls import path

from . import views

app_name = "core_reviews"

urlpatterns = [
    path("tenancy/<uuid:tenancy_pk>/", views.SaveReviewView.as_view(), name="save_review"),
]
