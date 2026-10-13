# core_rentals/views.py
# JSON endpoints for the Manage Rentals tab (landlords only, their own units).
import json
from abc import ABC, abstractmethod
from datetime import date

from django.core.exceptions import ValidationError
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404
from django.views import View

from core.core_accounts.mixins import LandlordRequiredMixin
from core.core_inquiries.models import Application
from core.core_inquiries.services import today
from core.core_listings.models import Unit

from .models import Tenancy
from .services import TenantAssignment


class RentalActionView(LandlordRequiredMixin, View, ABC):
    """Base for every Manage Rentals action (POST only).

    Template method: post() reads the JSON body and turns a ValidationError
    into a 400; each subclass only says what to do in perform().
    """

    success_status = 200

    def post(self, request, *args, **kwargs):
        self.data = self._payload()
        try:
            message = self.perform(**kwargs)
        except ValidationError as error:
            return JsonResponse(
                {"errors": {f: " ".join(m) for f, m in error.message_dict.items()}}, status=400,
            )
        return JsonResponse({"message": message}, status=self.success_status)

    @abstractmethod
    def perform(self, **kwargs):
        """Do the action and return the success message."""

    def _payload(self):
        try:
            return json.loads(self.request.body or "{}")
        except ValueError:
            return {}

    @staticmethod
    def _date(value):
        try:
            return date.fromisoformat(value) if value else None
        except (TypeError, ValueError):
            return None


class AssignTenantView(RentalActionView):
    success_status = 201

    def post(self, request, *args, **kwargs):
        self.unit = get_object_or_404(
            Unit.objects.select_related("complex"), pk=kwargs["unit_pk"], complex__landlord__user=request.user,
        )
        return super().post(request, *args, **kwargs)

    def perform(self, **kwargs):
        unit, data = self.unit, self.data
        application = None
        if data.get("application"):
            application = (
                Application.objects.filter(pk=data["application"], unit=unit).select_related("renter__user").first()
            )
            if application is None:
                raise ValidationError({"application": "That application is no longer open."})

        tenancy = TenantAssignment.create(
            unit, self._date(data.get("start_date")), application=application,
            tenant_name=data.get("tenant_name", ""), occupant_count=data.get("occupant_count", 1),
        ).save()
        return f"{tenancy.tenant_name} is now the tenant of {unit.unit_name}."


class TenancyActionView(RentalActionView):
    """An action on one of the landlord's own tenancies (404 for anyone else's)."""

    def post(self, request, *args, **kwargs):
        try:
            self.tenancy = (
                Tenancy.objects.of_landlord(request.user)
                .select_related("unit__complex", "renter__user").get(pk=kwargs["pk"])
            )
        except (Tenancy.DoesNotExist, ValidationError):
            raise Http404
        return super().post(request, *args, **kwargs)


class MarkPaidView(TenancyActionView):

    def perform(self, **kwargs):
        count = self.tenancy.mark_paid(self.data.get("months"))
        return f"Marked {count} month{'s' if count != 1 else ''} as paid for {self.tenancy.unit.unit_name}."


class EndTenancyView(TenancyActionView):

    def perform(self, **kwargs):
        status = self.data.get("status")
        self.tenancy.end(status)
        word = "completed" if status == Tenancy.Status.COMPLETED else "terminated"
        return f"{self.tenancy.unit.unit_name}'s contract was {word} and moved to the Archive."


class RenewTenancyView(TenancyActionView):

    def perform(self, **kwargs):
        self.tenancy.renew()
        _, end = self.tenancy.current_term(today())
        return f"{self.tenancy.unit.unit_name}'s contract was renewed until {end:%b} {end.day}, {end.year}."
