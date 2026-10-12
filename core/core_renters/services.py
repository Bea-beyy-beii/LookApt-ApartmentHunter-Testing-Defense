# core_renters/services.py
# Listing cards on the renter dashboard (Home + Saved Listings tabs).
from django.db.models import Prefetch

from core.core_listings.models import SavedListing, Unit
from core.core_listings.services import renter_visible_complexes

MAX_CARD_CHIPS = 4      # complex features only (unit amenities are on the listing page)


def _decorate(complex_obj, saved_ids):
    """Add the values the card shows: price, availability badge, feature chips, saved state."""
    units = list(complex_obj.units.all())   # published units only (see the Prefetch below)
    available = [unit for unit in units if unit.availability == Unit.Availability.AVAILABLE]
    priced = available or units

    complex_obj.card_price = min(unit.price for unit in priced)
    complex_obj.card_available = len(available)
    complex_obj.is_saved = complex_obj.pk in saved_ids

    # Chips: the complex's own features (Pet Friendly, CCTV ...), up to 4
    complex_obj.card_chips = complex_obj.feature_list()[:MAX_CARD_CHIPS]
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