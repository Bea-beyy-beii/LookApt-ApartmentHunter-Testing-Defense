# core_renters/services.py
# Listing cards on the renter dashboard (Home + Saved Listings tabs).
from django.db.models import Prefetch

from core.core_listings.models import Complex, SavedListing, Unit

from .search import active_filter_count, filter_complexes, filter_options, filter_units, parse_filters, sort_listings

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


def _published_units(filters=None):
    """Prefetch a complex's published units (only those matching the unit filters, if any)."""
    units = Unit.objects.exclude(availability=Unit.Availability.UNPUBLISHED)
    return Prefetch("units", queryset=filter_units(units, filters) if filters else units)


def _saved_ids(user):
    return list(SavedListing.objects.filter(renter__user=user).values_list("complex_id", flat=True))


def landlord_other_listings(complex_obj, user):
    """The listing page's "Other Listings" tab: the landlord's other complexes, as cards."""
    complexes = (
        Complex.objects.renter_visible()
        .filter(landlord=complex_obj.landlord)
        .exclude(pk=complex_obj.pk)
        .prefetch_related("pictures", _published_units())
        .order_by("-created_at")
    )
    saved_ids = set(_saved_ids(user))
    return [_decorate(c, saved_ids) for c in complexes if c.units.all()]


def get_renter_listings_context(user, params=None):
    """Home + Saved Listings cards. params = the search bar / "Filter by" values (request.GET)."""
    filters = parse_filters(params or {})

    # Only the published units that match the unit filters (type, budget, occupants ...)
    complexes = (
        filter_complexes(Complex.objects.renter_visible(), filters)
        .prefetch_related("pictures", _published_units(filters))
        .order_by("-created_at")
    )

    # Newest saved first
    saved_order = _saved_ids(user)
    saved_ids = set(saved_order)

    # A complex with no (matching) published units has nothing to rent yet
    listings = sort_listings([_decorate(c, saved_ids) for c in complexes if c.units.all()], filters["sort"])

    saved_listings = sorted(
        (c for c in listings if c.is_saved),
        key=lambda c: saved_order.index(c.pk),
    )
    if filters["sort"] != "newest":
        saved_listings = sort_listings(saved_listings, filters["sort"])

    return {
        "listings": listings,
        "saved_listings": saved_listings,
        "search": filters,
        "search_active": bool(filters["q"]) or active_filter_count(filters) > 0,
        "filter_count": active_filter_count(filters),
        "filter_options": filter_options(),
    }