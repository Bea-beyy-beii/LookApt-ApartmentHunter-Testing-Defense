"""The renter's Home and Saved Listings tabs (a DashboardSection, see core/sections.py).
Also used by the search endpoint and the renter preview (user=None)."""
from core.sections import DashboardSection

from .search import ListingSearch
from .services import ListingCards


class RenterListingsSection(DashboardSection):
    """Home + Saved Listings cards, narrowed by the search bar / "Filter by" values (request.GET)."""

    def context(self):
        search = ListingSearch(self.request.GET if self.request else None)
        listings, saved_listings = ListingCards(self.user).search(search)
        return {
            "listings": listings,
            "saved_listings": saved_listings,
            "search": search.filters,
            "search_active": search.is_active,
            "filter_count": search.filter_count,
            "filter_options": ListingSearch.options(),
        }
