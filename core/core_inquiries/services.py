# core_inquiries/services.py
# Applications (apply / waitlist), messages, the inbox and the bell's notifications.
#
#   LeaseSchedule        when a unit's lease ends and a new renter can move in
#   ApplicationRequest   "Apply as Renter" / "Join Waitlist" (one subclass per kind)
#   Attachment           a file sent in a chat, checked by name, size and content
#   MessageSender        renter inquiry / landlord message / reply (one subclass each)
#   ChatJSON, Inbox      what the chat pop-ups and the Messages list receive
#   NotificationFeed     the bell (one subclass per role)
import os
import uuid
from abc import ABC, abstractmethod
from datetime import timedelta

from dateutil.relativedelta import relativedelta
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.urls import reverse
from django.utils import timezone
from django.utils.functional import cached_property
from PIL import Image

from core.core_listings.models import LeaseTerm, Unit
from core.models import Renter
from core.roles import RoleBased

from .labels import date_label, size_label, time_label
from .models import Application, Conversation, Message

LEASE_MONTHS = {
    LeaseTerm.MONTHLY: 1,
    LeaseTerm.QUARTERLY: 3,
    LeaseTerm.BIANNUAL: 6,
    LeaseTerm.ANNUAL: 12,
}


def today():
    """Today in the site's time zone (one place, so tests can pin the date)."""
    return timezone.localdate()


# =========================================================
# DATES
# =========================================================

class LeaseSchedule:
    """The lease of one unit, seen on a given day (`on`, today by default)."""

    def __init__(self, unit, on=None):
        self.unit = unit
        self.on = on or today()

    @property
    def months(self):
        return LEASE_MONTHS.get(self.unit.complex.lease_term, 12)

    @property
    def current_end(self):
        """End of the current tenant's lease, or None if we don't know when it started.

        Leases renew: a monthly lease that started Oct 26, 2025 ends on the next
        26th that hasn't passed yet.
        """
        if not self.unit.occupied_since:
            return None
        end = self.unit.occupied_since + relativedelta(months=self.months)
        while end < self.on:
            end += relativedelta(months=self.months)
        return end

    @property
    def earliest_move_in(self):
        """First day a renter can move in.

        Available unit -> today.
        Occupied unit  -> current lease end + the landlord's turnover days
                          (or today + turnover days when the lease start isn't set).
        """
        if self.unit.availability == Unit.Availability.AVAILABLE:
            return self.on
        return (self.current_end or self.on) + timedelta(days=self.unit.complex.turnover_days)


# =========================================================
# APPLICATIONS
# =========================================================

