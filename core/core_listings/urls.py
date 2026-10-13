# core_listings/urls.py
from django.urls import path
from . import views


app_name = "core_listings"


urlpatterns = [
    # My Listings
    path("", views.ListingsView.as_view(), name="listings"),

    # Create Property
    path("create/", views.PropertyCreateView.as_view(), name="property_create"),


    path(
        "property/<uuid:pk>/",
        views.PropertyDetailView.as_view(),
        name="property_detail"
    ),

    path(
        "property/<uuid:pk>/edit/",
        views.PropertyEditView.as_view(),
        name="property_edit"
    ),

    path(
        "unit/<uuid:pk>/",
        views.UnitDetailView.as_view(),
        name="unit_detail"
    ),

    path("property/<uuid:property_pk>/units/create/", views.UnitCreateView.as_view(), name="unit_create"),
    path("unit/<uuid:pk>/edit/", views.UnitEditView.as_view(), name="unit_edit"),
    path("unit/<uuid:pk>/delete/", views.UnitDeleteView.as_view(), name="unit_delete"),
    path("property/<uuid:pk>/delete/", views.PropertyDeleteView.as_view(), name="property_delete"),
    path("property/<uuid:pk>/visibility/", views.PropertyVisibilityView.as_view(), name="property_set_visibility"),
    path("unit/<uuid:pk>/availability/", views.UnitAvailabilityView.as_view(), name="unit_set_availability"),
    path("property/<uuid:pk>/save/", views.ToggleSavedListingView.as_view(), name="toggle_saved_listing"),
    path("listing/<uuid:pk>/", views.RenterComplexDetailView.as_view(), name="renter_complex_detail"),
    path("listing/unit/<uuid:pk>/", views.RenterUnitDetailView.as_view(), name="renter_unit_detail"),
]
