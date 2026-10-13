"""
The landing page (/) and the two "try it first" previews:

    /preview/renter/    the renter dashboard, Home + Find Near only
    /preview/landlord/  the landlord dashboard, Home + My Listings only
                        (the Add Property form works, but can't be submitted)

The previews reuse the real dashboard templates with logged-out data.
preview.js turns every other click (other tabs, a listing, Save, Publish ...)
into a "Create an account" prompt.
"""
from abc import ABC, abstractmethod

from django.shortcuts import redirect
from django.views.generic import TemplateView

from core.core_listings.forms import ComplexForm
from core.core_renters.services import get_renter_listings_context
from core.core_reports.services import SUPPORT_EMAIL

from .access import PreviewAccess
from .demo import LandlordHomeDemo


class SignedOutOnlyMixin:
    """Signed-in users go straight to their own dashboard."""

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return redirect(request.user.home_url_name)
        return super().dispatch(request, *args, **kwargs)


class LandingView(SignedOutOnlyMixin, TemplateView):
    template_name = "core_preview/landing.html"
    extra_context = {"support_email": SUPPORT_EMAIL}


class PreviewView(SignedOutOnlyMixin, ABC, TemplateView):
    """One role's dashboard preview. Each subclass gives its tabs and its sample data."""

    preview = None        # 'renter' / 'landlord'
    tabs = ()

    def get(self, request, *args, **kwargs):
        PreviewAccess(request).start()
        return super().get(request, *args, **kwargs)

    @property
    def active_tab(self):
        """The ?tab= in the address, if this preview has it (otherwise Home)."""
        tab = self.request.GET.get("tab", "home")
        return tab if tab in self.tabs else "home"

    @abstractmethod
    def preview_context(self):
        """The dashboard data for this preview."""

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({
            "preview": self.preview,
            "preview_tabs": ",".join(self.tabs),
            "active_tab": self.active_tab,
            **self.preview_context(),
        })
        return context


class RenterPreviewView(PreviewView):
    template_name = "core_preview/renter_preview.html"
    preview = "renter"
    tabs = ("home", "findNear")

    def preview_context(self):
        return get_renter_listings_context(None, self.request.GET)   # every published listing, nothing saved


class LandlordPreviewView(PreviewView):
    template_name = "core_preview/landlord_preview.html"
    preview = "landlord"
    tabs = ("home", "myListings")

    def preview_context(self):
        return {
            # My Listings: no properties yet, an empty Add Property form
            "properties": [],
            "property_counts": {"all": 0, "active": 0, "unpublished": 0},
            "form": ComplexForm(),
            "property": None,
            "current_step": 1,
            # Verified, so no verification banner or pop-up
            "verification": {"state": "approved", "request": None, "can_submit": False, "show_welcome": False},
            "support_email": SUPPORT_EMAIL,
            **LandlordHomeDemo().context(),
        }
