"""The renter's Home and Saved Listings tabs (a DashboardSection, see core/sections.py)."""
from core.sections import DashboardSection

from .services import get_renter_listings_context


class RenterListingsSection(DashboardSection):

    def context(self):
        return get_renter_listings_context(self.user, self.request.GET if self.request else None)
