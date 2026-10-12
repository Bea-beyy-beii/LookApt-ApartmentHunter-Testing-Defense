# core_inquiries/services.py
# Applications (apply / waitlist), messages, and the data for the Inquiries tab.
import os
import uuid
from datetime import timedelta

from dateutil.relativedelta import relativedelta
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Count, OuterRef, Q, Subquery
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from core.core_listings.models import LeaseTerm, Unit
from core.core_listings.services import renter_visible_complexes
from core.models import Renter

from .models import Application, Conversation, Message

LEASE_MONTHS = {
    LeaseTerm.MONTHLY: 1,
    LeaseTerm.QUARTERLY: 3,
    LeaseTerm.BIANNUAL: 6,
    LeaseTerm.ANNUAL: 12,
}
MAX_NAME_LENGTH = 100
MAX_DAYS_AHEAD = 365          # move-in / site visit can't be more than a year away
MAX_NOTIFICATIONS = 8


# =========================================================
# DATES
# =========================================================

def today():
    return timezone.localdate()


def date_label(day):
    """"Nov 30, 2026". Built by hand: strftime's no-padding flag crashes on Windows."""
    return f"{day:%b} {day.day}, {day.year}"


def time_label(moment):
    """"Oct 6, 3:05 PM" in local time."""
    moment = timezone.localtime(moment)
    hour = moment.hour % 12 or 12
    return f"{moment:%b} {moment.day}, {hour}:{moment:%M %p}"


def current_lease_end(unit, on=None):
    """End of the current tenant's lease, or None if we don't know when it started.

    Leases renew: a monthly lease that started Oct 26, 2025 ends on the next
    26th that hasn't passed yet.
    """
    if not unit.occupied_since:
        return None
    on = on or today()
    months = LEASE_MONTHS.get(unit.complex.lease_term, 12)
    end = unit.occupied_since + relativedelta(months=months)
    while end < on:
        end += relativedelta(months=months)
    return end


def earliest_move_in(unit, on=None):
    """First day a renter can move in.

    Available unit -> today.
    Occupied unit  -> current lease end + the landlord's turnover days
                      (or today + turnover days when the lease start isn't set).
    """
    on = on or today()
    if unit.availability == Unit.Availability.AVAILABLE:
        return on
    lease_end = current_lease_end(unit, on) or on
    return lease_end + timedelta(days=unit.complex.turnover_days)


# =========================================================
# APPLICATIONS
# =========================================================

def renter_units():
    """Units a renter may apply to (published, in a visible complex)."""
    return (
        Unit.objects
        .exclude(availability=Unit.Availability.UNPUBLISHED)
        .filter(complex__in=renter_visible_complexes())
        .select_related("complex__landlord__user")
    )


def _clean_occupants(user, unit, names):
    if not isinstance(names, list):
        raise ValidationError({"occupants": "Add the names of everyone who will stay in the unit."})

    # The first tenant is always the account holder (the field is read-only in the form)
    others = [str(name).strip() for name in names[1:]]
    if any(not name for name in others):
        raise ValidationError({"occupants": "Fill in every name, or remove the empty row."})
    if any(len(name) > MAX_NAME_LENGTH for name in others):
        raise ValidationError({"occupants": f"Names can be up to {MAX_NAME_LENGTH} characters."})

    occupants = [user.display_name, *others]
    if len(occupants) > unit.max_occupant:
        raise ValidationError({
            "occupants": f"{unit.unit_name} allows up to {unit.max_occupant} occupant{'s' if unit.max_occupant != 1 else ''}."
        })
    return occupants


