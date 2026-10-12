# core_landlords/views.py
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.template.loader import render_to_string
from django.views.decorators.http import require_GET

from core.core_accounts.decorators import role_required
from core.core_inquiries.services import get_inquiries_context, today
from core.core_listings.services import get_listings_context
from core.core_rentals.services import get_rentals_context
from core.core_reports.services import SUPPORT_EMAIL, get_reports_context
from core.core_verification.services import verification_context

from . import services
from .export import receivables_pdf


@role_required('landlord')
def dashboard(request):
    active_tab = request.GET.get('tab', 'home')

    context = {
        'active_tab': active_tab,
    }

    context.update(get_inquiries_context(request.user))
    context.update(get_reports_context(request.user))
    context.update(get_listings_context(request.user))
    context.update(get_rentals_context(request.user))
    context.update(services.home_context(request.user, context))
    context.update(verification_context(request.user))
    context['support_email'] = SUPPORT_EMAIL

    return render(request, 'core_landlords/landlord_dashboard.html', context)


@role_required('landlord')
@require_GET
def receivables_panel(request):
    """Monthly Receivables drawer for ?month=YYYY-MM (the < > arrows)."""
    month = services.parse_month(request.GET.get('month'), today())
    html = render_to_string(
        'core_landlords/home/receivables_panel.html',
        {'receivables': services.receivables(request.user, month)},
        request=request,
    )
    return JsonResponse({'html': html})


@role_required('landlord')
@require_GET
def export_receivables(request):
    """Export Financials: the Monthly Receivables of ?month=YYYY-MM (default: this month) as a PDF."""
    month = services.parse_month(request.GET.get('month'), today())
    r = services.receivables(request.user, month)
    response = HttpResponse(receivables_pdf(request.user, r), content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="LookApt-receivables-{r["month_value"]}.pdf"'
    return response


@role_required('landlord')
@require_GET
def performance_data(request):
    """Listing Performance chart for ?month=YYYY-MM (the month dropdown)."""
    month = services.parse_month(request.GET.get('month'), today())
    return JsonResponse(services.performance(request.user, month))