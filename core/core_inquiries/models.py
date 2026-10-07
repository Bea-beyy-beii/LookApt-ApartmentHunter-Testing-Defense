# core_inquiries/models.py
# - Application: "Apply as Renter" (unit is available) or "Join Waitlist" (unit is occupied)
#                -> shows up in the landlord's Requests tab
# - Conversation + Message: "Inquire with Landlord"
#                -> shows up in Messages for both sides
#   A conversation is always started by a renter: landlords can only reply.
import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q


class Application(models.Model):

    class Kind(models.TextChoices):
        APPLY = "apply", "Tenant Application"
        WAITLIST = "waitlist", "Waitlist Application"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        ACCEPTED = "accepted", "Accepted"
        DECLINED = "declined", "Declined"
        WITHDRAWN = "withdrawn", "Withdrawn"

    application_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    renter = models.ForeignKey("core.Renter", on_delete=models.CASCADE, related_name="applications")
    unit = models.ForeignKey("core_listings.Unit", on_delete=models.CASCADE, related_name="applications")

    kind = models.CharField(max_length=10, choices=Kind.choices)
    occupants = models.JSONField(default=list)          # ["Arem Kein Maraño", "Juan Dela Cruz"]
    move_in_date = models.DateField()
    site_visit_date = models.DateField(null=True, blank=True)   # apply only (occupied units can't be visited)

    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            # One open application per renter per unit
            models.UniqueConstraint(
                fields=["renter", "unit"],
                condition=Q(status="pending"),
                name="one_pending_application_per_unit",
            ),
        ]

    def __str__(self):
        return f"{self.get_kind_display()} — {self.renter.user} → {self.unit}"


class Conversation(models.Model):
    """One thread per renter per landlord, whatever unit or complex it's about.
    complex/unit = what the renter asked about most recently (shown as the subject)."""

    conversation_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    renter = models.ForeignKey("core.Renter", on_delete=models.CASCADE, related_name="conversations")
    landlord = models.ForeignKey("core.Landlord", on_delete=models.CASCADE, related_name="conversations")
    complex = models.ForeignKey("core_listings.Complex", on_delete=models.CASCADE, related_name="conversations")
    unit = models.ForeignKey("core_listings.Unit", on_delete=models.SET_NULL, null=True, blank=True, related_name="conversations")

    created_at = models.DateTimeField(auto_now_add=True)
    last_message_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-last_message_at"]
        constraints = [
            models.UniqueConstraint(fields=["renter", "landlord"], name="one_conversation_per_renter_landlord"),
        ]

    def __str__(self):
        return f"{self.renter.user} ↔ {self.landlord.user} ({self.subject})"

    @property
    def subject(self):
        """"Unit 201 · Sunrise Residences" or just "Sunrise Residences"."""
        if self.unit_id:
            return f"{self.unit.unit_name} · {self.complex.complex_name}"
        return self.complex.complex_name


class Message(models.Model):
    MAX_LENGTH = 2000

    class AttachmentKind(models.TextChoices):
        IMAGE = "image", "Photo"
        VIDEO = "video", "Video"
        PDF = "pdf", "PDF"

    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name="messages")
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="sent_messages")
    body = models.TextField(max_length=MAX_LENGTH, blank=True)   # can be empty when a file is attached

    # Set when the renter asks about a different unit/complex in the same thread,
    # e.g. "Unit 401 · Sunrise Residences" (shown as a small divider)
    topic = models.CharField(max_length=200, blank=True)

    # Optional file (photo / video / PDF, up to 5 MB)
    attachment = models.FileField(upload_to="message_files/%Y/%m/", blank=True)
    attachment_name = models.CharField(max_length=255, blank=True)
    attachment_kind = models.CharField(max_length=10, choices=AttachmentKind.choices, blank=True)
    attachment_size = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)   # "Seen" for the sender

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.sender}: {self.body[:40] or self.attachment_name}"

    @property
    def preview(self):
        """Text for the inbox list: the message, or "📎 contract.pdf"."""
        return self.body or f"📎 {self.attachment_name or self.get_attachment_kind_display()}"