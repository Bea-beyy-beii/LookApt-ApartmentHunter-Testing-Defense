# core_renters/views.py
from django.shortcuts import render
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
    context.update(get_renter_listings_context(request.user))
    context.update(get_renter_rentals_context(request.user))

    return render(request, 'core_renters/renter_dashboard.html', context)