# core_listings/views.py
from django.shortcuts import render, redirect, get_object_or_404

from django.db import transaction
from django.urls import reverse

from core.core_accounts.decorators import role_required
from core.core_maps.maps.services import resolve_area, save_complex_landmarks

from .models import Complex, ComplexPicture, Unit
from .forms import ComplexForm


def _my_listings_url():
    # The listings page lives inside the landlord dashboard
    return f"{reverse('core_landlords:dashboard')}?tab=myListings"


@transaction.atomic
def _save_property(form, landlord):
    """Save the wizard form + the landmarks picked on the map (step 2)."""
    property_obj = form.save(commit=False)
    property_obj.landlord = landlord

    area_name = form.cleaned_data.get("area_name")
    if area_name or not property_obj.area_id:
        property_obj.area = resolve_area(area_name)

    property_obj.save()

    save_complex_landmarks(
        property_obj,
        form.cleaned_data.get("landmarks_json") or [],
        form.cleaned_data.get("travel_mode"),
    )
    return property_obj


def listings(request):
    properties = Complex.objects.all()

    status = request.GET.get("status")

    if status:
        properties = properties.filter(status=status)

    context = {
        "properties": properties,
        "current_filter": status,
    }

    return render(
        request,
        "core_listings/landlords/listings.html",
        context
    )


@role_required("landlord")
def property_create(request):
    if request.method == "POST":
        form = ComplexForm(request.POST)

        if form.is_valid():
            _save_property(form, request.user.landlord)
            return redirect(_my_listings_url())

    else:
        form = ComplexForm()

    return render(
        request,
        "core_listings/landlords/forms/property_form.html",
        {
            "property": None,
            "current_step": 1,
            "form": form,
        }
    )



def property_detail(request, pk):
    property_obj = get_object_or_404(
        Complex,
        pk=pk
    )

    active_tab = request.GET.get(
        "tab",
        "overview"
    )

    return render(
        request,
        "core_listings/landlords/property_detail.html",
        {
            "property": property_obj,
            "active_tab": active_tab,
        }
    )


@role_required("landlord")
def property_edit(request, pk):
    property_obj = get_object_or_404(Complex, pk=pk, landlord__user=request.user)

    if request.method == "POST":
        form = ComplexForm(request.POST, instance=property_obj)
        if form.is_valid():
            _save_property(form, property_obj.landlord)
            return redirect(_my_listings_url())
    else:
        form = ComplexForm(instance=property_obj)

    return render(
        request,
        "core_listings/landlords/forms/property_form.html",
        {
            "property": property_obj,
            "current_step": 1,
            "form": form,
        }
    )


def unit_detail(request, pk):
    unit = get_object_or_404(
        Unit,
        pk=pk
    )

    return render(
        request,
        "core_listings/landlords/unit_detail.html",
        {
            "unit": unit,
        }
    )