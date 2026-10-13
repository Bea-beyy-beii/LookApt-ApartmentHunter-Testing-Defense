"""The verification banner / pop-up on the landlord dashboard (a DashboardSection, see core/sections.py)."""
from core.sections import DashboardSection

from .forms import VerificationForm
from .services import DocumentPurge, LandlordVerification


class VerificationSection(DashboardSection):
    """The pop-up, the banner and the welcome message."""

    def context(self):
        DocumentPurge().run_daily()
        verification = LandlordVerification(self.user)
        state = verification.state
        return {
            "verification": {
                "state": state,
                "request": verification.latest,
                "can_submit": verification.can_submit,
                "show_welcome": verification.show_welcome,
            },
            "verification_form": VerificationForm(),
            "verification_max_mb": VerificationForm.MAX_FILE_MB,
        }
