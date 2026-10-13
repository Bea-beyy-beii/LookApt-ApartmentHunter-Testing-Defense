# core_calendar/views.py
import json
from datetime import date, time

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET, require_POST

from core.core_accounts.decorators import role_required
from core.core_verification.services import NOT_VERIFIED_TO_POST, LandlordVerification

from . import services


def calendar(request):
    return render(
        request,
        "core_calendar/calendar.html"
    )


def _date(value):
    try:
        return date.fromisoformat(value) if value else None
    except (TypeError, ValueError):
        return None


def _time(value):
    try:
        return time.fromisoformat(value) if value else None
    except (TypeError, ValueError):
        return None


@login_required
@require_GET
def events_api(request):
    """Calendar items between ?start= and ?end= (YYYY-MM-DD), for the logged-in user."""
    start, end = _date(request.GET.get("start")), _date(request.GET.get("end"))
    if not start or not end or end < start:
        return JsonResponse({"errors": {"__all__": "Give a start and end date."}}, status=400)
    return JsonResponse({"items": services.calendar_items(request.user, start, end)})


@role_required("landlord")
@require_POST
def post_bulletin(request):
    if LandlordVerification(request.user).must_verify:
        return JsonResponse({"errors": {"__all__": NOT_VERIFIED_TO_POST}}, status=403)
    try:
        data = json.loads(request.body or "{}")
    except ValueError:
        data = {}

    complex_ids = None if data.get("audience") != "some" else [str(pk) for pk in data.get("complexes") or []]
    try:
        event, sent = services.post_bulletin(
            request.user,
            message=data.get("message"),
            complex_ids=complex_ids,
            event_date=_date(data.get("event_date")),
            start_time=_time(data.get("start_time")),
            end_time=_time(data.get("end_time")),
            event_title=data.get("event_title", ""),
            event_type=data.get("event_type") or "announcement",
            whole_week=bool(data.get("whole_week")),
        )
    except ValidationError as error:
        return JsonResponse({"errors": {f: " ".join(m) for f, m in error.message_dict.items()}}, status=400)

    parts = []
    if sent:
        parts.append(f"sent to {sent} tenant{'s' if sent != 1 else ''}")
    if event:
        parts.append("added to the calendar")
    return JsonResponse({"message": "Bulletin " + " and ".join(parts) + "."}, status=201)