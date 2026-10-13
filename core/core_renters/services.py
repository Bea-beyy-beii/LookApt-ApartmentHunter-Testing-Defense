# core_renters/services.py
# Listing cards on the renter dashboard (Home + Saved Listings tabs) and the
# listing page's "Other Listings" tab.
from django.db.models import Prefetch

from core.core_listings.models import SavedListing, Unit
from core.core_listings.services import renter_visible_complexes


class ListingCards:
    """Listing cards as one renter sees them (user=None: the preview, nothing saved).

        cards = ListingCards(user)
        cards.search(ListingSearch(request.GET))   # Home tab
        cards.other_listings(complex_obj)          # listing page
    """

    MAX_CARD_CHIPS = 4      # complex features only (unit amenities are on the listing page)

    def __init__(self, user):
        self.user = user
        # Newest saved first
        self.saved_order = list(SavedListing.objects.filter(renter__user=user).values_list("complex_id", flat=True))
        self.saved_ids = set(self.saved_order)

    @staticmethod
    def _published_units(search=None):
        """Prefetch a complex's published units (only those matching the unit filters, if any)."""
        units = Unit.objects.exclude(availability=Unit.Availability.UNPUBLISHED)
        return Prefetch("units", queryset=search.filter_units(units) if search else units)

    def _decorate(self, complex_obj):
        """Add the values the card shows: price, availability badge, feature chips, saved state."""
        units = list(complex_obj.units.all())   # published units only (see _published_units)
        available = [unit for unit in units if unit.availability == Unit.Availability.AVAILABLE]
        priced = available or units

        complex_obj.card_price = min(unit.price for unit in priced)
        complex_obj.card_available = len(available)
        complex_obj.is_saved = complex_obj.pk in self.saved_ids

        # Chips: the complex's own features (Pet Friendly, CCTV ...), up to 4
        complex_obj.card_chips = complex_obj.feature_list()[:self.MAX_CARD_CHIPS]
        return complex_obj

    def _cards(self, complexes):
        # A complex with no (matching) published units has nothing to rent yet
        return [self._decorate(c) for c in complexes if c.units.all()]

    def other_listings(self, complex_obj):
        """The listing page's "Other Listings" tab: the landlord's other complexes, as cards."""
        complexes = (
            renter_visible_complexes()
            .filter(landlord=complex_obj.landlord)
            .exclude(pk=complex_obj.pk)
            .prefetch_related("pictures", self._published_units())
            .order_by("-created_at")
        )
        return self._cards(complexes)

    def search(self, search):
        """(every matching card, the saved ones) for the Home and Saved Listings tabs."""
        # Only the published units that match the unit filters (type, budget, occupants ...)
        complexes = (
            search.filter_complexes(renter_visible_complexes())
            .prefetch_related("pictures", self._published_units(search))
            .order_by("-created_at")
        )
        listings = search.order(self._cards(complexes))

        saved = sorted((c for c in listings if c.is_saved), key=lambda c: self.saved_order.index(c.pk))
        if search.sort != "newest":
            saved = search.order(saved)
        return listings, saved
