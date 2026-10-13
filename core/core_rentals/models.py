# core_rentals/models.py
# - Tenancy: who is renting a unit, from when to when (one active per unit).
#   The tenant is a LookApt renter (usually from an application) or, for
#   people not on the app, just a typed name. It also knows its own lease
#   terms and rent schedule (see the methods below).
# - RentPayment: one row per month the landlord marked as paid.
#
# Rent is due every month on the tenancy's start day (Oct 26 start -> due
# every 26th; a 31st start is due on the last day of shorter months).
#   Overdue  = a due date has passed and it isn't paid
#   Due soon = the next due date is within DUE_SOON_DAYS and isn't paid
#   Paid     = everything due so far is paid
import uuid
from datetime import date, timedelta

from dateutil.relativedelta import relativedelta
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import Q

from core.core_inquiries.services import LEASE_MONTHS, today


class TenancyQuerySet(models.QuerySet):
    """Tenancy.objects.active(), .of_landlord(user) ..."""

    def active(self):
        return self.filter(status=Tenancy.Status.ACTIVE)

    def ended(self):
        return self.exclude(status=Tenancy.Status.ACTIVE)

    def of_landlord(self, user):
        return self.filter(unit__complex__landlord__user=user)

    def of_renter(self, user):
        return self.filter(renter__user=user)


