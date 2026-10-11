# core_reports/views.py
# "File a Report" (renters + landlords). The page itself is part of each
# dashboard (core_reports.services.get_reports_context).
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.views.decorators.http import require_POST

from core.core_admin import notify
from core.core_verification.services import NOT_VERIFIED_TO_POST, landlord_must_verify

from . import services


@login_required
@require_POST
def create_report(request):
    if request.user.role not in ("renter", "landlord"):
        return JsonResponse({"errors": {"__all__": "Only renters and landlords can file reports."}}, status=403)
    if landlord_must_verify(request.user):
        return JsonResponse({"errors": {"__all__": NOT_VERIFIED_TO_POST}}, status=403)
    data = request.POST
    try:
        report = services.file_report(
            request.user,
            reported_id=data.get("reported_user"),
            category=data.get("category"),
            description=data.get("description"),
            other_text=data.get("other_category_text"),
            files=request.FILES.getlist("evidence"),
        )
    except ValidationError as error:
        return JsonResponse({"errors": {f: " ".join(m) for f, m in error.message_dict.items()}}, status=400)
    notify.report_received(report)
    return JsonResponse({
        "message": f"Your report about {report.reported_user.display_name} was sent. We'll review it soon.",
    }, status=201)