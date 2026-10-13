# core_listings/detail_services.py
# Data for the renter's listing pages:
#   - complex page (photos, units, amenities, location, landlord)
#   - unit page    (photos/videos, payment, amenities, similar units)
from collections import Counter
from decimal import Decimal

from django.db.models import Prefetch
from django.shortcuts import get_object_or_404
from django.utils import timezone

from core.core_inquiries.models import Application
from core.core_inquiries.services import LeaseSchedule
from core.core_maps.maps.services import ComplexLandmarks

from .models import BedroomType, Complex, ListingView, SavedListing, Unit
from .services import renter_visible_complexes

SIMILAR_LIMIT = 6
SIMILAR_PRICE_RANGE = Decimal("0.30")   # "similar" = rent within ±30%


# =========================================================
# HELPERS
# =========================================================

def record_view(user, complex_obj, unit=None):
    """Count a renter's visit for the landlord's "Views" (once per page per day)."""
    ListingView.objects.get_or_create(
        complex=complex_obj, unit=unit, viewer=user, viewed_on=timezone.localdate(),
    )


def _published_units():
    # Renters never see unpublished units
    return (
        Unit.objects
        .exclude(availability=Unit.Availability.UNPUBLISHED)
        .prefetch_related("pictures")
        .order_by("identifier")
    )


def _cover(pictures):
    """The cover photo, or the first one (pictures are already prefetched)."""
    pictures = list(pictures)
    return next((p for p in pictures if p.is_cover), None) or (pictures[0] if pictures else None)


def _decorate_unit(unit):
    """Values every unit row / card shows."""
    cover = _cover(unit.pictures.all())
    unit.cover_url = cover.image.url if cover else ""
    unit.is_available = unit.availability == Unit.Availability.AVAILABLE
    return unit


def _attach_inquiry_info(units, user):
    """What the Apply / Waitlist buttons and the demand box need, per unit."""
    pending = Application.objects.filter(unit__in=units, status__in=Application.OPEN_STATUSES)
    demand = Counter(pending.values_list("unit_id", flat=True))
    mine = set(pending.filter(renter__user=user).values_list("unit_id", flat=True))

    for unit in units:
        unit.demand = demand[unit.pk]               # renters interested / on the waitlist
        unit.has_pending = unit.pk in mine          # this renter already applied
        lease = LeaseSchedule(unit)
        unit.earliest_move_in = lease.earliest_move_in
        unit.lease_end = lease.current_end          # None when the landlord hasn't set it
    return units


def _features(complex_obj):
    """Every complex feature, ticked or not, e.g. for the amenities tab."""
    return [
        {"key": key, "label": label, "has": getattr(complex_obj, key)}
        for key, label in Complex.FEATURE_LABELS.items()
    ]


def landlord_summary(complex_obj):
    from core.core_reviews.models import Review    # core_reviews imports core_rentals -> core_listings
    landlord = complex_obj.landlord
    user = landlord.user
    return {
        "rating": Review.objects.for_landlord(landlord).summary("landlord"),        # stars beside the name
        "name": user.display_name,
        "initials": user.initials,
        "avatar_url": user.avatar_url,
        # Only what the landlord chose to show (Settings > Contact sharing)
        "email": user.email if user.share_email else "",
        "phone": user.phone_number if user.share_phone else "",
        "is_verified": user.is_verified,
        "listings": renter_visible_complexes().filter(landlord=landlord).count(),
        "member_since": user.date_joined,
    }


def _is_saved(user, complex_obj):
    return SavedListing.objects.filter(renter__user=user, complex=complex_obj).exists()


# =========================================================
# COMPLEX PAGE
# =========================================================

def get_renter_complex(pk):
    queryset = (
        renter_visible_complexes()
        .select_related("landlord__user", "area")
        .prefetch_related("pictures", Prefetch("units", queryset=_published_units()))
    )
    return get_object_or_404(queryset, pk=pk)


