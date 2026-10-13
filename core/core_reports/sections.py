"""The Reports Filed tab of both dashboards (a DashboardSection, see core/sections.py)."""
from core.sections import DashboardSection

from .services import get_reports_context


class ReportsSection(DashboardSection):

    def context(self):
        return get_reports_context(self.user)