class ApplicationRequest:
    """What a renter filled in on the Apply / Join Waitlist form, checked before it's saved.

    Polymorphism: each kind of request is a subclass that says which units it is
    for and whether a site visit can be asked for; submit() and update() are shared.
    """

    MAX_NAME_LENGTH = 100
    MAX_DAYS_AHEAD = 365          # move-in / site visit can't be more than a year away

    kind = None
    unit_must_be = None           # the Unit.Availability this kind of request is for
    unavailable_message = ""
    noun = "application"
    allows_site_visit = True

    def __init__(self, user, unit, occupants, move_in_date, site_visit_date=None, site_visit_time=None):
        self.user = user
        self.unit = unit
        self.occupants = occupants
        self.move_in_date = move_in_date
        self.site_visit_date = site_visit_date
        self.site_visit_time = site_visit_time

    @staticmethod
    def class_for(kind):
        """The subclass for "apply" / "waitlist" (None for anything else)."""
        return {subclass.kind: subclass for subclass in ApplicationRequest.__subclasses__()}.get(kind)

    def submit(self):
        """Validate and save a new application. Raises ValidationError({field: message})."""
        if self.unit.availability != self.unit_must_be:
            raise ValidationError({"__all__": self.unavailable_message.format(unit=self.unit.unit_name)})

        details = self._clean()
        renter, _ = Renter.objects.get_or_create(user=self.user)
        try:
            with transaction.atomic():
                return Application.objects.create(
                    renter=renter, unit=self.unit, kind=self.kind, **details,
                    site_visit_status=Application.SiteVisit.PENDING if details["site_visit_date"] else "",
                )
        except IntegrityError:
            raise ValidationError({"__all__": f"You already have an open application for {self.unit.unit_name}."})

    @transaction.atomic
    def update(self, application):
        """Renter changes a pending request ("Edit Application"). A new site visit
        date/time needs the landlord's confirmation again."""
        if application.status != Application.Status.PENDING:
            raise ValidationError({"__all__": "Only pending requests can be edited."})

        details = self._clean()
        visit_changed = (
            details["site_visit_date"] != application.site_visit_date
            or details["site_visit_time"] != application.site_visit_time
        )
        for field, value in details.items():
            setattr(application, field, value)
        if not application.site_visit_date:
            application.site_visit_status = ""
        elif visit_changed:
            application.site_visit_status = Application.SiteVisit.PENDING
        application.edited_at = timezone.now()     # the landlord's bell shows "Request updated"
        application.save()
        return application

    # ---------- checks shared by submit() and update()

    def _clean(self):
        """Returns the cleaned values."""
        complex_obj = self.unit.complex
        if not complex_obj.admits(self.user):
            sex = "female" if complex_obj.sex_restriction == "female_only" else "male"
            raise ValidationError({"__all__": f"{complex_obj.complex_name} is for {sex} tenants only."})

        now = today()
        occupants = self._clean_occupants()
        self._check_move_in(now)
        site_visit_date, site_visit_time = self._clean_site_visit(now)
        return {
            "occupants": occupants,
            "move_in_date": self.move_in_date,
            "site_visit_date": site_visit_date,
            "site_visit_time": site_visit_time,
        }

    def _clean_occupants(self):
        names = self.occupants
        if not isinstance(names, list):
            raise ValidationError({"occupants": "Add the names of everyone who will stay in the unit."})

        # The first tenant is always the account holder (the field is read-only in the form)
        others = [str(name).strip() for name in names[1:]]
        if any(not name for name in others):
            raise ValidationError({"occupants": "Fill in every name, or remove the empty row."})
        if any(len(name) > self.MAX_NAME_LENGTH for name in others):
            raise ValidationError({"occupants": f"Names can be up to {self.MAX_NAME_LENGTH} characters."})

        occupants = [self.user.display_name, *others]
        limit = self.unit.max_occupant
        if len(occupants) > limit:
            raise ValidationError({
                "occupants": f"{self.unit.unit_name} allows up to {limit} occupant{'s' if limit != 1 else ''}."
            })
        return occupants

    def _check_move_in(self, now):
        latest = now + timedelta(days=self.MAX_DAYS_AHEAD)
        earliest = LeaseSchedule(self.unit, now).earliest_move_in
        if not self.move_in_date:
            raise ValidationError({"move_in_date": "Pick your preferred move-in date."})
        if self.move_in_date < earliest:
            raise ValidationError({"move_in_date": f"The earliest move-in date is {date_label(earliest)}."})
        if self.move_in_date > max(latest, earliest + timedelta(days=self.MAX_DAYS_AHEAD)):
            raise ValidationError({"move_in_date": "Pick a move-in date within the next year."})

    def _clean_site_visit(self, now):
        visit_date, visit_time = self.site_visit_date, self.site_visit_time
        if not self.allows_site_visit or not visit_date:
            return None, None
        if visit_date < now:
            raise ValidationError({"site_visit_date": "The site visit can't be in the past."})
        if visit_date > self.move_in_date:
            raise ValidationError({"site_visit_date": "Schedule the site visit on or before your move-in date."})
        if not visit_time:
            raise ValidationError({"site_visit_time": "Pick a time for the site visit."})
        if visit_date == now and visit_time <= timezone.localtime().time():
            raise ValidationError({"site_visit_time": "That time has already passed. Pick a later time."})
        return visit_date, visit_time


class TenantApplication(ApplicationRequest):
    """"Apply as Renter": for available units, with an optional site visit."""
    kind = Application.Kind.APPLY
    unit_must_be = Unit.Availability.AVAILABLE
    unavailable_message = "{unit} is no longer available. You can join its waitlist instead."


class WaitlistApplication(ApplicationRequest):
    """"Join Waitlist": for occupied units, which can't be visited."""
    kind = Application.Kind.WAITLIST
    unit_must_be = Unit.Availability.OCCUPIED
    unavailable_message = "{unit} is available now. You can apply right away."
    noun = "waitlist application"
    allows_site_visit = False


# =========================================================
# MESSAGES
# One thread per renter per landlord. Only renters can start one;
# landlords can only reply once the renter has written.
# =========================================================

