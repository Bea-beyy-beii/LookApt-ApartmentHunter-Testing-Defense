"""The verification banner / pop-up on the landlord dashboard (a DashboardSection, see core/sections.py)."""
from core.sections import DashboardSection

from .services import verification_context


class VerificationSection(DashboardSection):

    def context(self):
        return verification_context(self.user)