def _clean_details(user, unit, kind, occupants, move_in_date, site_visit_date=None, site_visit_time=None):
    """Checks shared by "submit" and "edit". Returns the cleaned values."""
    now = today()
    latest = now + timedelta(days=MAX_DAYS_AHEAD)

    occupants = _clean_occupants(user, unit, occupants)

    earliest = earliest_move_in(unit, now)
    if not move_in_date:
        raise ValidationError({"move_in_date": "Pick your preferred move-in date."})
    if move_in_date < earliest:
        raise ValidationError({"move_in_date": f"The earliest move-in date is {date_label(earliest)}."})
    if move_in_date > max(latest, earliest + timedelta(days=MAX_DAYS_AHEAD)):
        raise ValidationError({"move_in_date": "Pick a move-in date within the next year."})

    if kind == Application.Kind.WAITLIST or not site_visit_date:
        site_visit_date = site_visit_time = None   # occupied units can't be visited
    else:
        if site_visit_date < now:
            raise ValidationError({"site_visit_date": "The site visit can't be in the past."})
        if site_visit_date > move_in_date:
            raise ValidationError({"site_visit_date": "Schedule the site visit on or before your move-in date."})
        if not site_visit_time:
            raise ValidationError({"site_visit_time": "Pick a time for the site visit."})
        if site_visit_date == now and site_visit_time <= timezone.localtime().time():
            raise ValidationError({"site_visit_time": "That time has already passed. Pick a later time."})

    return {
        "occupants": occupants,
        "move_in_date": move_in_date,
        "site_visit_date": site_visit_date,
        "site_visit_time": site_visit_time,
    }


def create_application(user, unit, kind, occupants, move_in_date, site_visit_date=None, site_visit_time=None):
    """Validate and save an application. Raises ValidationError({field: message})."""
    if kind == Application.Kind.APPLY and unit.availability != Unit.Availability.AVAILABLE:
        raise ValidationError({"__all__": f"{unit.unit_name} is no longer available. You can join its waitlist instead."})
    if kind == Application.Kind.WAITLIST and unit.availability != Unit.Availability.OCCUPIED:
        raise ValidationError({"__all__": f"{unit.unit_name} is available now. You can apply right away."})

    details = _clean_details(user, unit, kind, occupants, move_in_date, site_visit_date, site_visit_time)

    renter, _ = Renter.objects.get_or_create(user=user)
    try:
        with transaction.atomic():
            return Application.objects.create(
                renter=renter, unit=unit, kind=kind, **details,
                site_visit_status=Application.SiteVisit.PENDING if details["site_visit_date"] else "",
            )
    except IntegrityError:
        raise ValidationError({"__all__": f"You already have an open application for {unit.unit_name}."})


@transaction.atomic
def edit_application(user, application, occupants, move_in_date, site_visit_date=None, site_visit_time=None):
    """Renter changes a pending request ("Edit Application"). A new site visit
    date/time needs the landlord's confirmation again."""
    if application.status != Application.Status.PENDING:
        raise ValidationError({"__all__": "Only pending requests can be edited."})

    details = _clean_details(
        user, application.unit, application.kind, occupants, move_in_date, site_visit_date, site_visit_time,
    )
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


def unit_demand(unit):
    """Open applications for one unit (pending + waitlisted), e.g. for "3 renters interested"."""
    return unit.applications.filter(status__in=Application.OPEN_STATUSES).count()


# =========================================================
# MESSAGES
# One thread per renter per landlord. Only renters can start one;
# landlords can only reply once the renter has written.
# =========================================================

ATTACHMENT_MAX_MB = 5
ATTACHMENT_TYPES = {
    ".jpg": Message.AttachmentKind.IMAGE,
    ".jpeg": Message.AttachmentKind.IMAGE,
    ".png": Message.AttachmentKind.IMAGE,
    ".mp4": Message.AttachmentKind.VIDEO,
    ".webm": Message.AttachmentKind.VIDEO,
    ".mov": Message.AttachmentKind.VIDEO,
    ".pdf": Message.AttachmentKind.PDF,
}


def size_label(size):
    return f"{size / (1024 * 1024):.1f} MB" if size >= 1024 * 1024 else f"{max(1, round(size / 1024))} KB"


