import uuid

from django.conf import settings
from django.db import models


# (value, label) pairs — value is stored in the DB, label is shown in the UI.

RENTER_CATEGORIES = [
    ("price_mismatch", "Landlord did not follow declared price of unit"),
    ("offensive_statements", "Listing included offensive statements"),
    ("misleading_info", "Misleading photos or information"),
    ("unresponsive", "Landlord was unresponsive or unprofessional"),
    ("safety_concerns", "Safety concerns / suspicious activity"),
    ("policy_violation", "Violation of platform rules or policies"),
    ("fraudulent_listing", "Fraudulent listing (fake or duplicate)"),
    ("others", "Others (please specify)"),
]


LANDLORD_CATEGORIES = [
    ("no_show", "Renter did not show up to a scheduled visit"),
    ("harassment", "Renter was abusive or harassing"),
    ("fake_inquiry", "Fake or spam inquiry"),
    ("policy_violation", "Violation of platform rules or policies"),
    ("safety_concerns", "Safety concerns / suspicious activity"),
    ("others", "Others (please specify)"),
]

# The model's `choices` needs the full combined set, deduped, so both
# a renter's and a landlord's report validate against the same field.

ALL_CATEGORIES = list(dict(RENTER_CATEGORIES + LANDLORD_CATEGORIES).items())


class Report(models.Model):
    class Status(models.TextChoices):
        WAITING = "waiting", "Pending"
        REVIEWING = "reviewing", "Under Review"
        RESOLVED = "resolved", "Resolved"
        DISMISSED = "dismissed", "Closed"

    OPEN_STATUSES = (Status.WAITING, Status.REVIEWING)

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    reporter = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="reports_filed",
    )
    reported_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="reports_received",  # two FKs to User need different related_names
    )

    category = models.CharField(max_length=50, choices=ALL_CATEGORIES)
    other_category_text = models.CharField(max_length=200, blank=True)
    description = models.TextField(max_length=500)

    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.WAITING
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.get_category_display()} ({self.get_status_display()})"


class ReportEvidence(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    report = models.ForeignKey(
        Report, on_delete=models.CASCADE, related_name="evidence"
    )
    file = models.FileField(upload_to="report_evidence/%Y/%m/")
    name = models.CharField(max_length=255, blank=True)   # the file's original name
    kind = models.CharField(max_length=10, blank=True)    # image / video / document
    size = models.PositiveIntegerField(default=0)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["uploaded_at"]

    def __str__(self):
        return self.name or self.file.name