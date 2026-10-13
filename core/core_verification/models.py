import logging
import uuid
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.core.files.storage import storages
from django.db import models, transaction
from django.db.models import Q
from django.utils import timezone

logger = logging.getLogger(__name__)


def verification_storage():
    # Private files (settings.STORAGES["verification"]): only admins see them, through short-lived links
    return storages["verification"]


def document_path(instance, filename):
    # Random names, so a file's link can't be guessed from the landlord's name
    return f"{instance.landlord_id}/{uuid.uuid4().hex}{Path(filename).suffix.lower()}"


class VerificationRequestQuerySet(models.QuerySet):

    def waiting(self):
        """Waiting for an admin."""
        return self.filter(status=VerificationRequest.Status.REVIEW)

    def documents_older_than(self, cutoff):
        """Rejected / replaced requests decided before `cutoff` that still have their files."""
        Status = VerificationRequest.Status
        return (self.filter(status__in=[Status.REJECTED, Status.RESUBMIT])
                .filter(Q(decided_at__lt=cutoff) | Q(decided_at__isnull=True, created_at__lt=cutoff))
                .exclude(id_photo=""))


class VerificationRequest(models.Model):
    """One set of landlord documents: a government ID, a selfie holding it, and a
    business permit OR proof of ownership. Claude checks them first
    (core_verification/services.py); anything unclear waits for an admin."""

    class Status(models.TextChoices):
        CHECKING = "checking", "Checking documents"
        REVIEW = "review", "Waiting for admin review"
        RESUBMIT = "resubmit", "New documents needed"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    class IdType(models.TextChoices):
        PHILSYS = "philsys", "PhilSys National ID"
        PASSPORT = "passport", "Passport"
        DRIVERS_LICENSE = "drivers_license", "Driver's license"
        UMID = "umid", "UMID"
        SSS = "sss", "SSS ID"
        PRC = "prc", "PRC ID"
        POSTAL = "postal", "Postal ID"
        VOTERS = "voters", "Voter's ID"
        SENIOR_CITIZEN = "senior_citizen", "Senior Citizen ID"

    class OwnershipType(models.TextChoices):
        BUSINESS_PERMIT = "business_permit", "Business / Mayor's permit"
        LAND_TITLE = "land_title", "Land title (TCT / CCT)"
        TAX_DECLARATION = "tax_declaration", "Tax declaration"
        DEED_OF_SALE = "deed_of_sale", "Deed of sale"
        OTHER = "other", "Other proof of ownership"

    # A check still "running" after this long was lost (e.g. the server restarted): an admin takes over
    STALE_CHECK = timedelta(minutes=10)
    RESUBMIT_DEFAULT = ("We couldn't read one of your documents. Please upload clear photos with all four corners "
                        "showing.")

    request_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    landlord = models.ForeignKey("core.Landlord", on_delete=models.CASCADE, related_name="verification_requests")

    id_type = models.CharField("ID type", max_length=20, choices=IdType.choices)
    id_photo = models.ImageField(upload_to=document_path, storage=verification_storage)
    selfie = models.ImageField(upload_to=document_path, storage=verification_storage)
    ownership_type = models.CharField(max_length=20, choices=OwnershipType.choices)
    ownership_document = models.FileField(upload_to=document_path, storage=verification_storage)   # photo or PDF

    status = models.CharField(max_length=10, choices=Status.choices, default=Status.CHECKING)
    ai_result = models.JSONField(null=True, blank=True)     # what Claude read from each document
    ai_summary = models.TextField("Summary", blank=True)    # for admins: why it was or wasn't auto-approved
    message = models.TextField(blank=True)                  # for the landlord: what to fix / why it was rejected

    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name="+")
    decided_at = models.DateTimeField(null=True, blank=True)
    welcome_seen = models.BooleanField(default=False)       # the "you're verified" pop-up was shown
    created_at = models.DateTimeField(auto_now_add=True)

    objects = VerificationRequestQuerySet.as_manager()

    class Meta:
        db_table = "verification_requests"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.landlord.user.display_name} ({self.get_status_display()})"

    @property
    def documents_deleted(self):
        """The files were removed after the retention period (services.DocumentPurge)."""
        return not self.id_photo

    @property
    def documents(self):
        """The uploaded files that are still there."""
        return [f for f in (self.id_photo, self.selfie, self.ownership_document) if f]

    @property
    def is_pdf(self):
        return self.ownership_document.name.lower().endswith(".pdf")

    def expire_stale_check(self):
        """A check that never finished goes to an admin."""
        if self.status == self.Status.CHECKING and self.created_at < timezone.now() - self.STALE_CHECK:
            self.status = self.Status.REVIEW
            self.ai_summary = "The automatic check didn't finish. Please review by hand."
            self.save(update_fields=["status", "ai_summary"])

    # ---------------------------------------------------------- decisions

    @transaction.atomic
    def decide(self, status, reviewer, message=""):
        """Approve / ask for new documents / reject (reviewer is None when Claude approved it).
        Sets the landlord's verified badge and tells them."""
        if status == self.Status.APPROVED:
            message = ""
        elif status == self.Status.RESUBMIT:
            message = message or self.RESUBMIT_DEFAULT
        self.status = status
        self.message = message
        self.reviewed_by = reviewer
        self.decided_at = timezone.now()
        self.save()
        user = self.landlord.user
        user.is_verified = status == self.Status.APPROVED
        user.save(update_fields=["is_verified"])
        self.notify_landlord()

    def approve(self, reviewer):
        self.decide(self.Status.APPROVED, reviewer)

    def ask_resubmit(self, reviewer, message):
        self.decide(self.Status.RESUBMIT, reviewer, message)

    def reject(self, reviewer, message):
        self.decide(self.Status.REJECTED, reviewer, message)

    @transaction.atomic
    def apply_result(self, verdict):
        """Save Claude's reading (an AIVerdict, see services.py) and act on it."""
        self.ai_result = verdict.result
        self.ai_summary = verdict.result.get("summary", "")
        if verdict.status == self.Status.APPROVED:
            self.decide(self.Status.APPROVED, reviewer=None)
            return
        self.status = verdict.status
        self.message = verdict.message
        self.save(update_fields=["status", "message", "ai_result", "ai_summary"])
        if self.status == self.Status.RESUBMIT:
            self.notify_landlord()

    def send_to_review(self, summary):
        self.status = self.Status.REVIEW
        self.ai_summary = summary
        self.save(update_fields=["status", "ai_summary"])

    def notify_landlord(self):
        """Bell notice + email about the decision (core_admin/notify.py)."""
        from core.core_admin.notify import VerificationNotice     # core_admin imports this app
        notice = VerificationNotice.for_request(self)
        if notice:
            notice.send()

    def mark_welcome_seen(self):
        self.welcome_seen = True
        self.save(update_fields=["welcome_seen"])

    # ---------------------------------------------------------- privacy

    def delete_documents(self):
        """Remove the files and what Claude read from them; the row (and its decision) stays."""
        files = self.documents
        VerificationRequest.objects.filter(pk=self.pk).update(
            id_photo="", selfie="", ownership_document="", ai_result=None)
        for f in files:
            try:
                f.storage.delete(f.name)
            except Exception:
                logger.exception("Couldn't delete verification file %s", f.name)
