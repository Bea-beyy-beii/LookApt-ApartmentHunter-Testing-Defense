"""
Terms and Conditions + Privacy Notice (templates/core_accounts/legal/).

Changing the text? Bump TERMS_VERSION and EFFECTIVE_DATE: each account records
the version it agreed to at sign-up (User.terms_version / terms_accepted_at).
"""
from datetime import date

TERMS_VERSION = "2026-10-13"
EFFECTIVE_DATE = date(2026, 10, 13)


class LegalContextMixin:
    """For views whose page shows the Terms / Privacy text (terms_body.html, privacy_body.html)."""

    def get_context_data(self, **kwargs):
        from core.core_reports.services import SUPPORT_EMAIL
        context = super().get_context_data(**kwargs)
        context.update(legal_effective_date=EFFECTIVE_DATE, support_email=SUPPORT_EMAIL)
        return context
