# core_listings/views.py
from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404

from django.core.files.base import ContentFile
from django.db import transaction
from django.urls import reverse

from core.core_accounts.decorators import role_required
from core.core_maps.maps.services import complex_landmarks, resolve_area, save_complex_landmarks
from core.core_verification.services import can_publish

from .models import Complex, ComplexPicture, Unit, UnitPicture
from .forms import (
    BulkUnitForm, MAX_BULK_UNITS,
    COMPLEX_DELETE_HAS_RENTER, COMPLEX_HAS_RENTER, UNIT_DELETE_HAS_RENTER, UNIT_HAS_RENTER, ComplexForm, UnitForm,
)

from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import ensure_csrf_cookie

from .models import UnitPicture, UnitVideo
import logging

from .models import SavedListing
from .services import renter_visible_complexes
from core.models import Renter
from .detail_services import (
    complex_detail_context, get_renter_complex, get_renter_unit, record_view, unit_detail_context,
)

NOT_VERIFIED = "Verify your account first: listings can be published once you're approved."

COMPLEX_UNPUBLISHED = "This complex is unpublished. Publish it first to change its units' status."

def _my_listings_url(saved=False):
    # The listings page lives inside the landlord dashboard.
    # saved=1 tells wizard_draft.js the submit went through, so it can drop the draft.
    url = f"{reverse('core_landlords:dashboard')}?tab=myListings"
    return url + "&saved=1" if saved else url


@transaction.atomic
def _save_property(form, landlord):
    """Save the wizard form + the landmarks picked on the map (step 2)."""
    property_obj = form.save(commit=False)
    property_obj.landlord = landlord
    moved = bool(property_obj.pk) and {"latitude", "longitude"} & set(form.changed_data)

    # Which create button was clicked: "unpublished" or "active"
    # (landlords who aren't verified yet can only save it unpublished)
    visibility = form.data.get("visibility")
    if visibility == Complex.ComplexStatus.ACTIVE and not can_publish(landlord.user):
        visibility = Complex.ComplexStatus.UNPUBLISHED
    if visibility in Complex.ComplexStatus.values:
        property_obj.status = visibility

    area_name = form.cleaned_data.get("area_name")
    if area_name or not property_obj.area_id:
        property_obj.area = resolve_area(area_name)

    property_obj.save()

    landmarks = form.cleaned_data.get("landmarks_json")
    travel_mode = form.cleaned_data.get("travel_mode")
    if landmarks is None and moved:
        # New pin but no new list: keep the landmarks, with distances from the new spot
        landmarks = saved = complex_landmarks(property_obj)
        travel_mode = travel_mode or (saved[0]["travel_mode"] if saved else None)
    if landmarks is not None:
        save_complex_landmarks(property_obj, landmarks, travel_mode)

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


def _warn_if_not_verified(request, form):
    if form.data.get("visibility") == Complex.ComplexStatus.ACTIVE and not can_publish(request.user):
        messages.warning(request, f"It was saved as unpublished. {NOT_VERIFIED}")



@role_required("landlord")
def property_create(request):
    if request.method == "POST":
        form = ComplexForm(request.POST, request.FILES, landlord=request.user.landlord)

        if form.is_valid():
            saved = _save_property(form, request.user.landlord)
            messages.success(request, f"{saved.complex_name} was created.")
            _warn_if_not_verified(request, form)
            return redirect(_my_listings_url(saved=True))
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
            messages.success(request, f"{property_obj.complex_name} was saved.")
            _warn_if_not_verified(request, form)
            return redirect(_my_listings_url(saved=True))
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

    if property_obj.units.filter(tenancies__status="active").exists():
        error = COMPLEX_DELETE_HAS_RENTER.format(name=name)
        if _wants_json(request):
            return JsonResponse({"error": error}, status=400)
        messages.error(request, error)
        return redirect(_my_listings_url())

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

    if visibility == Complex.ComplexStatus.ACTIVE and not can_publish(request.user):
        if _wants_json(request):
            return JsonResponse({"error": NOT_VERIFIED}, status=403)
        messages.error(request, NOT_VERIFIED)
        return redirect(_my_listings_url())

    if visibility == Complex.ComplexStatus.UNPUBLISHED and property_obj.units.filter(tenancies__status="active").exists():
        error = COMPLEX_HAS_RENTER.format(name=property_obj.complex_name)
        if _wants_json(request):
            return JsonResponse({"error": error}, status=400)
        messages.error(request, error)
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

    # Which button was clicked: "available" (vacant), "occupied" or "unpublished".
    # A unit with a renter stays occupied (UnitForm already refuses unpublishing it).
    availability = form.data.get("availability")
    if unit.pk and unit.has_renter:
        unit.availability = Unit.Availability.OCCUPIED
    elif availability in Unit.Availability.values:
        unit.availability = availability

    unit.save()
    _save_pictures(UnitPicture, "unit", unit, form.cleaned_data.get("photos") or [])
    _save_videos(unit, form.cleaned_data.get("videos") or [])
    return unit