def _content_matches(upload, kind):
    """Check the file's content, not just its name (a renamed .exe must not pass)."""
    head = upload.read(12)
    upload.seek(0)
    if kind == Message.AttachmentKind.PDF:
        return head[:5] == b"%PDF-"
    if kind == Message.AttachmentKind.VIDEO:
        return head[4:8] == b"ftyp" or head[:4] == b"\x1a\x45\xdf\xa3"   # MP4/MOV or WebM
    try:
        with Image.open(upload) as image:
            ok = image.format in ("JPEG", "PNG")
            image.verify()
        return ok
    except Exception:
        return False
    finally:
        upload.seek(0)


def clean_attachment(upload):
    """Validate an uploaded file. Returns its kind ("image" / "video" / "pdf")."""
    kind = ATTACHMENT_TYPES.get(os.path.splitext(upload.name)[1].lower())
    if not kind:
        raise ValidationError({"attachment": "You can send photos (JPG, PNG), videos (MP4, WebM, MOV) or PDF files."})
    if upload.size > ATTACHMENT_MAX_MB * 1024 * 1024:
        raise ValidationError({"attachment": f"Files can be up to {ATTACHMENT_MAX_MB} MB ({upload.name} is {size_label(upload.size)})."})
    if not _content_matches(upload, kind):
        raise ValidationError({"attachment": f"{upload.name} doesn't look like a real {kind} file."})
    return kind


def _clean_body(body, has_attachment=False):
    body = (body or "").strip()
    if not body and not has_attachment:
        raise ValidationError({"body": "Type a message or attach a file first."})
    if len(body) > Message.MAX_LENGTH:
        raise ValidationError({"body": f"Messages can be up to {Message.MAX_LENGTH} characters."})
    return body


def renter_conversation(user, landlord):
    """The renter's thread with this landlord, or None."""
    return Conversation.objects.filter(renter__user=user, landlord=landlord).first()


def _subject(unit, complex_obj):
    return f"{unit.unit_name} · {complex_obj.complex_name}" if unit else complex_obj.complex_name


@transaction.atomic
def start_or_continue_inquiry(user, body, unit=None, complex_obj=None, attachment=None):
    """Renter sends a message about a unit/complex from a listing page.

    Always lands in the renter's single thread with that landlord. When the
    renter asks about a different unit/complex, the message carries a "topic"
    so both sides can see what it's about.
    """
    kind = clean_attachment(attachment) if attachment else ""
    body = _clean_body(body, bool(attachment))
    complex_obj = unit.complex if unit else complex_obj
    renter, _ = Renter.objects.get_or_create(user=user)
    subject = _subject(unit, complex_obj)

    conversation = renter_conversation(user, complex_obj.landlord)
    if conversation is None:
        conversation = Conversation.objects.create(
            renter=renter, landlord=complex_obj.landlord, complex=complex_obj, unit=unit,
        )
        topic = subject
    elif conversation.subject != subject:
        conversation.complex, conversation.unit = complex_obj, unit
        conversation.save(update_fields=["complex", "unit"])
        topic = subject
    else:
        topic = ""

    return _add_message(conversation, user, body, attachment, kind, topic)


def user_conversations(user):
    """Threads this user takes part in (as renter or as landlord)."""
    return Conversation.objects.filter(Q(renter__user=user) | Q(landlord__user=user))


def landlord_can_contact(landlord_user, renter):
    """A landlord may write first only to renters with a real link to them:
    a current/past tenant, or someone who applied to one of their units."""
    from core.core_rentals.models import Tenancy   # imported here: core_rentals imports this module
    mine = Q(unit__complex__landlord__user=landlord_user)
    return (
        Tenancy.objects.filter(mine, renter=renter).exists()
        or Application.objects.filter(mine, renter=renter).exists()
    )


def can_send(user, conversation):
    """Renters can always reply in their own thread.
    Landlords can reply once the renter has written first, or when the
    renter is/was their tenant or applied to one of their units."""
    if conversation.renter.user_id == user.pk:
        return True
    if conversation.landlord.user_id == user.pk:
        return (
            conversation.messages.filter(sender=conversation.renter.user).exists()
            or landlord_can_contact(user, conversation.renter)
        )
    return False