class Attachment:
    """A file sent in a chat (photo / video / PDF up to MAX_MB), checked before it's saved."""

    MAX_MB = 5
    TYPES = {
        ".jpg": Message.AttachmentKind.IMAGE,
        ".jpeg": Message.AttachmentKind.IMAGE,
        ".png": Message.AttachmentKind.IMAGE,
        ".mp4": Message.AttachmentKind.VIDEO,
        ".webm": Message.AttachmentKind.VIDEO,
        ".mov": Message.AttachmentKind.VIDEO,
        ".pdf": Message.AttachmentKind.PDF,
    }

    def __init__(self, upload):
        self.upload = upload

    def clean(self):
        """Validate the file. Returns its kind ("image" / "video" / "pdf")."""
        upload = self.upload
        kind = self.TYPES.get(os.path.splitext(upload.name)[1].lower())
        if not kind:
            raise ValidationError({"attachment": "You can send photos (JPG, PNG), videos (MP4, WebM, MOV) or PDF files."})
        if upload.size > self.MAX_MB * 1024 * 1024:
            raise ValidationError({"attachment": f"Files can be up to {self.MAX_MB} MB ({upload.name} is {size_label(upload.size)})."})
        if not self._content_matches(kind):
            raise ValidationError({"attachment": f"{upload.name} doesn't look like a real {kind} file."})
        return kind

    def _content_matches(self, kind):
        """Check the file's content, not just its name (a renamed .exe must not pass)."""
        head = self.upload.read(12)
        self.upload.seek(0)
        checks = {
            Message.AttachmentKind.PDF: self._is_pdf,
            Message.AttachmentKind.VIDEO: self._is_video,
            Message.AttachmentKind.IMAGE: self._is_image,
        }
        return checks[kind](head)

    def _is_pdf(self, head):
        return head[:5] == b"%PDF-"

    def _is_video(self, head):
        return head[4:8] == b"ftyp" or head[:4] == b"\x1a\x45\xdf\xa3"   # MP4/MOV or WebM

    def _is_image(self, head):
        try:
            with Image.open(self.upload) as image:
                ok = image.format in ("JPEG", "PNG")
                image.verify()
            return ok
        except Exception:
            return False
        finally:
            self.upload.seek(0)


class MessageSender(ABC):
    """Sends one message from `user`.

    Template method: send() always checks the sender, the file and the text in
    the same order; each subclass says who may write (_check_allowed) and which
    thread the message goes to (_thread).
    """

    message_kind = Message.Kind.MESSAGE
    bulletin_event = ""

    def __init__(self, user):
        self.user = user

    @transaction.atomic
    def send(self, body, attachment=None):
        self._check_allowed()
        kind = Attachment(attachment).clean() if attachment else ""
        body = self._clean_body(body, bool(attachment))
        conversation, topic = self._thread()
        return conversation.add_message(self.user, body, attachment, kind, topic,
                                        kind=self.message_kind, bulletin_event=self.bulletin_event)

    def _check_allowed(self):
        """Raise PermissionDenied when this user may not write here."""

    @abstractmethod
    def _thread(self):
        """(conversation, topic) the message goes to (creating the thread if needed)."""

    def _clean_body(self, body, has_attachment):
        body = (body or "").strip()
        if not body and not has_attachment:
            raise ValidationError({"body": "Type a message or attach a file first."})
        if len(body) > Message.MAX_LENGTH:
            raise ValidationError({"body": f"Messages can be up to {Message.MAX_LENGTH} characters."})
        return body


class RenterInquiry(MessageSender):
    """Renter asks about a unit/complex from a listing page.

    Always lands in the renter's single thread with that landlord. When the
    renter asks about a different unit/complex, the message carries a "topic"
    so both sides can see what it's about.
    """

    def __init__(self, user, unit=None, complex_obj=None):
        super().__init__(user)
        self.unit = unit
        self.complex = unit.complex if unit else complex_obj

    @classmethod
    def thread_with(cls, user, landlord):
        """The renter's thread with this landlord, or None."""
        return Conversation.objects.filter(renter__user=user, landlord=landlord).first()

    def _thread(self):
        renter, _ = Renter.objects.get_or_create(user=self.user)
        subject = Conversation.subject_for(self.unit, self.complex)

        conversation = self.thread_with(self.user, self.complex.landlord)
        if conversation is None:
            conversation = Conversation.objects.create(
                renter=renter, landlord=self.complex.landlord, complex=self.complex, unit=self.unit,
            )
            return conversation, subject
        if conversation.subject != subject:
            conversation.complex, conversation.unit = self.complex, self.unit
            conversation.save(update_fields=["complex", "unit"])
            return conversation, subject
        return conversation, ""


