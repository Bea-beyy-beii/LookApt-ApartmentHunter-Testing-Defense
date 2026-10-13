# core_reviews/urls.py
from django.urls import path

from . import views

app_name = "core_reviews"

urlpatterns = [
    path("tenancy/<uuid:tenancy_pk>/", views.save_review, name="save_review"),
]