def landlord_conversation(landlord_user, renter):
    return Conversation.objects.filter(landlord__user=landlord_user, renter=renter).first()


@transaction.atomic
def start_landlord_message(user, renter, body, attachment=None, message_kind=Message.Kind.MESSAGE, bulletin_event=""):
    """Landlord writes to a tenant/applicant from Manage Rentals (creates the thread if needed).
    message_kind=BULLETIN: a Post on Bulletin announcement (shown as a banner, core_calendar)."""
    if not landlord_can_contact(user, renter):
        raise PermissionDenied("You can only message renters who rent from you, applied to your units, or messaged you first.")
    kind = clean_attachment(attachment) if attachment else ""
    body = _clean_body(body, bool(attachment))

    conversation = landlord_conversation(user, renter)
    if conversation is None:
        # What the thread is about: their latest rental, else their latest application
        from core.core_rentals.models import Tenancy
        link = (
            Tenancy.objects.filter(renter=renter, unit__complex__landlord__user=user).select_related("unit__complex").first()
            or Application.objects.filter(renter=renter, unit__complex__landlord__user=user).select_related("unit__complex").first()
        )
        conversation = Conversation.objects.create(
            renter=renter, landlord=user.landlord, complex=link.unit.complex, unit=link.unit,
        )
    return _add_message(conversation, user, body, attachment, kind,
                        message_kind=message_kind, bulletin_event=bulletin_event)


@transaction.atomic
def reply(user, conversation, body, attachment=None):
    if not can_send(user, conversation):
        raise PermissionDenied("You can only reply to renters who messaged you first.")
    kind = clean_attachment(attachment) if attachment else ""
    body = _clean_body(body, bool(attachment))
    return _add_message(conversation, user, body, attachment, kind)


def _add_message(conversation, user, body, attachment=None, kind="", topic="",
                 message_kind=Message.Kind.MESSAGE, bulletin_event=""):
    message = Message(conversation=conversation, sender=user, body=body, topic=topic,
                      kind=message_kind, bulletin_event=bulletin_event[:200])
    if attachment:
        message.attachment = attachment
        message.attachment_name = os.path.basename(attachment.name)[:255]
        message.attachment_kind = kind
        message.attachment_size = attachment.size
    message.save()

    conversation.last_message_at = message.created_at
    conversation.save(update_fields=["last_message_at"])
    return message


def mark_read(user, conversation):
    conversation.messages.filter(read_at__isnull=True).exclude(sender=user).update(read_at=timezone.now())


def other_party(user, conversation):
    """The person on the other side of the thread (a User)."""
    if conversation.renter.user_id == user.pk:
        return conversation.landlord.user
    return conversation.renter.user


def initials(user):
    return f"{user.first_name[:1]}{user.last_name[:1]}".upper()


def message_json(user, message):
    data = {
        "id": message.pk,
        "body": message.body,
        "topic": message.topic,
        "kind": message.kind,                       # "bulletin" = announcement banner (chat.js)
        "bulletin_event": message.bulletin_event,
        "mine": message.sender_id == user.pk,
        "created_at": message.created_at.isoformat(),
        "time_label": time_label(message.created_at),
        "seen": message.read_at is not None,
        "seen_label": time_label(message.read_at) if message.read_at else "",
        "attachment": None,
    }
    if message.attachment:
        data["attachment"] = {
            "url": message.attachment.url,
            "name": message.attachment_name,
            "kind": message.attachment_kind,
            "size_label": size_label(message.attachment_size),
        }
    return data


