# core_renters/services.py
# Listing cards on the renter dashboard (Home + Saved Listings tabs).
from collections import Counter

from django.db.models import Prefetch

from core.core_listings.models import SavedListing, Unit
from core.core_listings.services import renter_visible_complexes

MAX_CARD_CHIPS = 3


def _decorate(complex_obj, saved_ids):
    """Add the values the card shows: price, availability badge, chips, saved state."""
    units = list(complex_obj.units.all())   # published units only (see the Prefetch below)
    available = [unit for unit in units if unit.availability == Unit.Availability.AVAILABLE]
    priced = available or units

    complex_obj.card_price = min(unit.price for unit in priced)
    complex_obj.card_available = len(available)
    complex_obj.is_saved = complex_obj.pk in saved_ids

    # Chips: complex features, then amenities found in its units, furnishing last
    chips = complex_obj.feature_list()
    seen = set()
    for unit in priced:
        for amenity in unit.amenity_list():
            if amenity["key"] not in seen:
                seen.add(amenity["key"])
                chips.append(amenity)

    furnish_level = Counter(unit.furnish_level for unit in priced).most_common(1)[0][0]
    if furnish_level != "unfurnished":
        furnish_label = dict(Unit._meta.get_field("furnish_level").choices)[furnish_level]
        chips = chips[:MAX_CARD_CHIPS - 1] + [{"key": "furnished", "label": furnish_label}]

    complex_obj.card_chips = chips[:MAX_CARD_CHIPS]
    return complex_obj


def get_renter_listings_context(user):
    published_units = Prefetch(
        "units",
        queryset=Unit.objects.exclude(availability=Unit.Availability.UNPUBLISHED),
    )
    complexes = (
        renter_visible_complexes()
        .prefetch_related("pictures", published_units)
        .order_by("-created_at")
    )

    # Newest saved first
    saved_order = list(
        SavedListing.objects.filter(renter__user=user).values_list("complex_id", flat=True)
    )
    saved_ids = set(saved_order)

    # A complex with no published units has nothing to rent yet
    listings = [_decorate(c, saved_ids) for c in complexes if c.units.all()]

    saved_listings = sorted(
        (c for c in listings if c.is_saved),
        key=lambda c: saved_order.index(c.pk),
    )

    return {
        "listings": listings,
        "saved_listings": saved_listings,
    }