def _copies(uploads):
    """Read each uploaded file once, so it can be saved for every unit."""
    copies = []
    for upload in uploads:
        upload.seek(0)
        copies.append((upload.name, upload.read()))
    return copies


@transaction.atomic
def _save_bulk_units(form, complex_obj):
    """Bulk listing: the same details, photos and videos for every unit number."""
    availability = form.data.get("availability")
    photos = _copies(form.cleaned_data.get("photos") or [])
    videos = _copies(form.cleaned_data.get("videos") or [])

    units = form.build_units()
    for unit in units:
        if availability in Unit.Availability.values:
            unit.availability = availability
        unit.save()
        _save_pictures(UnitPicture, "unit", unit, [ContentFile(data, name=name) for name, data in photos])
        _save_videos(unit, [ContentFile(data, name=name) for name, data in videos])
    return units


def _next_identifier(complex_obj):
    """Suggested first number for Bulk listing: one after the highest unit number."""
    highest = complex_obj.units.order_by("-identifier").values_list("identifier", flat=True).first()
    return (highest or 0) + 1


def _unit_form_page(request, complex_obj, unit=None):
    # "Bulk listing" switch (new units only): several units with the same details
    bulk = unit is None and request.POST.get("bulk") == "1"
    form_class = BulkUnitForm if bulk else UnitForm

    if request.method == "POST":
        form = form_class(request.POST, request.FILES, instance=unit, complex_obj=complex_obj)
        if form.is_valid():
            if bulk:
                units = _save_bulk_units(form, complex_obj)
                numbers = ", ".join(str(n) for n in sorted(u.identifier for u in units))
                messages.success(request, f"{len(units)} units were added: {numbers}.")
            else:
                saved = _save_unit(form, complex_obj)
                messages.success(request, f"Unit {saved.identifier} was saved.")
            return redirect(_my_listings_url(saved=True))
    else:
        form = UnitForm(instance=unit, complex_obj=complex_obj)

    return render(request, "core_listings/landlords/forms/unit_form.html", {
        "form": form,
        "complex": complex_obj,
        "unit": unit,
        "bulk": bulk,
        "max_bulk_units": MAX_BULK_UNITS,
        "next_identifier": _next_identifier(complex_obj),
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

    if unit.has_renter:
        error = UNIT_DELETE_HAS_RENTER.format(name=f"Unit {unit.identifier}")
        if _wants_json(request):
            return JsonResponse({"error": error}, status=400)
        messages.error(request, error)
        return redirect(_my_listings_url())

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

    if unit.complex_unpublished:
        if _wants_json(request):
            return JsonResponse({"error": COMPLEX_UNPUBLISHED}, status=400)
        messages.error(request, COMPLEX_UNPUBLISHED)
        return redirect(_my_listings_url())

    if availability == Unit.Availability.UNPUBLISHED and unit.has_renter:
        error = UNIT_HAS_RENTER.format(name=f"Unit {unit.identifier}")
        if _wants_json(request):
            return JsonResponse({"error": error}, status=400)
        messages.error(request, error)
        return redirect(_my_listings_url())

    # Occupied / available follow the contracts in Manage Rentals; the landlord
    # only publishes or unpublishes the unit
    if availability != Unit.Availability.UNPUBLISHED:
        availability = Unit.Availability.OCCUPIED if unit.has_renter else Unit.Availability.AVAILABLE

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





# =========================================================
# RENTERS — listing pages (opened from a card or the map)
# =========================================================

# Which dashboard tab the renter came from (first breadcrumb + highlighted sidebar link)
RENTER_ORIGINS = {
    "home": "Home",
    "findNear": "Find Near",
    "saved": "Saved Listings",
}


def _renter_origin(request):
    origin = request.GET.get("from")
    return origin if origin in RENTER_ORIGINS else "home"


@role_required("renter")
@ensure_csrf_cookie   # the pop-ups post with fetch(), which needs the CSRF cookie
def renter_complex_detail(request, pk):
    origin = _renter_origin(request)
    complex_obj = get_renter_complex(pk)
    record_view(request.user, complex_obj)
    context = complex_detail_context(complex_obj, request.user)
    context.update(origin=origin, origin_label=RENTER_ORIGINS[origin])
    return render(request, "core_listings/renters/complex_detail.html", context)


@role_required("renter")
@ensure_csrf_cookie   # the pop-ups post with fetch(), which needs the CSRF cookie
def renter_unit_detail(request, pk):
    origin = _renter_origin(request)
    unit = get_renter_unit(pk)
    record_view(request.user, unit.complex, unit)
    context = unit_detail_context(unit, request.user)
    context.update(origin=origin, origin_label=RENTER_ORIGINS[origin])
    return render(request, "core_listings/renters/unit_detail.html", context)