def conversation_json(user, conversation, after=None):
    """The thread for the pop-up / Inquiries tab.

    after=<message id>: only newer messages (used by the 4-second refresh).
    Seen status is always sent for this user's messages, so ✓✓ can update.
    """
    other = other_party(user, conversation)
    messages = conversation.messages.all()
    if after:
        messages = messages.filter(pk__gt=after)

    seen_ids = list(
        conversation.messages.filter(sender=user, read_at__isnull=False).values_list("pk", "read_at")
    )

    return {
        "id": str(conversation.pk),
        "subject": conversation.subject,
        "other_name": other.display_name,
        "other_initials": initials(other),
        "other_avatar": other.avatar_url,
        "other_role": other.role,
        "other_verified": other.is_verified,
        "can_send": can_send(user, conversation),
        "messages": [message_json(user, m) for m in messages],
        "seen": {str(pk): time_label(read_at) for pk, read_at in seen_ids},
        "detail_url": reverse("core_inquiries:conversation_detail", args=[conversation.pk]),
        "reply_url": reverse("core_inquiries:conversation_reply", args=[conversation.pk]),
    }


# =========================================================
# INQUIRIES TAB (renter + landlord dashboards)
# =========================================================

class _Latest:
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


def _conversations_for_tab(user):
    latest = Message.objects.filter(conversation=OuterRef("pk")).order_by("-created_at", "-pk")
    conversations = (
        user_conversations(user)
        .select_related("renter__user", "landlord__user", "complex", "unit")
        .annotate(
            unread_count=Count("messages", filter=Q(messages__read_at__isnull=True) & ~Q(messages__sender=user)),
            latest_body=Subquery(latest.values("body")[:1]),
            latest_kind=Subquery(latest.values("kind")[:1]),
            latest_attachment_name=Subquery(latest.values("attachment_name")[:1]),
            latest_sender_id=Subquery(latest.values("sender_id")[:1]),
        )
        .order_by("-last_message_at")   # newest conversation on top
    )
    result = []
    for conversation in conversations:
        other = other_party(user, conversation)
        conversation.other_user = other
        conversation.other_initials = initials(other)
        conversation.latest_message = _Latest(conversation) if conversation.latest_sender_id else None
        result.append(conversation)
    return result


def inbox_json(user):
    """Thread list for the Inquiries tab's live refresh (newest first)."""
    conversations = _conversations_for_tab(user)
    return {
        "unread_messages_count": sum(c.unread_count for c in conversations),
        "threads": [
            {
                "id": str(c.pk),
                "other_name": c.other_user.display_name,
                "other_initials": c.other_initials,
                "other_avatar": c.other_user.avatar_url,
                "other_role": c.other_user.role,
                "subject": c.subject,
                "preview": (("You: " if c.latest_message.sender_id == user.pk else "") + c.latest_message.preview)
                           if c.latest_message else "No messages yet.",
                "time_label": time_label(c.last_message_at),
                "unread": c.unread_count,
                "url": reverse("core_inquiries:conversation_detail", args=[c.pk]),
                "reply_url": reverse("core_inquiries:conversation_reply", args=[c.pk]),
            }
            for c in conversations
        ],
    }


# Bell colours: green = new message / good news, yellow = needs a look
# (new or changed requests), red = cancelled / turned down
GREEN, YELLOW, RED = "green", "yellow", "red"


def _notification(key, title, message, when, tone, is_read=True, type_="application"):
    return {
        "id": key, "type": type_, "tone": tone, "is_read": is_read,
        "title": title, "message": message, "created_at": when,
    }


def _changes(application):
    """"move-in Nov 1, 2026 · site visit Oct 25, 2026 · 2:00 PM" (what an edit set)."""
    parts = [f"move-in {date_label(application.move_in_date)}"]
    if application.site_visit_date:
        parts.append(f"site visit {application.visit_label}")
    return " · ".join(parts)


