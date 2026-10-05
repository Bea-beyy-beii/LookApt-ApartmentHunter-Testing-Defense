# core_listings/urls.py
from django.urls import path
from . import views


app_name = "core_listings"


urlpatterns = [
    # My Listings
    path("", views.listings, name="listings"),

    # Create Property
    path("create/", views.property_create, name="property_create"),

    
    path(
        "property/<uuid:pk>/",
        views.property_detail,
        name="property_detail"
    ),

    path(
        "property/<uuid:pk>/edit/",
        views.property_edit,
        name="property_edit"
    ),

    path(
        "unit/<uuid:pk>/",
        views.unit_detail,
        name="unit_detail"
    ),

    path("property/<uuid:property_pk>/units/create/", views.unit_create, name="unit_create"),
    path("unit/<uuid:pk>/edit/", views.unit_edit, name="unit_edit"),
    path("unit/<uuid:pk>/delete/", views.unit_delete, name="unit_delete"),
    path("property/<uuid:pk>/delete/", views.property_delete, name="property_delete"),
    path("property/<uuid:pk>/visibility/", views.property_set_visibility, name="property_set_visibility"),
]