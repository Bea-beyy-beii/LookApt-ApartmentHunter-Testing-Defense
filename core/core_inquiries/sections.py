"""The Inquiries tab of both dashboards (a DashboardSection, see core/sections.py)."""
from core.sections import DashboardSection

from .services import get_inquiries_context


class InquiriesSection(DashboardSection):

    def context(self):
        return get_inquiries_context(self.user)