class LandlordMessage(MessageSender):
    """Landlord writes to a tenant/applicant from Manage Rentals (creates the thread if needed).
    message_kind=BULLETIN: a Post on Bulletin announcement (shown as a banner, core_calendar)."""

    def __init__(self, user, renter, message_kind=Message.Kind.MESSAGE, bulletin_event=""):
        super().__init__(user)
        self.renter = renter
        self.message_kind = message_kind
        self.bulletin_event = bulletin_event

    @classmethod
    def thread_with(cls, landlord_user, renter):
        return Conversation.objects.filter(landlord__user=landlord_user, renter=renter).first()

    def _check_allowed(self):
        if not Conversation.landlord_can_contact(self.user, self.renter):
            raise PermissionDenied("You can only message renters who rent from you, applied to your units, or messaged you first.")

    def _thread(self):
        conversation = self.thread_with(self.user, self.renter)
        if conversation is None:
            # What the thread is about: their latest rental, else their latest application
            from core.core_rentals.models import Tenancy   # imported here: core_rentals imports this module
            mine = {"renter": self.renter, "unit__complex__landlord__user": self.user}
            link = (
                Tenancy.objects.filter(**mine).select_related("unit__complex").first()
                or Application.objects.filter(**mine).select_related("unit__complex").first()
            )
            conversation = Conversation.objects.create(
                renter=self.renter, landlord=self.user.landlord, complex=link.unit.complex, unit=link.unit,
            )
        return conversation, ""


class ThreadReply(MessageSender):
    """A reply in an existing thread (either side)."""

    def __init__(self, user, conversation):
        super().__init__(user)
        self.conversation = conversation

    def _check_allowed(self):
        if not self.conversation.can_send(self.user):
            raise PermissionDenied("You can only reply to renters who messaged you first.")

    def _thread(self):
        return self.conversation, ""


class ChatJSON:
    """Messages and threads as the chat pop-ups receive them, seen by `user`."""

    def __init__(self, user):
        self.user = user

    def message(self, message):
        data = {
            "id": message.pk,
            "body": message.body,
            "topic": message.topic,
            "kind": message.kind,                       # "bulletin" = announcement banner (chat.js)
            "bulletin_event": message.bulletin_event,
            "mine": message.sender_id == self.user.pk,
            "created_at": message.created_at.isoformat(),
            "time_label": message.time_label,
            "seen": message.read_at is not None,
            "seen_label": message.seen_label,
            "attachment": None,
        }
        if message.attachment:
            data["attachment"] = {
                "url": message.attachment.url,
                "name": message.attachment_name,
                "kind": message.attachment_kind,
                "size_label": message.attachment_size_label,
            }
        return data

    def conversation(self, conversation, after=None):
        """The thread for the pop-up / Inquiries tab.

        after=<message id>: only newer messages (used by the 4-second refresh).
        Seen status is always sent for this user's messages, so ✓✓ can update.
        """
        other = conversation.other_party(self.user)
        messages = conversation.messages.all()
        if after:
            messages = messages.filter(pk__gt=after)

        seen_ids = list(
            conversation.messages.filter(sender=self.user, read_at__isnull=False).values_list("pk", "read_at")
        )

        return {
            "id": str(conversation.pk),
            "subject": conversation.subject,
            "other_name": other.display_name,
            "other_initials": other.initials,
            "other_avatar": other.avatar_url,
            "other_role": other.role,
            "other_verified": other.is_verified,
            "can_send": conversation.can_send(self.user),
            "messages": [self.message(m) for m in messages],
            "seen": {str(pk): time_label(read_at) for pk, read_at in seen_ids},
            "detail_url": reverse("core_inquiries:conversation_detail", args=[conversation.pk]),
            "reply_url": reverse("core_inquiries:conversation_reply", args=[conversation.pk]),
        }


# =========================================================
# INBOX (Messages in the Inquiries tab)
# =========================================================

