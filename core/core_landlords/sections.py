"""The landlord's Home tab (a DashboardSection, see core/sections.py).
Comes after the other sections, so it reuses their data from `shared`."""
from core.core_accounts.services import SignIn
from core.core_reports.services import SUPPORT_EMAIL
from core.sections import DashboardSection

from .services import home_context


class HomeSection(DashboardSection):

    def context(self):
        context = home_context(self.user, self.shared)
        context["support_email"] = SUPPORT_EMAIL
        context["first_visit"] = SignIn(self.request).first_visit
        return context
