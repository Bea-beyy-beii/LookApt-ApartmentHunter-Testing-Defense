"""Manage Rentals (landlord) and Rental History (renter) (DashboardSections, see core/sections.py)."""
from core.sections import DashboardSection

from .services import get_rentals_context, get_renter_rentals_context


class RentalsSection(DashboardSection):

    def context(self):
        return get_rentals_context(self.user)


class RenterRentalsSection(DashboardSection):

    def context(self):
        return get_renter_rentals_context(self.user)
