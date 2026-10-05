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

from .models import UnitPicture, UnitVideo
import logging

from .models import SavedListing
from .services import renter_visible_complexes
from core.models import Renter


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
        "core_listings/landlords/forms/property_form_page.html",
        {
            "property": None,
            "current_step": 1,
            "form": form,
            "active_tab": "myListings",
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
        "core_listings/landlords/forms/property_form_page.html",
        {
            "property": property_obj,
            "current_step": 1,
            "form": form,
            "active_tab": "myListings",
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
# ⋮ MENU ACTIONS (called with fetch() from listings_cards.js)
# ---------------------------------------------------------

def _wants_json(request):
    return "application/json" in request.headers.get("Accept", "")


def _own_property(request, pk):
    # landlord__user=request.user: a landlord can only touch their own complexes
    return get_object_or_404(Complex, pk=pk, landlord__user=request.user)



logger = logging.getLogger(__name__)


def _delete_files(files):
    """Remove files from storage (S3). Deleting rows does NOT delete their files."""
    for file in files:
        try:
            file.delete(save=False)
        except Exception as error:
            # Don't block the delete, but don't hide the problem either
            logger.warning("Could not delete %s: %s", file.name, error)


def _unit_media_files(units):
    files = [picture.image for picture in UnitPicture.objects.filter(unit__in=units)]
    files += [clip.video for clip in UnitVideo.objects.filter(unit__in=units)]
    return files


@role_required("landlord")
@require_POST
def property_delete(request, pk):
    property_obj = _own_property(request, pk)
    name = property_obj.complex_name

    files = [picture.image for picture in property_obj.pictures.all()]
    files += _unit_media_files(property_obj.units.all())

    property_obj.delete()   # cascades to units, pictures, videos, landmarks
    _delete_files(files)

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

def _save_videos(unit, videos):
    start = unit.videos.count()
    for index, clip in enumerate(videos):
        UnitVideo.objects.create(unit=unit, video=clip, position=start + index)


@transaction.atomic
def _save_unit(form, complex_obj):
    unit = form.save(commit=False)
    unit.complex = complex_obj

    # Which button was clicked: "available" (vacant), "occupied" or "unpublished"
    availability = form.data.get("availability")
    if availability in Unit.Availability.values:
        unit.availability = availability

    unit.save()
    _save_pictures(UnitPicture, "unit", unit, form.cleaned_data.get("photos") or [])
    _save_videos(unit, form.cleaned_data.get("videos") or [])
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
        "active_tab": "myListings",
    })


@role_required("landlord")
def unit_create(request, property_pk):
    complex_obj = get_object_or_404(Complex, pk=property_pk, landlord__user=request.user)
    return _unit_form_page(request, complex_obj)


@role_required("landlord")
def unit_edit(request, pk):
    unit = get_object_or_404(Unit, pk=pk, complex__landlord__user=request.user)
    return _unit_form_page(request, unit.complex, unit)

def _own_unit(request, pk):
    return get_object_or_404(Unit, pk=pk, complex__landlord__user=request.user)


@role_required("landlord")
@require_POST
def unit_delete(request, pk):
    unit = _own_unit(request, pk)
    name = unit.unit_name
    files = _unit_media_files(Unit.objects.filter(pk=unit.pk))

    unit.delete()
    _delete_files(files)

    if _wants_json(request):
        return JsonResponse({"deleted": True, "name": name})
    messages.success(request, f"{name} was deleted.")
    return redirect(_my_listings_url())


@role_required("landlord")
@require_POST
def unit_set_availability(request, pk):
    unit = _own_unit(request, pk)
    availability = request.POST.get("availability")

    if availability not in Unit.Availability.values:
        if _wants_json(request):
            return JsonResponse({"error": "Invalid status."}, status=400)
        return redirect(_my_listings_url())

    unit.availability = availability
    unit.save(update_fields=["availability", "updated_at"])

    if _wants_json(request):
        return JsonResponse({
            "availability": unit.availability,
            "label": unit.get_availability_display(),
        })
    return redirect(_my_listings_url())



# =========================================================
# RENTERS — save / unsave a listing (the ribbon on the card)
# =========================================================

@role_required("renter")
@require_POST
def toggle_saved_listing(request, pk):
    complex_obj = get_object_or_404(renter_visible_complexes(), pk=pk)
    renter, _ = Renter.objects.get_or_create(user=request.user)

    saved, created = SavedListing.objects.get_or_create(renter=renter, complex=complex_obj)
    if not created:
        saved.delete()   # second click = unsave

    return JsonResponse({"saved": created})