"""The landlord's Home tab (a DashboardSection, see core/sections.py).
Comes after the other sections, so it reuses their data from `shared`
(Manage Rentals' rental groups, the Inquiries tab's pending requests ...)."""
import json

from core.core_accounts.services import AccountService
from core.core_inquiries.services import today
from core.core_reports.services import SUPPORT_EMAIL
from core.sections import DashboardSection

from .services import (
    ContractsEndingSoon, OverdueRent, PendingRequests, PerformanceChart, ReceivablesReport, SiteVisitsToConfirm,
    VacantWithWaitlist,
)


class HomeSection(DashboardSection):
    """The 4 cards, Monthly Receivables, Listing Performance, Needs Your Attention and Managed Properties."""

    # Needs Your Attention, in this order (each one shows only when there's something to do)
    ATTENTION_CHECKS = (OverdueRent, PendingRequests, SiteVisitsToConfirm, ContractsEndingSoon, VacantWithWaitlist)

    def context(self):
        on = today()
        user = self.user
        chart = PerformanceChart(user, on, on).as_dict()
        return {
            "home": self._summary(on),
            "receivables": ReceivablesReport(user, on, on).as_dict(),
            "performance": chart,
            "performance_json": json.dumps(chart),
            "support_email": SUPPORT_EMAIL,
            "first_visit": self.request.session.get(AccountService.FIRST_VISIT, False),
        }

    @property
    def _groups(self):
        return self.shared["rental_groups"]

    @property
    def _units(self):
        return [u for g in self._groups for u in g["units"]]

    def _attention(self, on):
        rows = (check(self.shared, on).item() for check in self.ATTENTION_CHECKS)
        return [row for row in rows if row]

    @staticmethod
    def _property_card(group):
        stats = group["stats"]
        return {
            "complex": group["complex"],
            "cover_url": group["cover_url"],
            "units": stats["total"],
            "occupied": stats["occupied"],
            "vacant": stats["vacant"],
            "percent": round(stats["occupied"] * 100 / stats["total"]) if stats["total"] else 0,
        }

    def _summary(self, on):
        user, units = self.user, self._units
        occupied = sum(1 for u in units if u.state == "occupied")
        return {
            "first_name": user.first_name.split()[0].title() if user.first_name else user.display_name,
            "properties_count": len(self._groups),
            "units_count": len(units),
            "occupied": occupied,
            "occupancy": round(occupied * 100 / len(units)) if units else 0,
            "overdue_units": sum(1 for u in units if u.tenancy and u.tenancy.pay["key"] == "overdue"),
            "attention": self._attention(on),
            "properties": [self._property_card(group) for group in self._groups],
        }
