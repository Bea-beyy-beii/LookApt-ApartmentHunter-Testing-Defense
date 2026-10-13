# core_landlords/views.py
from django.http import HttpResponse, JsonResponse
from django.template.loader import render_to_string
from django.views import View
from django.views.generic import TemplateView

from core.core_accounts.mixins import LandlordRequiredMixin
from core.core_inquiries.sections import InquiriesSection
from core.core_inquiries.services import today
from core.core_listings.sections import ListingsSection
from core.core_rentals.sections import RentalsSection
from core.core_reports.sections import ReportsSection
from core.core_verification.sections import VerificationSection
from core.sections import SectionedDashboardMixin

from .export import ReceivablesPdf
from .sections import HomeSection
from .services import Month, PerformanceChart, ReceivablesReport


class DashboardView(LandlordRequiredMixin, SectionedDashboardMixin, TemplateView):
    """The landlord dashboard: every tab's data comes from its app's section."""
    template_name = 'core_landlords/landlord_dashboard.html'
    sections = (InquiriesSection, ReportsSection, ListingsSection, RentalsSection, HomeSection, VerificationSection)


class MonthView(LandlordRequiredMixin, View):
    """Base for the Home tab's GET endpoints that show one ?month=YYYY-MM (default: this month)."""

    @property
    def month(self):
        return Month.parse(self.request.GET.get('month'), today()).first


class ReceivablesPanelView(MonthView):
    """Monthly Receivables drawer for ?month=YYYY-MM (the < > arrows)."""

    def get(self, request):
        html = render_to_string(
            'core_landlords/home/receivables_panel.html',
            {'receivables': ReceivablesReport(request.user, self.month).as_dict()},
            request=request,
        )
        return JsonResponse({'html': html})


class ExportReceivablesView(MonthView):
    """Export Financials: the Monthly Receivables of ?month=YYYY-MM (default: this month) as a PDF."""

    def get(self, request):
        report = ReceivablesReport(request.user, self.month)
        response = HttpResponse(ReceivablesPdf(report).render(), content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="LookApt-receivables-{report.month.value}.pdf"'
        return response


class PerformanceDataView(MonthView):
    """Listing Performance chart for ?month=YYYY-MM (the month dropdown)."""

    def get(self, request):
        return JsonResponse(PerformanceChart(request.user, self.month).as_dict())
