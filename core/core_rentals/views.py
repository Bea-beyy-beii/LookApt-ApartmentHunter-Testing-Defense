# core_rentals/views.py
# JSON endpoints for the Manage Rentals tab (landlords only, their own units).
import json
from datetime import date

from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_POST

from core.core_accounts.decorators import role_required
from core.core_inquiries.models import Application
from core.core_listings.models import Unit

from . import services
from .models import Tenancy


def _payload(request):
    try:
        return json.loads(request.body or "{}")
    except ValueError:
        return {}


def _date(value):
    try:
        return date.fromisoformat(value) if value else None
    except (TypeError, ValueError):
        return None


def _errors(error):
    return JsonResponse({"errors": {f: " ".join(m) for f, m in error.message_dict.items()}}, status=400)


def _own_tenancy(request, pk):
    try:
        return services.landlord_tenancy(request.user, pk)
    except (ObjectDoesNotExist, ValidationError):
        raise Http404


@role_required("landlord")
@require_POST
def assign_tenant(request, unit_pk):
    unit = get_object_or_404(Unit.objects.select_related("complex"), pk=unit_pk, complex__landlord__user=request.user)
    data = _payload(request)

    application = None
    if data.get("application"):
        application = Application.objects.filter(pk=data["application"], unit=unit).select_related("renter__user").first()
        if application is None:
            return JsonResponse({"errors": {"application": "That application is no longer open."}}, status=400)

    try:
        tenancy = services.assign_tenant(
            unit, _date(data.get("start_date")), application=application,
            tenant_name=data.get("tenant_name", ""), occupant_count=data.get("occupant_count", 1),
        )
    except ValidationError as error:
        return _errors(error)
    return JsonResponse({"message": f"{tenancy.tenant_name} is now the tenant of {unit.unit_name}."}, status=201)


@role_required("landlord")
@require_POST
def mark_paid(request, pk):
    tenancy = _own_tenancy(request, pk)
    try:
        count = services.mark_paid(tenancy, _payload(request).get("months"))
    except ValidationError as error:
        return _errors(error)
    return JsonResponse({"message": f"Marked {count} month{'s' if count != 1 else ''} as paid for {tenancy.unit.unit_name}."})


@role_required("landlord")
@require_POST
def end_tenancy(request, pk):
    tenancy = _own_tenancy(request, pk)
    status = _payload(request).get("status")
    try:
        services.end_tenancy(tenancy, status)
    except ValidationError as error:
        return _errors(error)
    word = "completed" if status == Tenancy.Status.COMPLETED else "terminated"
    return JsonResponse({"message": f"{tenancy.unit.unit_name}'s contract was {word} and moved to the Archive."})



@role_required("landlord")
@require_POST
def renew_tenancy(request, pk):
    tenancy = _own_tenancy(request, pk)
    try:
        services.renew_tenancy(tenancy)
    except ValidationError as error:
        return _errors(error)
    _, end = services.current_term(tenancy, services.today())
    return JsonResponse({"message": f"{tenancy.unit.unit_name}'s contract was renewed until {end:%b} {end.day}, {end.year}."})