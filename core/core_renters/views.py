# core_renters/views.py
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.shortcuts import render
from django.template.loader import render_to_string
from django.views.decorators.http import require_GET

from core.core_preview.access import is_previewing
from core.core_inquiries.services import get_inquiries_context
from core.core_reports.services import get_reports_context
from core.core_accounts.decorators import role_required
from core.core_rentals.services import get_renter_rentals_context
from .services import get_renter_listings_context


@role_required('renter')
def dashboard(request):
    active_tab = request.GET.get('tab', 'home')

    context = {
        'active_tab': active_tab,
    }
    
    context.update(get_inquiries_context(request.user))
    context.update(get_reports_context(request.user))
    context.update(get_renter_listings_context(request.user, request.GET))
    context.update(get_renter_rentals_context(request.user))

    return render(request, 'core_renters/renter_dashboard.html', context)


@require_GET
def search_listings(request):
    """Search bar / "Filter by" (renter_search.js): the Home and Saved Listings cards again,
    narrowed down. Also works in the renter preview (no account)."""
    if request.user.is_authenticated:
        if request.user.role != "renter":
            raise PermissionDenied
        user = request.user
    elif is_previewing(request):
        user = None
    else:
        raise PermissionDenied

    context = get_renter_listings_context(user, request.GET)

    def cards(listings, origin):
        return "".join(
            render_to_string("core_renters/partials/listing_card.html",
                             {"listing": listing, "origin": origin}, request=request)
            for listing in listings
        )

    return JsonResponse({
        "home_html": cards(context["listings"], "home"),
        "saved_html": cards(context["saved_listings"], "saved"),
        "home_count": len(context["listings"]),
        "saved_count": len(context["saved_listings"]),
        "filter_count": context["filter_count"],
    })