class Tenancy(models.Model):

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        COMPLETED = "completed", "Completed"
        TERMINATED = "terminated", "Terminated"

    DUE_SOON_DAYS = 7
    ENDING_SOON_DAYS = 30

    tenancy_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    unit = models.ForeignKey("core_listings.Unit", on_delete=models.CASCADE, related_name="tenancies")

    # A LookApt renter (null for tenants who aren't on the app)
    renter = models.ForeignKey("core.Renter", on_delete=models.SET_NULL, null=True, blank=True, related_name="tenancies")
    application = models.ForeignKey(
        "core_inquiries.Application", on_delete=models.SET_NULL, null=True, blank=True, related_name="tenancies",
    )

    tenant_name = models.CharField(max_length=150)           # primary tenant, shown in Manage Rentals
    occupants = models.JSONField(default=list)               # everyone staying, primary tenant first

    monthly_rent = models.DecimalField(max_digits=8, decimal_places=2)   # copied from the unit when assigned
    start_date = models.DateField()                          # rent is due on this day every month
    end_date = models.DateField()                            # last day of the lease (start + lease term - 1 day)

    status = models.CharField(max_length=12, choices=Status.choices, default=Status.ACTIVE)
    ended_on = models.DateField(null=True, blank=True)       # when it was marked completed/terminated

    created_at = models.DateTimeField(auto_now_add=True)

    objects = TenancyQuerySet.as_manager()

    class Meta:
        verbose_name_plural = "tenancies"
        ordering = ["-start_date"]
        constraints = [
            models.UniqueConstraint(
                fields=["unit"], condition=Q(status="active"), name="one_active_tenancy_per_unit",
            ),
        ]

    def __str__(self):
        return f"{self.tenant_name} — {self.unit} ({self.get_status_display()})"

    # ---------- who ----------

    @property
    def is_active(self):
        return self.status == self.Status.ACTIVE

    @property
    def is_app_user(self):
        return self.renter_id is not None

    @property
    def initials(self):
        parts = [p for p in self.tenant_name.split() if p]
        return (parts[0][:1] + (parts[-1][:1] if len(parts) > 1 else "")).upper() or "?"

    @property
    def avatar_url(self):
        """Their profile photo (tenants not on the app have none)."""
        return self.renter.user.avatar_url if self.renter_id else ""

    @property
    def occupant_count(self):
        return max(1, len(self.occupants))

    def can_be_reviewed_by(self, user):
        """The tenancy's own renter, once the rental has started (current or past)."""
        renter = self.renter
        return bool(renter and renter.user_id == user.pk and self.start_date <= today())

    # ---------- lease terms ----------

    @property
    def lease_months(self):
        return LEASE_MONTHS.get(self.unit.complex.lease_term, 12)

    @property
    def first_term_end(self):
        """Last day of the first lease term: start + lease term - 1 day (Oct 1, 2026 -> Sep 30, 2027 for annual)."""
        return self._term_end(0)

    def _term_end(self, n):
        """Last day of lease term number n (0 = the first term)."""
        return self.start_date + relativedelta(months=self.lease_months * (n + 1)) - timedelta(days=1)

    def current_term(self, on):
        """(start, end) shown as the contract period on `on`.

        start = first day of the lease term running on `on`
        end   = the contract end: end_date, which "Renew Lease Contract" pushes
                forward. If nobody renewed or ended it in time, the lease rolls over
                on its own (a monthly lease from Jan 10 is in its Oct 10 – Nov 9 term
                on Oct 20).
        """
        if not self.is_active:
            return self.start_date, self.end_date
        n = 0
        while self._term_end(n) < on:
            n += 1
        term_start = self.start_date + relativedelta(months=self.lease_months * n)
        return term_start, max(self.end_date, self._term_end(n))

    def renewal_end(self, on=None):
        """The contract end after one more lease term (what "Renew" would set)."""
        _, end = self.current_term(on or today())
        n = 0
        while self._term_end(n) < end:
            n += 1
        return self._term_end(n + 1)

    @transaction.atomic
    def renew(self, on=None):
        """Add one more lease term after the current contract end."""
        if not self.is_active:
            raise ValidationError({"__all__": "This contract has ended. Assign the renter again instead."})
        self.end_date = self.renewal_end(on)
        self.save(update_fields=["end_date"])
        return self

    @transaction.atomic
    def end(self, status, on=None):
        """Mark the contract completed or terminated: it moves to the Archive, the unit is vacant again."""
        if status not in (self.Status.COMPLETED, self.Status.TERMINATED):
            raise ValidationError({"__all__": "Unknown action."})
        if not self.is_active:
            raise ValidationError({"__all__": "This contract has already ended."})

        self.status = status
        self.ended_on = on or today()
        self.save(update_fields=["status", "ended_on"])

        unit = self.unit
        unit.availability = unit.Availability.AVAILABLE
        unit.occupied_since = None
        unit.save(update_fields=["availability", "occupied_since", "updated_at"])
        return self

    # ---------- rent ----------

    @property
    def _billing_stop(self):
        """Active: rent keeps coming due. Ended: nothing after the day it ended."""
        return None if self.is_active else (self.ended_on or self.end_date)

    def _paid_dates(self):
        return {p.due_date for p in self.payments.all()}

    @staticmethod
    def _month_label(day):
        return f"{day:%B %Y}"

    def due_dates(self, until):
        """Every monthly due date from the start up to `until`."""
        stop = self._billing_stop
        last = min(until, stop) if stop else until
        dates, n = [], 0
        while True:
            due = self.start_date + relativedelta(months=n)   # relativedelta keeps "the 31st" sane
            if due > last:
                return dates
            dates.append(due)
            n += 1

    def next_due_date(self, after):
        """First due date after `after`, or None once the tenancy has ended."""
        stop = self._billing_stop
        n = 0
        while True:
            due = self.start_date + relativedelta(months=n)
            if stop and due > stop:
                return None
            if due > after:
                return due
            n += 1

    def unpaid_dates(self, until):
        """Due dates up to `until` that weren't marked as paid."""
        paid = self._paid_dates()
        return [d for d in self.due_dates(until) if d not in paid]

    def payment_status(self, on=None):
        """{"key": "paid" | "due_soon" | "overdue", "label": ..., "detail": ...}"""
        on = on or today()
        paid = self._paid_dates()

        overdue = self.unpaid_dates(on - timedelta(days=1))
        if overdue:
            detail = self._month_label(overdue[0]) if len(overdue) == 1 else f"{len(overdue)} months unpaid"
            return {"key": "overdue", "label": "Overdue", "detail": detail}

        soon = on + timedelta(days=self.DUE_SOON_DAYS)
        upcoming = [d for d in self.due_dates(soon) if d >= on and d not in paid]
        if upcoming:
            when = "today" if upcoming[0] == on else f"{upcoming[0]:%b} {upcoming[0].day}"
            return {"key": "due_soon", "label": "Due Soon", "detail": f"Due {when}"}

        latest = max(paid) if paid else None
        return {"key": "paid", "label": "Paid", "detail": self._month_label(latest) if latest else "Nothing due yet"}

    def payable_months(self, on=None):
        """Months the landlord can mark as paid: everything unpaid so far + the next one."""
        on = on or today()
        paid = self._paid_dates()
        months = [d for d in self.due_dates(on) if d not in paid]
        upcoming = self.next_due_date(on)
        while upcoming and upcoming in paid:            # already paid in advance: offer the one after
            upcoming = self.next_due_date(upcoming)
        if upcoming and upcoming not in months:
            months.append(upcoming)
        return [
            {"value": d.isoformat(), "label": self._month_label(d), "due": f"Due {d:%b} {d.day}, {d.year}",
             "overdue": d < on}
            for d in months
        ]

    @transaction.atomic
    def mark_paid(self, due_date_values, on=None):
        """Record payments for the chosen months. Only months offered by payable_months() are accepted."""
        if not self.is_active:
            raise ValidationError({"__all__": "This tenancy has ended."})
        allowed = {m["value"] for m in self.payable_months(on)}
        chosen = [v for v in (due_date_values or []) if v in allowed]
        if not chosen:
            raise ValidationError({"months": "Pick at least one month to mark as paid."})

        for value in chosen:
            RentPayment.objects.get_or_create(
                tenancy=self, due_date=date.fromisoformat(value),
                defaults={"amount": self.monthly_rent, "paid_on": on or today()},
            )
        return len(chosen)


class RentPayment(models.Model):
    tenancy = models.ForeignKey(Tenancy, on_delete=models.CASCADE, related_name="payments")
    due_date = models.DateField()        # which month this pays for (that month's due date)
    amount = models.DecimalField(max_digits=8, decimal_places=2)
    paid_on = models.DateField()
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["due_date"]
        constraints = [
            models.UniqueConstraint(fields=["tenancy", "due_date"], name="one_payment_per_month"),
        ]

    def __str__(self):
        return f"{self.tenancy.tenant_name} paid {self.due_date:%b %Y}"
