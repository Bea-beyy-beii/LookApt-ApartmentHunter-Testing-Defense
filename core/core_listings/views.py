# core_listings/views.py
from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404

from django.db import transaction
from django.urls import reverse

from core.core_accounts.decorators import role_required
from core.core_maps.maps.services import resolve_area, save_complex_landmarks

from .models import Complex, ComplexPicture, Unit, UnitPicture
from .forms import ComplexForm, UnitForm

from django.http import JsonResponse
from django.views.decorators.http import require_POST

from .models import UnitPicture


def _my_listings_url():
    # The listings page lives inside the landlord dashboard
    return f"{reverse('core_landlords:dashboard')}?tab=myListings"


@transaction.atomic
def _save_property(form, landlord):
    """Save the wizard form + the landmarks picked on the map (step 2)."""
    property_obj = form.save(commit=False)
    property_obj.landlord = landlord

    # Which create button was clicked: "unpublished" or "active"
    visibility = form.data.get("visibility")
    if visibility in Complex.ComplexStatus.values:
        property_obj.status = visibility

    area_name = form.cleaned_data.get("area_name")
    if area_name or not property_obj.area_id:
        property_obj.area = resolve_area(area_name)

    property_obj.save()

    save_complex_landmarks(
        property_obj,
        form.cleaned_data.get("landmarks_json") or [],
        form.cleaned_data.get("travel_mode"),
    )

    photos = form.cleaned_data.get("photos") or []
    has_cover = property_obj.pictures.filter(is_cover=True).exists()
    start_position = property_obj.pictures.count()

    for index, photo in enumerate(photos):
        ComplexPicture.objects.create(
            complex=property_obj,
            image=photo,
            position=start_position + index,
            # model allows only one cover per complex; make the first photo the cover
            is_cover=(not has_cover and index == 0),
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
        form = ComplexForm(request.POST, request.FILES)

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
        form = ComplexForm(request.POST, request.FILES, instance=property_obj)
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

# ---------------------------------------------------------
# UNITS (placeholders until the Units feature is built)
# ---------------------------------------------------------

def _units_coming_soon(request):
    messages.info(request, "Managing units is coming soon.")
    return redirect(_my_listings_url())


@role_required("landlord")
def unit_create(request, property_pk):
    return _units_coming_soon(request)


@role_required("landlord")
def unit_edit(request, pk):
    return _units_coming_soon(request)


@role_required("landlord")
def unit_delete(request, pk):
    return _units_coming_soon(request)



# ---------------------------------------------------------
# ⋮ MENU ACTIONS (called with fetch() from listings_cards.js)
# ---------------------------------------------------------

def _wants_json(request):
    return "application/json" in request.headers.get("Accept", "")


def _own_property(request, pk):
    # landlord__user=request.user: a landlord can only touch their own complexes
    return get_object_or_404(Complex, pk=pk, landlord__user=request.user)


@role_required("landlord")
@require_POST
def property_delete(request, pk):
    property_obj = _own_property(request, pk)
    name = property_obj.complex_name

    # Remember the image files first: deleting rows does NOT delete files in storage (S3)
    image_files = [picture.image for picture in property_obj.pictures.all()]
    image_files += [picture.image for picture in UnitPicture.objects.filter(unit__complex=property_obj)]

    # Cascades to units, pictures and saved landmarks (on_delete=CASCADE)
    property_obj.delete()

    for image in image_files:
        try:
            image.delete(save=False)
        except Exception:
            pass   # a missing file shouldn't block the delete

    if _wants_json(request):
        return JsonResponse({"deleted": True, "name": name})
    return redirect(_my_listings_url())


@role_required("landlord")
@require_POST
def property_set_visibility(request, pk):
    property_obj = _own_property(request, pk)
    visibility = request.POST.get("visibility")

    if visibility not in Complex.ComplexStatus.values:
        if _wants_json(request):
            return JsonResponse({"error": "Invalid visibility."}, status=400)
        return redirect(_my_listings_url())

    property_obj.status = visibility
    property_obj.save(update_fields=["status", "updated_at"])

    if _wants_json(request):
        return JsonResponse({
            "status": property_obj.status,
            "label": property_obj.get_status_display(),
            "approval_status": property_obj.approval_status,
        })
    return redirect(_my_listings_url())




def _save_pictures(picture_model, owner_field, owner, photos):
    """Save uploaded photos in order; the first becomes cover if there isn't one yet."""
    existing = picture_model.objects.filter(**{owner_field: owner})
    has_cover = existing.filter(is_cover=True).exists()
    start_position = existing.count()

    for index, photo in enumerate(photos):
        picture_model.objects.create(
            **{owner_field: owner},
            image=photo,
            position=start_position + index,
            is_cover=(not has_cover and index == 0),
        )


# ---------------------------------------------------------
# UNITS
# ---------------------------------------------------------

@transaction.atomic
def _save_unit(form, complex_obj):
    unit = form.save(commit=False)
    unit.complex = complex_obj
    unit.save()
    _save_pictures(UnitPicture, "unit", unit, form.cleaned_data.get("photos") or [])
    return unit


def _unit_form_page(request, complex_obj, unit=None):
    if request.method == "POST":
        form = UnitForm(request.POST, request.FILES, instance=unit, complex_obj=complex_obj)
        if form.is_valid():
            saved = _save_unit(form, complex_obj)
            messages.success(request, f"Unit {saved.identifier} was saved.")
            return redirect(_my_listings_url())
    else:
        form = UnitForm(instance=unit, complex_obj=complex_obj)

    return render(request, "core_listings/landlords/forms/unit_form.html", {
        "form": form,
        "complex": complex_obj,
        "unit": unit,
    })


@role_required("landlord")
def unit_create(request, property_pk):
    complex_obj = get_object_or_404(Complex, pk=property_pk, landlord__user=request.user)
    return _unit_form_page(request, complex_obj)


@role_required("landlord")
def unit_edit(request, pk):
    unit = get_object_or_404(Unit, pk=pk, complex__landlord__user=request.user)
    return _unit_form_page(request, unit.complex, unit)