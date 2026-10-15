# core_renters/views.py
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.template.loader import render_to_string
from django.views import View
from django.views.generic import TemplateView

from core.core_accounts.mixins import RenterRequiredMixin
from core.core_accounts.throttle import RateLimitMixin
from core.core_inquiries.sections import InquiriesSection
from core.core_preview.access import PreviewAccess
from core.core_rentals.sections import RenterRentalsSection
from core.core_reports.sections import ReportsSection
from core.sections import SectionedDashboardMixin
from .sections import RenterListingsSection


class DashboardView(RenterRequiredMixin, SectionedDashboardMixin, TemplateView):
    """The renter dashboard: every tab's data comes from its app's section."""
    template_name = 'core_renters/renter_dashboard.html'
    sections = (InquiriesSection, ReportsSection, RenterListingsSection, RenterRentalsSection)


class SearchListingsView(RateLimitMixin, View):
    """Search bar / "Filter by" (renter_search.js): the Home and Saved Listings cards again,
    narrowed down. Also works in the renter preview (no account)."""

    def _viewer(self):
        """The renter searching, None in the preview; anyone else gets a 403."""
        user = self.request.user
        if user.is_authenticated:
            if user.role != "renter":
                raise PermissionDenied
            return user
        if PreviewAccess(self.request).is_previewing:
            return None
        raise PermissionDenied

    def _cards(self, listings, origin):
        return "".join(
            render_to_string("core_renters/partials/listing_card.html",
                             {"listing": listing, "origin": origin}, request=self.request)
            for listing in listings
        )

    def get(self, request):
        context = RenterListingsSection(self._viewer(), request).context()
        return JsonResponse({
            "home_html": self._cards(context["listings"], "home"),
            "saved_html": self._cards(context["saved_listings"], "saved"),
            "home_count": len(context["listings"]),
            "saved_count": len(context["saved_listings"]),
            "filter_count": context["filter_count"],
        })