def _notifications(user, conversations, applications):
    items = []

    for conversation in conversations:
        if conversation.unread_count:
            items.append(_notification(
                f"m-{conversation.pk}", "New message",
                f"{conversation.other_user.display_name} messaged you about {conversation.subject}.",
                conversation.last_message_at, GREEN, is_read=False, type_="message",
            ))

    S = Application.Status
    for a in applications:
        where = f"{a.unit.unit_name} at {a.unit.complex.complex_name}"
        when = a.decided_at or a.updated_at
        key = f"a-{a.pk}"

        if user.role == "landlord":
            name = a.renter.user.display_name
            if a.status == S.PENDING and a.edited_at:
                items.append(_notification(key, "Request updated",
                                           f"{name} changed their request for {where}: {_changes(a)}.",
                                           a.edited_at, YELLOW, is_read=False))
            elif a.status == S.PENDING:
                items.append(_notification(key, f"New {a.get_kind_display().lower()}",
                                           f"{name} applied for {where}.", a.created_at, YELLOW, is_read=False))
            elif a.status == S.WITHDRAWN:
                items.append(_notification(key, "Request cancelled",
                                           f"{name} cancelled their request for {where}.", when, RED))
            continue

        if a.status == S.WAITLISTED and a.notified_at:
            items.append(_notification(key, "Unit now available",
                                       f"{where} is vacant. The landlord sent you a message.", a.notified_at, GREEN, is_read=False))
        elif a.status == S.WAITLISTED:
            items.append(_notification(key, "Added to the waitlist", f"The landlord approved your waitlist request for {where}.", when, YELLOW))
        elif a.status == S.ACCEPTED:
            items.append(_notification(key, "Application approved",
                                       f"You're the new tenant of {where}. See Rental History.", when, GREEN, is_read=False))
        elif a.status == S.DECLINED:
            items.append(_notification(key, "Request rejected", f"Your request for {where} was rejected.", when, RED))
        elif a.status == S.CLOSED:
            items.append(_notification(key, "Request closed", f"{where} was rented to another applicant.", when, RED))
        elif a.status == S.PENDING and a.site_visit_status in (Application.SiteVisit.CONFIRMED, Application.SiteVisit.DECLINED):
            confirmed = a.site_visit_status == Application.SiteVisit.CONFIRMED
            items.append(_notification(f"v-{a.pk}", f"Site visit {a.get_site_visit_status_display().lower()}",
                                       f"Your site visit for {where} ({a.visit_label}) was {a.get_site_visit_status_display().lower()}.",
                                       a.updated_at, GREEN if confirmed else RED, type_="site_visit"))

    # Messages from LookApt itself (verification results, report updates ...: core_admin/notify.py)
    from core.core_admin.models import Notice
    for notice in Notice.objects.filter(user=user)[:MAX_NOTIFICATIONS]:
        items.append(_notification(f"n-{notice.pk}", notice.title, notice.message, notice.created_at,
                                   notice.tone, type_="account"))

    items.sort(key=lambda item: item["created_at"], reverse=True)
    return items[:MAX_NOTIFICATIONS]


def mark_new(user, items):
    """Flag the notifications that arrived after the user last opened the bell."""
    seen = user.notifications_seen_at
    for item in items:
        item["is_new"] = bool(item["created_at"]) and (seen is None or item["created_at"] > seen)
    return items


def notifications_for(user):
    """The bell's list on any page (the Inquiries tab builds the same list itself)."""
    from .workflow import _visible, visit_label

    applications = list(_visible(user).prefetch_related(None))   # no photos needed here
    for application in applications:
        application.visit_label = visit_label(application)
    return mark_new(user, _notifications(user, _conversations_for_tab(user), applications))


def get_inquiries_context(user):
    from .workflow import request_tabs   # workflow imports core_rentals, which imports this module

    conversations = _conversations_for_tab(user)
    tabs = request_tabs(user, conversations)
    notifications = mark_new(user, _notifications(user, conversations, tabs.pop("all_requests")))

    return {
        "conversations": conversations,
        **tabs,
        "unread_messages_count": sum(c.unread_count for c in conversations),
        "notifications": notifications,
        "unread_notifications_count": sum(1 for n in notifications if not n["is_read"]),
        "new_notifications_count": sum(1 for n in notifications if n["is_new"]),
        "is_landlord_inbox": user.role == "landlord",
    }