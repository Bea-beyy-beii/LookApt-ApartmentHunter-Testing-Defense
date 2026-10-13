"""The landlord's My Listings tab (a DashboardSection, see core/sections.py)."""
from core.sections import DashboardSection

from .services import get_listings_context


class ListingsSection(DashboardSection):

    def context(self):
        return get_listings_context(self.user)