def complex_detail_context(complex_obj, user):
    from core.core_reviews.models import Review
    from core.core_reviews.services import ComplexReviews

    units = [_decorate_unit(unit) for unit in complex_obj.units.all()]
    _attach_inquiry_info(units, user)
    ratings = Review.objects.unit_summaries(units)
    for unit in units:
        unit.rating = ratings.get(unit.pk)          # stars under the price (None: no reviews yet)
    available = [unit for unit in units if unit.is_available]

    # Unit types in the usual order: Studio, 1BR, 2BR, 3+
    type_labels = dict(BedroomType.choices)
    present_types = {unit.bedroom_type for unit in units}
    unit_types = [{"key": key, "label": label} for key, label in type_labels.items() if key in present_types]

    # In-unit amenities found in this complex: "Air Conditioned — 3 of 4 units"
    unit_amenities = []
    for name in Unit.AMENITY_FIELDS:
        count = sum(1 for unit in units if getattr(unit, name))
        if count:
            unit_amenities.append({
                "key": name,
                "label": Unit._meta.get_field(name).verbose_name,
                "count": count,
            })

    prices = [unit.price for unit in (available or units)]

    return {
        "complex": complex_obj,
        "media": [{"kind": "image", "url": p.image.url} for p in complex_obj.pictures.all()],
        "units": units,
        "unit_types": unit_types,
        "available_count": len(available),
        "occupied_count": len(units) - len(available),
        "demand": sum(unit.demand for unit in units),
        "lowest_price": min(prices) if prices else None,
        "features": _features(complex_obj),
        "unit_amenities": unit_amenities,
        "landmarks": ComplexLandmarks(complex_obj).as_list(),
        "landlord": landlord_summary(complex_obj),
        "is_saved": _is_saved(user, complex_obj),
        "other_listings": _other_listings(complex_obj, user),
        "complex_rating": Review.objects.for_complex(complex_obj).summary("complex"),   # stars beside the name
        **ComplexReviews(complex_obj).context(),          # Reviews tab
    }


def _other_listings(complex_obj, user):
    from core.core_renters.services import ListingCards   # core_renters imports core_listings
    return ListingCards(user).other_listings(complex_obj)


# =========================================================
# UNIT PAGE
# =========================================================

def get_renter_unit(pk):
    queryset = (
        _published_units()
        .filter(complex__in=renter_visible_complexes())
        .select_related("complex__landlord__user", "complex__area")
        .prefetch_related("videos")
    )
    return get_object_or_404(queryset, pk=pk)


def _payment(unit):
    advance = unit.price * unit.advance_months
    deposit = unit.price * unit.deposit_months
    return {
        "advance_months": unit.advance_months,
        "advance": advance,
        "deposit_months": unit.deposit_months,
        "deposit": deposit,
        # Move-in = advance + deposit; with neither, just the first month
        "total": (advance + deposit) or unit.price,
    }


def _similar_units(unit):
    """Same unit type and a close rent: first in the same complex, then elsewhere."""
    low = unit.price * (1 - SIMILAR_PRICE_RANGE)
    high = unit.price * (1 + SIMILAR_PRICE_RANGE)

    # Same complex: every other published unit, most similar first
    same_complex = [
        _decorate_unit(other) for other in _published_units()
        .filter(complex=unit.complex)
        .exclude(pk=unit.pk)
    ]
    same_complex.sort(key=lambda other: (
        other.bedroom_type != unit.bedroom_type,   # same type first
        not other.is_available,                    # then available
        abs(other.price - unit.price),             # then closest rent
    ))

    other_complexes = [
        _decorate_unit(other) for other in _published_units()
        .filter(
            complex__in=renter_visible_complexes().exclude(pk=unit.complex_id),
            bedroom_type=unit.bedroom_type,
            price__gte=low,
            price__lte=high,
        )
        .select_related("complex")
    ]
    other_complexes.sort(key=lambda other: (not other.is_available, abs(other.price - unit.price)))

    return same_complex[:SIMILAR_LIMIT], other_complexes[:SIMILAR_LIMIT]


def unit_detail_context(unit, user):
    from core.core_reviews.models import Review

    _decorate_unit(unit)
    unit.rating = Review.objects.for_unit(unit).summary("unit")
    _attach_inquiry_info([unit], user)
    complex_obj = unit.complex
    same_complex, other_complexes = _similar_units(unit)

    # Photos first, then videos (the gallery shows both)
    media = [{"kind": "image", "url": p.image.url} for p in unit.pictures.all()]
    media += [{"kind": "video", "url": v.video.url} for v in unit.videos.all()]

    unit_amenities = [
        {"key": name, "label": Unit._meta.get_field(name).verbose_name, "has": getattr(unit, name)}
        for name in Unit.AMENITY_FIELDS
    ]

    return {
        "unit": unit,
        "complex": complex_obj,
        "media": media,
        "payment": _payment(unit),
        "unit_amenities": unit_amenities,
        "features": _features(complex_obj),
        "similar_same_complex": same_complex,
        "similar_other_complexes": other_complexes,
        "landlord": landlord_summary(complex_obj),
    }