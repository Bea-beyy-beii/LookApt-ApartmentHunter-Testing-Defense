"""The Reports Filed tab of both dashboards (a DashboardSection, see core/sections.py)."""
from collections import Counter

from core.sections import DashboardSection

from .services import SUPPORT_EMAIL, EvidenceFile, Reporter


class ReportsSection(DashboardSection):
    """The same tab for renters and landlords: the Reporter subclass decides
    the reasons and who can be reported."""

    STATUS_TABS = [
        ("waiting", "Pending", "clock"),
        ("reviewing", "Under Review", "document"),
        ("resolved", "Resolved", "check"),
        ("dismissed", "Closed", "info"),
    ]

    def context(self):
        reporter = Reporter.for_user(self.user)
        reports = reporter.reports()
        counts = Counter(r.status for r in reports)
        return {
            "reports": reports,
            "report_tabs": [
                {"value": value, "label": label, "icon": icon, "count": counts.get(value, 0)}
                for value, label, icon in self.STATUS_TABS
            ],
            "report_people": reporter.reportable_people(),
            "report_categories": reporter.categories,
            "report_target": reporter.target,
            "report_support_email": SUPPORT_EMAIL,
            "report_max_files": reporter.MAX_FILES,
            "report_max_mb": EvidenceFile.MAX_MB,
        }
