# core_landlords/views.py
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.template.loader import render_to_string
from django.views.decorators.http import require_GET

from django.views.generic import TemplateView

from core.core_accounts.decorators import role_required
from core.core_accounts.mixins import LandlordRequiredMixin
from core.core_inquiries.sections import InquiriesSection
from core.core_inquiries.services import today
from core.core_listings.sections import ListingsSection
from core.core_rentals.sections import RentalsSection
from core.core_reports.sections import ReportsSection
from core.core_verification.sections import VerificationSection
from core.sections import SectionedDashboardMixin

from . import services
from .export import receivables_pdf
from .sections import HomeSection


class DashboardView(LandlordRequiredMixin, SectionedDashboardMixin, TemplateView):
    """The landlord dashboard: every tab's data comes from its app's section."""
    template_name = 'core_landlords/landlord_dashboard.html'
    sections = (InquiriesSection, ReportsSection, ListingsSection, RentalsSection, HomeSection, VerificationSection)


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