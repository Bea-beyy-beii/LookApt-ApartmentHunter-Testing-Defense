# core_renters/search.py
# Search bar + "Filter by" on the renter's Home and Saved Listings tabs.
#
#   ?q=sunrise davao&lease_term=monthly&pets=1&budget_max=8000 ...
#
# Complex-level filters narrow the complexes; unit-level filters narrow the
# units, and a complex only shows when at least one of its units still matches
# (the card's price then comes from those units).
from decimal import Decimal, InvalidOperation

from django.db.models import Q

from core.core_listings.models import BedroomType, Complex, FurnishLevel, LeaseTerm, SexRestriction, Unit

MAX_QUERY_LENGTH = 100

# Checkbox name -> model field. Complex features first, then unit amenities.
COMPLEX_FEATURES = {
    "pets": "pet_friendly",
    "parking": "has_parking_space",
    "gated": "is_gated",
    "laundry": "has_laundry_area",
    "security": "has_security",
    "cctv": "has_cctv",
    "lounge": "has_common_lounge",
    "waste": "has_waste_collection",
}
UNIT_AMENITIES = {
    "aircon": "air_conditioned",
    "wifi": "wifi_ready",
    "bathroom": "own_bathroom",
    "kitchen": "has_kitchen_area",
    "meter": "own_electric_meter",
    "heater": "has_water_heater",
}

SORTS = {
    "newest": "Newest first",
    "price_low": "Price: low to high",
    "price_high": "Price: high to low",
}


def _decimal(value):
    try:
        number = Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, ValueError):
        return None
    return number if number > 0 else None


def _positive_int(value, limit=20):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if 1 <= number <= limit else None


def _choice(value, choices):
    return value if value in choices else ""


def parse_filters(params):
    """GET params -> cleaned filters. Anything invalid is simply ignored."""
    budget_min, budget_max = _decimal(params.get("budget_min")), _decimal(params.get("budget_max"))
    if budget_min and budget_max and budget_min > budget_max:
        budget_min, budget_max = budget_max, budget_min

    return {
        "q": (params.get("q") or "").strip()[:MAX_QUERY_LENGTH],
        "lease_term": _choice(params.get("lease_term"), LeaseTerm.values),
        "sex": _choice(params.get("sex"), SexRestriction.values),
        "unit_type": _choice(params.get("unit_type"), BedroomType.values),
        "furnishing": _choice(params.get("furnishing"), FurnishLevel.values),
        "occupants": _positive_int(params.get("occupants")),
        "budget_min": budget_min,
        "budget_max": budget_max,
        "available": params.get("available") == "1",
        "features": [key for key in COMPLEX_FEATURES if params.get(key) == "1"],
        "amenities": [key for key in UNIT_AMENITIES if params.get(key) == "1"],
        "sort": _choice(params.get("sort"), SORTS) or "newest",
    }


def active_filter_count(filters):
    """For the badge on the "Filter by" button (search text and sort don't count)."""
    count = sum(bool(filters[key]) for key in ("lease_term", "sex", "unit_type", "furnishing", "occupants", "available"))
    count += bool(filters["budget_min"] or filters["budget_max"])
    return count + len(filters["features"]) + len(filters["amenities"])


def filter_complexes(complexes, filters):
    """Complex name, address, area, nearby landmarks, landlord name + complex-level filters."""
    for word in filters["q"].split():
        complexes = complexes.filter(
            Q(complex_name__icontains=word)
            | Q(address__icontains=word)
            | Q(area__area_name__icontains=word)
            | Q(landmarks__landmark__name__icontains=word)
            | Q(landlord__user__first_name__icontains=word)
            | Q(landlord__user__last_name__icontains=word)
        )

    if filters["lease_term"]:
        complexes = complexes.filter(lease_term=filters["lease_term"])
    if filters["sex"]:
        complexes = complexes.filter(sex_restriction=filters["sex"])
    for key in filters["features"]:
        complexes = complexes.filter(**{COMPLEX_FEATURES[key]: True})

    return complexes.distinct()     # the landmark join can repeat a complex


def filter_units(units, filters):
    """Unit-level filters: the units a renter could actually take."""
    if filters["unit_type"]:
        units = units.filter(bedroom_type=filters["unit_type"])
    if filters["furnishing"]:
        units = units.filter(furnish_level=filters["furnishing"])
    if filters["occupants"]:
        units = units.filter(max_occupant__gte=filters["occupants"])
    if filters["budget_min"]:
        units = units.filter(price__gte=filters["budget_min"])
    if filters["budget_max"]:
        units = units.filter(price__lte=filters["budget_max"])
    if filters["available"]:
        units = units.filter(availability=Unit.Availability.AVAILABLE)
    for key in filters["amenities"]:
        units = units.filter(**{UNIT_AMENITIES[key]: True})
    return units


def sort_listings(listings, sort):
    if sort == "price_low":
        return sorted(listings, key=lambda c: c.card_price)
    if sort == "price_high":
        return sorted(listings, key=lambda c: c.card_price, reverse=True)
    return listings        # already newest first


def filter_options():
    """Choices for the filter panel (template)."""
    return {
        "lease_terms": LeaseTerm.choices,
        "sex_restrictions": [c for c in SexRestriction.choices if c[0] != SexRestriction.NO_RESTRICTION]
                            + [(SexRestriction.NO_RESTRICTION, "No restriction")],
        "unit_types": BedroomType.choices,
        "furnishings": FurnishLevel.choices,
        "features": [(key, Complex.FEATURE_LABELS[field]) for key, field in COMPLEX_FEATURES.items()],
        "amenities": [(key, Unit._meta.get_field(field).verbose_name) for key, field in UNIT_AMENITIES.items()],
        "sorts": list(SORTS.items()),
    }
