import uuid
from pathlib import Path

from django.conf import settings
from django.core.files.storage import storages
from django.db import models


def verification_storage():
    # Private files (settings.STORAGES["verification"]): only admins see them, through short-lived links
    return storages["verification"]


def document_path(instance, filename):
    # Random names, so a file's link can't be guessed from the landlord's name
    return f"{instance.landlord_id}/{uuid.uuid4().hex}{Path(filename).suffix.lower()}"


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

    class Meta:
        db_table = "verification_requests"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.landlord.user.display_name} ({self.get_status_display()})"