class LatestMessage:
    """The latest message of a thread, read from annotations (no extra queries)."""

    def __init__(self, conversation):
        self.body = conversation.latest_body or ""
        self.kind = conversation.latest_kind or Message.Kind.MESSAGE
        self.attachment_name = conversation.latest_attachment_name or ""
        # A subquery value can come back as a plain string (SQLite): make it a UUID like user.pk
        sender = conversation.latest_sender_id
        self.sender_id = sender if sender is None or isinstance(sender, uuid.UUID) else uuid.UUID(str(sender))
        self.created_at = conversation.last_message_at

    @property
    def preview(self):
        if self.kind == Message.Kind.BULLETIN:
            return f"Bulletin: {self.body}"
        return self.body or (f"📎 {self.attachment_name}" if self.attachment_name else "")


class Inbox:
    """One user's threads, newest first, each with the other person and its latest message."""

    def __init__(self, user):
        self.user = user

    @cached_property
    def conversations(self):
        result = []
        for conversation in Conversation.objects.for_user(self.user).with_inbox_data(self.user):
            other = conversation.other_party(self.user)
            conversation.other_user = other
            conversation.other_initials = other.initials
            conversation.latest_message = LatestMessage(conversation) if conversation.latest_sender_id else None
            result.append(conversation)
        return result

    @property
    def unread_count(self):
        return sum(c.unread_count for c in self.conversations)

    def to_json(self):
        """Thread list for the Inquiries tab's live refresh (newest first)."""
        return {
            "unread_messages_count": self.unread_count,
            "threads": [self._thread_json(c) for c in self.conversations],
        }

    def _thread_json(self, c):
        latest = c.latest_message
        return {
            "id": str(c.pk),
            "other_name": c.other_user.display_name,
            "other_initials": c.other_initials,
            "other_avatar": c.other_user.avatar_url,
            "other_role": c.other_user.role,
            "subject": c.subject,
            "preview": (("You: " if latest.sender_id == self.user.pk else "") + latest.preview)
                       if latest else "No messages yet.",
            "time_label": time_label(c.last_message_at),
            "unread": c.unread_count,
            "url": reverse("core_inquiries:conversation_detail", args=[c.pk]),
            "reply_url": reverse("core_inquiries:conversation_reply", args=[c.pk]),
        }


# =========================================================
# NOTIFICATIONS (the bell)
# =========================================================

class NotificationFeed(RoleBased, ABC):
    """The bell's list: new messages, request updates and notices from LookApt.

    Polymorphism: landlords and renters hear about different request changes,
    so each subclass answers _application_item() its own way.
    """

    MAX_ITEMS = 8
    # Bell colours: green = new message / good news, yellow = needs a look
    # (new or changed requests), red = cancelled / turned down
    GREEN, YELLOW, RED = "green", "yellow", "red"

    def __init__(self, user, conversations, applications):
        self.user = user
        self.conversations = conversations
        self.applications = applications

    @classmethod
    def for_user(cls, user, conversations=None, applications=None):
        """The right feed for this user. Loads the threads/requests itself when not given
        (the bell on any page); the Inquiries tab passes the ones it already has."""
        feed_class = cls.class_for(user)
        if applications is None:
            applications = list(Application.objects.visible_to(user).prefetch_related(None))   # no photos needed
        if conversations is None:
            conversations = Inbox(user).conversations
        return feed_class(user, conversations, applications)

    def items(self):
        """Newest first, at most MAX_ITEMS, each flagged "is_new" if it came after the bell was last opened."""
        items = self._message_items() + self._request_items() + self._notice_items() + self._extra_items()

        # "Clear all" hides everything up to that moment
        cleared = self.user.notifications_cleared_at
        if cleared:
            items = [item for item in items if item["created_at"] and item["created_at"] > cleared]

        items.sort(key=lambda item: item["created_at"], reverse=True)
        items = items[:self.MAX_ITEMS]

        seen = self.user.notifications_seen_at
        for item in items:
            item["is_new"] = bool(item["created_at"]) and (seen is None or item["created_at"] > seen)
        return items

    @staticmethod
    def _item(key, title, message, when, tone, is_read=True, type_="application"):
        return {
            "id": key, "type": type_, "tone": tone, "is_read": is_read,
            "title": title, "message": message, "created_at": when,
        }

    def _message_items(self):
        return [
            self._item(f"m-{c.pk}", "New message", f"{c.other_user.display_name} messaged you about {c.subject}.",
                       c.last_message_at, self.GREEN, is_read=False, type_="message")
            for c in self.conversations if c.unread_count
        ]

    def _request_items(self):
        items = []
        for application in self.applications:
            where = f"{application.unit.unit_name} at {application.unit.complex.complex_name}"
            item = self._application_item(application, where, f"a-{application.pk}")
            if item:
                items.append(item)
        return items

    @abstractmethod
    def _application_item(self, application, where, key):
        """The notification for one request, or None."""

    def _extra_items(self):
        """Anything else only this kind of user hears about (landlords: reviews)."""
        return []

    def _notice_items(self):
        """Messages from LookApt itself (verification results, report updates ...: core_admin/notify.py)."""
        from core.core_admin.models import Notice
        return [
            self._item(f"n-{notice.pk}", notice.title, notice.message, notice.created_at, notice.tone, type_="account")
            for notice in Notice.objects.filter(user=self.user)[:self.MAX_ITEMS]
        ]


