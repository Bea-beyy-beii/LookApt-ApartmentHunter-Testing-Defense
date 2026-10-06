# core_listings/detail_services.py
# Data for the renter's listing pages:
#   - complex page (photos, units, amenities, location, landlord)
#   - unit page    (photos/videos, payment, amenities, similar units)
from decimal import Decimal

from django.db.models import Prefetch
from django.shortcuts import get_object_or_404

from core.core_maps.maps.services import complex_landmarks

from .models import BedroomType, Complex, SavedListing, Unit
from .services import renter_visible_complexes

SIMILAR_LIMIT = 6
SIMILAR_PRICE_RANGE = Decimal("0.30")   # "similar" = rent within ±30%


# =========================================================
# HELPERS
# =========================================================

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


def _features(complex_obj):
    """Every complex feature, ticked or not, e.g. for the amenities tab."""
    return [
        {"key": key, "label": label, "has": getattr(complex_obj, key)}
        for key, label in Complex.FEATURE_LABELS.items()
    ]


def landlord_summary(complex_obj):
    landlord = complex_obj.landlord
    user = landlord.user
    return {
        "name": user.display_name,
        "initials": f"{user.first_name[:1]}{user.last_name[:1]}".upper(),
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
    units = [_decorate_unit(unit) for unit in complex_obj.units.all()]
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
        "lowest_price": min(prices) if prices else None,
        "features": _features(complex_obj),
        "unit_amenities": unit_amenities,
        "landmarks": complex_landmarks(complex_obj),
        "landlord": landlord_summary(complex_obj),
        "is_saved": _is_saved(user, complex_obj),
    }


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
    _decorate_unit(unit)
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