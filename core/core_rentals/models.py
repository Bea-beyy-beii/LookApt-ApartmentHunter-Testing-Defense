# core_rentals/models.py
# - Tenancy: who is renting a unit, from when to when (one active per unit).
#   The tenant is a LookApt renter (usually from an application) or, for
#   people not on the app, just a typed name.
# - RentPayment: one row per month the landlord marked as paid.
import uuid

from django.db import models
from django.db.models import Q


class Tenancy(models.Model):

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        COMPLETED = "completed", "Completed"
        TERMINATED = "terminated", "Terminated"

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

    @property
    def is_active(self):
        return self.status == self.Status.ACTIVE


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