class LandlordNotifications(NotificationFeed):
    ROLE = "landlord"

    # An edit counts as an update only if it came a while after the review was written
    REVIEW_EDIT_GRACE = timedelta(minutes=1)

    def _extra_items(self):
        """A renter left or edited a review of one of your rentals."""
        from core.core_reviews.models import Review
        reviews = (Review.objects.filter(landlord__user=self.user)
                   .select_related("renter__user", "unit__complex")[:self.MAX_ITEMS])
        items = []
        for review in reviews:
            edited = review.updated_at - review.created_at > self.REVIEW_EDIT_GRACE
            name = review.renter.user.display_name
            where = f"{review.unit.unit_name} at {review.unit.complex.complex_name}"
            stars = f"{review.landlord_rating} star{'s' if review.landlord_rating != 1 else ''}"
            items.append(self._item(
                f"r-{review.pk}", "Review updated" if edited else "New review",
                f"{name} {'changed their review' if edited else 'reviewed their stay'} at {where}: {stars} for you.",
                review.updated_at, self.YELLOW, type_="review",
            ))
        return items

    def _application_item(self, a, where, key):
        S = Application.Status
        name = a.renter.user.display_name
        if a.status == S.PENDING and a.edited_at:
            return self._item(key, "Request updated", f"{name} changed their request for {where}: {a.changes_label}.",
                              a.edited_at, self.YELLOW, is_read=False)
        if a.status == S.PENDING:
            return self._item(key, f"New {a.get_kind_display().lower()}", f"{name} applied for {where}.",
                              a.created_at, self.YELLOW, is_read=False)
        if a.status == S.WITHDRAWN:
            return self._item(key, "Request cancelled", f"{name} cancelled their request for {where}.",
                              a.decided_at or a.updated_at, self.RED)
        return None


class RenterNotifications(NotificationFeed):
    ROLE = "renter"

    def _application_item(self, a, where, key):
        S = Application.Status
        when = a.decided_at or a.updated_at
        if a.status == S.WAITLISTED and a.notified_at:
            return self._item(key, "Unit now available", f"{where} is vacant. The landlord sent you a message.",
                              a.notified_at, self.GREEN, is_read=False)
        if a.status == S.WAITLISTED:
            return self._item(key, "Added to the waitlist", f"The landlord approved your waitlist request for {where}.",
                              when, self.YELLOW)
        if a.status == S.ACCEPTED:
            return self._item(key, "Application approved", f"You're the new tenant of {where}. See Rental History.",
                              when, self.GREEN, is_read=False)
        if a.status == S.DECLINED:
            return self._item(key, "Request rejected", f"Your request for {where} was rejected.", when, self.RED)
        if a.status == S.CLOSED:
            return self._item(key, "Request closed", f"{where} was rented to another applicant.", when, self.RED)
        if a.status == S.PENDING and a.site_visit_status in (Application.SiteVisit.CONFIRMED, Application.SiteVisit.DECLINED):
            confirmed = a.site_visit_status == Application.SiteVisit.CONFIRMED
            word = a.get_site_visit_status_display().lower()
            return self._item(f"v-{a.pk}", f"Site visit {word}",
                              f"Your site visit for {where} ({a.visit_label}) was {word}.",
                              a.updated_at, self.GREEN if confirmed else self.RED, type_="site_visit")
        return None
