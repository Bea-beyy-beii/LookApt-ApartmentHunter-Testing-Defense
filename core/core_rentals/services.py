# core_rentals/services.py
# Assigning a tenant to a unit (Manage Rentals -> "Assign a Renter", and
# Inquiries -> "Approve as Tenant"). Everything about one tenancy after that
# (rent, renew, end) lives on the Tenancy model.
from abc import ABC, abstractmethod
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from core.core_inquiries.models import Application
from core.core_inquiries.services import today
from core.core_listings.models import Unit

from .models import Tenancy


class TenantAssignment(ABC):
    """Make someone the unit's tenant.

    Polymorphism: a LookApt applicant (ApplicantAssignment) and a typed name for
    people not on the app (NamedTenantAssignment) are checked and recorded a bit
    differently; save() is the same for both.

        TenantAssignment.create(unit, start_date, application=...).save()
    """

    MAX_YEARS_AGO = 5
    application = None        # set by ApplicantAssignment

    def __init__(self, unit, start_date, on=None):
        self.unit = unit
        self.start_date = start_date
        self.on = on or today()

    @classmethod
    def create(cls, unit, start_date, application=None, tenant_name="", occupant_count=1, on=None):
        """The right kind of assignment for what the landlord picked."""
        if application:
            return ApplicantAssignment(unit, start_date, application, on)
        return NamedTenantAssignment(unit, start_date, tenant_name, occupant_count, on)

    @abstractmethod
    def _tenant(self):
        """(renter or None, primary tenant's name, occupants). Raises ValidationError."""

    @abstractmethod
    def _other_requests(self, open_requests):
        """The unit's open requests that move to the Archive now that it's rented."""

    def _accept(self, now):
        """Anything else to record once the tenancy exists (nothing by default)."""

    def _check(self):
        unit, start = self.unit, self.start_date
        if unit.availability == Unit.Availability.UNPUBLISHED:
            raise ValidationError({"__all__": "Publish this unit before assigning a renter."})
        if unit.tenancies.active().exists():
            raise ValidationError({"__all__": f"{unit.unit_name} already has a tenant. End that contract first."})
        if not start:
            raise ValidationError({"start_date": "Pick the date the rental starts."})
        if start > self.on + timedelta(days=365):
            raise ValidationError({"start_date": "The start date can't be more than a year away."})
        if start < self.on - timedelta(days=self.MAX_YEARS_AGO * 365):
            raise ValidationError({"start_date": "The start date can't be more than 5 years ago."})

    @transaction.atomic
    def save(self):
        self._check()
        renter, name, occupants = self._tenant()
        unit = self.unit

        tenancy = Tenancy(
            unit=unit, renter=renter, application=self.application, tenant_name=name,
            occupants=occupants, monthly_rent=unit.price, start_date=self.start_date,
        )
        tenancy.end_date = tenancy.first_term_end
        try:
            tenancy.save(force_insert=True)
        except IntegrityError:
            raise ValidationError({"__all__": f"{unit.unit_name} already has a tenant."})

        now = timezone.now()
        self._accept(now)
        # The vacancy is filled: other requests (pending or waitlisted) move to the Archive.
        self._other_requests(unit.applications.filter(status__in=Application.OPEN_STATUSES)).update(
            status=Application.Status.CLOSED, reason=Application.Reason.UNIT_RENTED,
            reason_note="", decided_at=now, updated_at=now,
        )

        unit.availability = Unit.Availability.OCCUPIED
        unit.occupied_since = self.start_date
        unit.save(update_fields=["availability", "occupied_since", "updated_at"])
        return tenancy


class ApplicantAssignment(TenantAssignment):
    """A renter who applied for / joined the waitlist of this unit on LookApt."""

    def __init__(self, unit, start_date, application, on=None):
        super().__init__(unit, start_date, on)
        self.application = application

    def _tenant(self):
        application = self.application
        if application.unit_id != self.unit.pk or not application.is_open:
            raise ValidationError({"application": "That application is no longer open."})
        renter = application.renter
        name = renter.user.display_name
        return renter, name, list(application.occupants) or [name]

    def _accept(self, now):
        self.application.status = Application.Status.ACCEPTED
        self.application.decided_at = now
        self.application.save(update_fields=["status", "decided_at", "updated_at"])

    def _other_requests(self, open_requests):
        return open_requests.exclude(pk=self.application.pk)


class NamedTenantAssignment(TenantAssignment):
    """Someone who isn't on LookApt: only the primary tenant's name is known."""

    MAX_NAME_LENGTH = 150

    def __init__(self, unit, start_date, tenant_name="", occupant_count=1, on=None):
        super().__init__(unit, start_date, on)
        self.tenant_name = tenant_name
        self.occupant_count = occupant_count

    def _tenant(self):
        name = (self.tenant_name or "").strip()
        if not name:
            raise ValidationError({"tenant_name": "Pick an applicant or type the tenant's full name."})
        if len(name) > self.MAX_NAME_LENGTH:
            raise ValidationError({"tenant_name": f"Names can be up to {self.MAX_NAME_LENGTH} characters."})
        try:
            count = int(self.occupant_count)
        except (TypeError, ValueError):
            count = 0
        if not 1 <= count <= self.unit.max_occupant:
            raise ValidationError(
                {"occupant_count": f"{self.unit.unit_name} allows 1 to {self.unit.max_occupant} occupants."}
            )
        return None, name, [name] + [""] * (count - 1)

    def _other_requests(self, open_requests):
        # Recording the tenant already living in an occupied unit keeps its waitlist
        if self.unit.availability == Unit.Availability.OCCUPIED:
            return open_requests.filter(kind=Application.Kind.APPLY)
        return open_requests
