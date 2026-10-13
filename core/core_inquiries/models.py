# core_inquiries/models.py
# - Application: "Apply as Renter" (unit is available) or "Join Waitlist" (unit is occupied)
#                pending    -> Pending Requests tab (both sides)
#                waitlisted -> Waitlist tab (landlord approved the waitlist request)
#                accepted   -> a Tenancy was created (Manage Rentals / Rental History)
#                declined / withdrawn / closed -> Archive tab (kept for 30 days)
# - Conversation + Message: "Inquire with Landlord"
#                -> shows up in Messages for both sides
#   A conversation is always started by a renter: landlords can only reply.
import os
import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

from .labels import clock_label, date_label, size_label, time_label
from .managers import ApplicationQuerySet, ConversationQuerySet


class Application(models.Model):

    class Kind(models.TextChoices):
        APPLY = "apply", "Tenant Application"
        WAITLIST = "waitlist", "Waitlist Application"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        WAITLISTED = "waitlisted", "Waitlisted"
        ACCEPTED = "accepted", "Approved"
        DECLINED = "declined", "Rejected"
        WITHDRAWN = "withdrawn", "Cancelled"
        CLOSED = "closed", "Closed"          # the unit was rented to someone else

    # Still waiting on something (shown in Pending Requests / Waitlist)
    OPEN_STATUSES = (Status.PENDING, Status.WAITLISTED)
    # Finished without a tenancy (shown in the Archive)
    ARCHIVED_STATUSES = (Status.DECLINED, Status.WITHDRAWN, Status.CLOSED)
    ARCHIVE_DAYS = 30          # how long a finished request stays in the Archive

    class SiteVisit(models.TextChoices):
        PENDING = "pending", "Pending"
        CONFIRMED = "confirmed", "Confirmed"
        DECLINED = "declined", "Declined"

    class Reason(models.TextChoices):
        # Landlord rejects a request
        UNIT_UNAVAILABLE = "unit_unavailable", "Unit is no longer available"
        REQUIREMENTS = "requirements", "Requirements not met"
        MOVE_IN_DATE = "move_in_date", "Move-in date doesn't work"
        OCCUPANTS = "occupants", "Too many occupants"
        CHOSE_OTHER = "chose_other", "Chose another applicant"
        # Renter cancels a request
        FOUND_OTHER = "found_other", "Found another place"
        PLANS_CHANGED = "plans_changed", "Change of plans"
        BUDGET = "budget", "Price / budget"
        LOCATION = "location", "Location doesn't suit me"
        # Set by the app
        UNIT_RENTED = "unit_rented", "Unit was rented to another applicant"
        OTHER = "other", "Other"

    application_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    renter = models.ForeignKey("core.Renter", on_delete=models.CASCADE, related_name="applications")
    unit = models.ForeignKey("core_listings.Unit", on_delete=models.CASCADE, related_name="applications")

    kind = models.CharField(max_length=10, choices=Kind.choices)
    occupants = models.JSONField(default=list)          # ["Arem Kein Maraño", "Juan Dela Cruz"]
    move_in_date = models.DateField()
    site_visit_date = models.DateField(null=True, blank=True)   # apply only (occupied units can't be visited)
    site_visit_time = models.TimeField(null=True, blank=True)
    site_visit_status = models.CharField(max_length=10, choices=SiteVisit.choices, blank=True)   # empty = no visit

    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)

    # Why it was rejected / cancelled / closed (shown in the Archive)
    reason = models.CharField(max_length=20, choices=Reason.choices, blank=True)
    reason_note = models.TextField(max_length=500, blank=True)
    decided_at = models.DateTimeField(null=True, blank=True)    # last status change (waitlisted / archived)
    notified_at = models.DateTimeField(null=True, blank=True)   # "Notify Applicant" (waitlist, unit vacant)
    edited_at = models.DateTimeField(null=True, blank=True)     # renter changed it with "Edit Application"

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = ApplicationQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            # One open application (pending or on the waitlist) per renter per unit
            models.UniqueConstraint(
                fields=["renter", "unit"],
                condition=Q(status__in=["pending", "waitlisted"]),
                name="one_open_application_per_unit",
            ),
        ]

    def __str__(self):
        return f"{self.get_kind_display()} — {self.renter.user} → {self.unit}"

    @property
    def is_open(self):
        return self.status in self.OPEN_STATUSES

    @property
    def visit_label(self):
        """"Oct 25, 2026 · 2:00 PM" ("" when no site visit was asked for)."""
        if not self.site_visit_date:
            return ""
        label = date_label(self.site_visit_date)
        if self.site_visit_time:
            label += f" · {clock_label(self.site_visit_time)}"
        return label

    @property
    def changes_label(self):
        """"move-in Nov 1, 2026 · site visit Oct 25, 2026 · 2:00 PM" (what an edit set)."""
        parts = [f"move-in {date_label(self.move_in_date)}"]
        if self.site_visit_date:
            parts.append(f"site visit {self.visit_label}")
        return " · ".join(parts)

    # ---------- status changes (the rules for when they're allowed live in workflow.py)

    def close(self, status, reason="", note=""):
        """Move the request to the Archive (declined / withdrawn / closed)."""
        self.status = status
        self.reason = reason
        self.reason_note = note
        self.decided_at = timezone.now()
        self.save(update_fields=["status", "reason", "reason_note", "decided_at", "updated_at"])

    def move_to_waitlist(self):
        self.status = self.Status.WAITLISTED
        self.decided_at = timezone.now()
        self.save(update_fields=["status", "decided_at", "updated_at"])

    def mark_notified(self):
        self.notified_at = timezone.now()
        self.save(update_fields=["notified_at", "updated_at"])

    def set_site_visit_status(self, status):
        self.site_visit_status = status
        self.save(update_fields=["site_visit_status", "updated_at"])


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

    objects = ConversationQuerySet.as_manager()

    class Meta:
        ordering = ["-last_message_at"]
        constraints = [
            models.UniqueConstraint(fields=["renter", "landlord"], name="one_conversation_per_renter_landlord"),
        ]

    def __str__(self):
        return f"{self.renter.user} ↔ {self.landlord.user} ({self.subject})"

    @staticmethod
    def subject_for(unit, complex_obj):
        """"Unit 201 · Sunrise Residences" or just "Sunrise Residences"."""
        return f"{unit.unit_name} · {complex_obj.complex_name}" if unit else complex_obj.complex_name

    @property
    def subject(self):
        return self.subject_for(self.unit if self.unit_id else None, self.complex)

    @staticmethod
    def landlord_can_contact(landlord_user, renter):
        """A landlord may write first only to renters with a real link to them:
        a current/past tenant, or someone who applied to one of their units."""
        from core.core_rentals.models import Tenancy   # imported here: core_rentals imports this app
        mine = Q(unit__complex__landlord__user=landlord_user)
        return (
            Tenancy.objects.filter(mine, renter=renter).exists()
            or Application.objects.filter(mine, renter=renter).exists()
        )

    def can_send(self, user):
        """Renters can always reply in their own thread.
        Landlords can reply once the renter has written first, or when the
        renter is/was their tenant or applied to one of their units."""
        if self.renter.user_id == user.pk:
            return True
        if self.landlord.user_id == user.pk:
            return (
                self.messages.filter(sender=self.renter.user).exists()
                or self.landlord_can_contact(user, self.renter)
            )
        return False

    def other_party(self, user):
        """The person on the other side of the thread (a User)."""
        if self.renter.user_id == user.pk:
            return self.landlord.user
        return self.renter.user

    def mark_read(self, user):
        """Everything the other side sent is now seen."""
        self.messages.filter(read_at__isnull=True).exclude(sender=user).update(read_at=timezone.now())

    def add_message(self, sender, body, attachment=None, attachment_kind="", topic="",
                    kind="message", bulletin_event=""):
        """Save a (checked) message in this thread and move the thread to the top."""
        message = Message(conversation=self, sender=sender, body=body, topic=topic,
                          kind=kind, bulletin_event=bulletin_event[:200])
        if attachment:
            message.attachment = attachment
            message.attachment_name = os.path.basename(attachment.name)[:255]
            message.attachment_kind = attachment_kind
            message.attachment_size = attachment.size
        message.save()

        self.last_message_at = message.created_at
        self.save(update_fields=["last_message_at"])
        return message


class Message(models.Model):
    MAX_LENGTH = 2000

    class AttachmentKind(models.TextChoices):
        IMAGE = "image", "Photo"
        VIDEO = "video", "Video"
        PDF = "pdf", "PDF"

    class Kind(models.TextChoices):
        MESSAGE = "message", "Message"
        BULLETIN = "bulletin", "Bulletin announcement"      # Post on Bulletin -> a yellow banner in the chat

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

    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.MESSAGE)
    # Bulletins with a date: "Maintenance / Inspection · Oct 11, 2026 – Oct 17, 2026 (whole week)"
    bulletin_event = models.CharField(max_length=200, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)   # "Seen" for the sender

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.sender}: {self.body[:40] or self.attachment_name}"

    @property
    def preview(self):
        """Text for the inbox list: the message, "Bulletin: …", or "📎 contract.pdf"."""
        if self.kind == self.Kind.BULLETIN:
            return f"Bulletin: {self.body}"
        return self.body or f"📎 {self.attachment_name or self.get_attachment_kind_display()}"

    @property
    def time_label(self):
        return time_label(self.created_at)

    @property
    def seen_label(self):
        return time_label(self.read_at) if self.read_at else ""

    @property
    def attachment_size_label(self):
        return size_label(self.attachment_size)