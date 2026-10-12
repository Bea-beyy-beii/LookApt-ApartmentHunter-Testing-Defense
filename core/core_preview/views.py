"""
The landing page (/) and the two "try it first" previews:

    /preview/renter/    the renter dashboard, Home + Find Near only
    /preview/landlord/  the landlord dashboard, Home + My Listings only
                        (the Add Property form works, but can't be submitted)

The previews reuse the real dashboard templates with logged-out data.
preview.js turns every other click (other tabs, a listing, Save, Publish ...)
into a "Create an account" prompt.
"""
from django.shortcuts import redirect, render

from core.core_accounts.views import ROLE_HOME
from core.core_listings.forms import ComplexForm
from core.core_renters.services import get_renter_listings_context
from core.core_reports.services import SUPPORT_EMAIL

from . import demo
from .access import start_preview

RENTER_TABS = ("home", "findNear")
LANDLORD_TABS = ("home", "myListings")


def _signed_in_home(request):
    """Signed-in users go straight to their own dashboard."""
    if request.user.is_authenticated:
        return redirect(ROLE_HOME.get(request.user.role, "login"))
    return None


def landing(request):
    return _signed_in_home(request) or render(request, "core_preview/landing.html", {
        "support_email": SUPPORT_EMAIL,
    })


def _tab(request, allowed):
    tab = request.GET.get("tab", "home")
    return tab if tab in allowed else "home"


def renter_preview(request):
    if response := _signed_in_home(request):
        return response
    start_preview(request)
    return render(request, "core_preview/renter_preview.html", {
        "preview": "renter",
        "preview_tabs": ",".join(RENTER_TABS),
        "active_tab": _tab(request, RENTER_TABS),
        **get_renter_listings_context(None),          # every published listing, nothing saved
    })


def landlord_preview(request):
    if response := _signed_in_home(request):
        return response
    start_preview(request)
    return render(request, "core_preview/landlord_preview.html", {
        "preview": "landlord",
        "preview_tabs": ",".join(LANDLORD_TABS),
        "active_tab": _tab(request, LANDLORD_TABS),
        # My Listings: no properties yet, an empty Add Property form
        "properties": [],
        "property_counts": {"all": 0, "active": 0, "unpublished": 0},
        "form": ComplexForm(),
        "property": None,
        "current_step": 1,
        # Verified, so no verification banner or pop-up
        "verification": {"state": "approved", "request": None, "can_submit": False, "show_welcome": False},
        "support_email": SUPPORT_EMAIL,
        **demo.landlord_home(),
    })