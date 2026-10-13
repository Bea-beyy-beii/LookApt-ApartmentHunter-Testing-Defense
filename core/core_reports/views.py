# core_reports/views.py
# "File a Report" (renters + landlords). The page itself is part of each
# dashboard (core_reports.sections.ReportsSection).
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.views import View

from core.core_admin.notify import ReportReceived
from core.core_verification.services import NOT_VERIFIED_TO_POST, LandlordVerification

from .services import Reporter


class CreateReportView(LoginRequiredMixin, View):

    def post(self, request):
        user = request.user
        if user.role not in ("renter", "landlord"):
            return JsonResponse({"errors": {"__all__": "Only renters and landlords can file reports."}}, status=403)
        if LandlordVerification(user).must_verify:
            return JsonResponse({"errors": {"__all__": NOT_VERIFIED_TO_POST}}, status=403)
        data = request.POST
        try:
            report = Reporter.for_user(user).file_report(
                reported_id=data.get("reported_user"),
                category=data.get("category"),
                description=data.get("description"),
                other_text=data.get("other_category_text"),
                files=request.FILES.getlist("evidence"),
            )
        except ValidationError as error:
            return JsonResponse({"errors": {f: " ".join(m) for f, m in error.message_dict.items()}}, status=400)
        ReportReceived(report).send()
        return JsonResponse({
            "message": f"Your report about {report.reported_user.display_name} was sent. We'll review it soon.",
        }, status=201)
