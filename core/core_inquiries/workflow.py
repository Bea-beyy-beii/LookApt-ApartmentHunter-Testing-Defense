# core_inquiries/workflow.py
# Pending Requests / Waitlist / Archive (Inquiries tab, both sides).
#
#   pending ──"Approve as Tenant"──▶ accepted   (a Tenancy: Manage Rentals / Rental History)
#      │    ──"Approve for Waitlist"▶ waitlisted ──assigned in Manage Rentals──▶ accepted
#      │                                  │
#      └──"Reject" / "Cancel"─────────────┴──▶ declined / withdrawn ──▶ Archive (30 days)
#
# Once a renter is assigned to a unit, every other open request for it is
# "closed" (core_rentals.services.assign_tenant) and lands in the Archive too.
# "Approve as Tenant" posts to core_rentals:assign_tenant, the same endpoint
# as "Assign a Renter" in Manage Rentals, so both pages always agree.
import json
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from core.core_listings.models import Unit
from core.core_rentals.models import Tenancy
from core.core_rentals.services import ENDING_SOON_DAYS, current_term, lease_months

from .models import Application
from .services import (
    current_lease_end, date_label, earliest_move_in, initials, start_landlord_message, time_label, today,
)

ARCHIVE_DAYS = 30
MAX_NOTE = 500

R = Application.Reason
LANDLORD_REASONS = [R.UNIT_UNAVAILABLE, R.REQUIREMENTS, R.MOVE_IN_DATE, R.OCCUPANTS, R.CHOSE_OTHER, R.OTHER]
RENTER_REASONS = [R.FOUND_OTHER, R.PLANS_CHANGED, R.MOVE_IN_DATE, R.BUDGET, R.LOCATION, R.OTHER]


# =========================================================
# LOOKUPS
# =========================================================

def _base():
    return Application.objects.select_related("renter__user", "unit__complex__landlord__user")


def landlord_application(user, pk):
    """An application to one of this landlord's units (raises DoesNotExist)."""
    return _base().get(pk=pk, unit__complex__landlord__user=user)


def renter_application(user, pk):
    """One of this renter's own applications (raises DoesNotExist)."""
    return _base().get(pk=pk, renter__user=user)


def unit_is_vacant(unit):
    return (
        unit.availability == Unit.Availability.AVAILABLE
        and not unit.tenancies.filter(status=Tenancy.Status.ACTIVE).exists()
    )


# =========================================================
# ACTIONS
# =========================================================

def _clean_reason(reason, note, allowed, required):
    note = (note or "").strip()
    if len(note) > MAX_NOTE:
        raise ValidationError({"reason_note": f"Keep it under {MAX_NOTE} characters."})
    if not reason:
        if required:
            raise ValidationError({"reason": "Pick a reason."})
        return "", note
    if reason not in allowed:
        raise ValidationError({"reason": "Pick one of the listed reasons."})
    if reason == R.OTHER and not note:
        raise ValidationError({"reason_note": "Tell them the reason in a few words."})
    return reason, note


def _close(application, status, reason="", note=""):
    application.status = status
    application.reason = reason
    application.reason_note = note
    application.decided_at = timezone.now()
    application.save(update_fields=["status", "reason", "reason_note", "decided_at", "updated_at"])
    return application


@transaction.atomic
def reject(application, reason, note=""):
    """Landlord: "Reject Request" (pending) or "Remove from Waitlist" (waitlisted). Reason required."""
    if not application.is_open:
        raise ValidationError({"__all__": "This request was already closed."})
    reason, note = _clean_reason(reason, note, LANDLORD_REASONS, required=True)
    return _close(application, Application.Status.DECLINED, reason, note)


@transaction.atomic
def cancel(application, reason="", note=""):
    """Renter: "Cancel Application" / "Leave Waitlist". The reason is optional."""
    if not application.is_open:
        raise ValidationError({"__all__": "This request was already closed."})
    reason, note = _clean_reason(reason, note, RENTER_REASONS, required=False)
    return _close(application, Application.Status.WITHDRAWN, reason, note)


@transaction.atomic
def approve_waitlist(application):
    """Landlord: "Approve for Waitlist" (waitlist requests only)."""
    if application.status != Application.Status.PENDING:
        raise ValidationError({"__all__": "Only pending requests can be approved."})
    if application.kind != Application.Kind.WAITLIST:
        raise ValidationError({"__all__": "This is a tenant application. Approve it as a tenant instead."})
    application.status = Application.Status.WAITLISTED
    application.decided_at = timezone.now()
    application.save(update_fields=["status", "decided_at", "updated_at"])
    return application


@transaction.atomic
def notify_applicant(landlord_user, application):
    """Landlord: "Notify Applicant" once a waitlisted unit is vacant.
    Sends the renter a message (Inquiries → Messages) and remembers when."""
    if application.status != Application.Status.WAITLISTED:
        raise ValidationError({"__all__": "Only renters on the waitlist can be notified."})
    unit = application.unit
    if not unit_is_vacant(unit):
        raise ValidationError({"__all__": f"{unit.unit_name} isn't vacant yet."})

    start_landlord_message(
        landlord_user, application.renter,
        f"Good news! {unit.unit_name} at {unit.complex.complex_name} is now available. "
        f"You're on its waitlist, so let me know if you're still interested and we can arrange your move-in.",
    )
    application.notified_at = timezone.now()
    application.save(update_fields=["notified_at", "updated_at"])
    return application


@transaction.atomic
def decide_site_visit(application, decision):
    """Landlord confirms or declines the site visit a renter asked for."""
    if application.status != Application.Status.PENDING:
        raise ValidationError({"__all__": "This request is no longer pending."})
    if not application.site_visit_date:
        raise ValidationError({"__all__": "No site visit was requested."})
    choices = {"confirm": Application.SiteVisit.CONFIRMED, "decline": Application.SiteVisit.DECLINED}
    if decision not in choices:
        raise ValidationError({"__all__": "Unknown action."})
    application.site_visit_status = choices[decision]
    application.save(update_fields=["site_visit_status", "updated_at"])
    return application


# =========================================================
# TAB DATA
# =========================================================

def _cover(pictures):
    pictures = list(pictures)
    cover = next((p for p in pictures if p.is_cover), None) or (pictures[0] if pictures else None)
    return (cover.image.url if cover else ""), len(pictures)


def unit_outlook(unit, tenancy, on):
    """Waitlist header: is the unit vacant, occupied, or about to be free?"""
    if tenancy is None and unit.availability == Unit.Availability.AVAILABLE:
        return {"key": "vacant", "label": "Vacant", "expected": None}
    if tenancy is not None:
        _, end = current_term(tenancy, on)
        expected = end + timedelta(days=1 + unit.complex.turnover_days)
        ending = lease_months(unit) > 1 and (end - on).days <= ENDING_SOON_DAYS
    else:
        expected = earliest_move_in(unit, on)
        ending = False
    if ending:
        return {"key": "ending", "label": "Tenancy Ending Soon", "expected": expected}
    return {"key": "occupied", "label": "Currently Occupied", "expected": expected}


def _chat(user, application, conversation):
    """What the Message column and the chat pop-up need."""
    landlord_view = user.role == "landlord"
    other = application.renter.user if landlord_view else application.unit.complex.landlord.user
    latest = conversation.latest_message if conversation else None
    return {
        "name": other.display_name,
        "initials": initials(other),
        "subject": f"{application.unit.unit_name} · {application.unit.complex.complex_name}",
        "detail_url": reverse("core_inquiries:conversation_detail", args=[conversation.pk]) if conversation else "",
        "send_url": reverse("core_inquiries:send_to_renter" if landlord_view else "core_inquiries:send_inquiry"),
        "send_params": json.dumps({"renter": str(application.renter_id)} if landlord_view else {"unit": str(application.unit_id)}),
        "preview": latest.preview if latest else "",
        "mine": bool(latest and latest.sender_id == user.pk),
        "time": time_label(latest.created_at) if latest else "",
        "unread": conversation.unread_count if conversation else 0,
    }


def _decorate(user, application, conversation, on):
    unit = application.unit
    application.cover_url, application.photo_count = _cover(unit.pictures.all())
    if not application.cover_url:
        application.cover_url, application.photo_count = _cover(unit.complex.pictures.all())

    renter_user = application.renter.user
    application.renter_name = renter_user.display_name
    application.renter_initials = initials(renter_user)
    application.renter_avatar = renter_user.avatar_url
    application.renter_contact = renter_user.shared_contact       # only what the renter chose to share (Settings)
    landlord_user = unit.complex.landlord.user
    application.landlord_name = landlord_user.display_name
    application.landlord_initials = initials(landlord_user)
    application.landlord_avatar = landlord_user.avatar_url
    application.landlord_verified = landlord_user.is_verified
    application.other_occupants = application.occupants[1:]
    application.chat = _chat(user, application, conversation)
    application.since = application.decided_at or application.created_at
    application.visit_label = visit_label(application)
    application.can_notify = False      # set for vacant units in the waitlist

    if user.role == "renter" and application.status == Application.Status.PENDING:
        # "Edit Application" re-opens the form with these values
        application.earliest_move_in = earliest_move_in(unit, on)
        application.lease_known = current_lease_end(unit, on) is not None
        visit_time = application.site_visit_time
        application.prefill_json = json.dumps({
            "occupants": application.occupants[1:],
            "move_in_date": application.move_in_date.isoformat(),
            "site_visit_date": application.site_visit_date.isoformat() if application.site_visit_date else "",
            "site_visit_time": visit_time.strftime("%H:%M") if visit_time else "",
        })
    return application


def _visible(user):
    scope = Q(unit__complex__landlord__user=user) if user.role == "landlord" else Q(renter__user=user)
    cutoff = timezone.now() - timedelta(days=ARCHIVE_DAYS)
    return (
        _base()
        .filter(scope)
        .filter(Q(status__in=Application.OPEN_STATUSES) | Q(decided_at__gte=cutoff))
        .prefetch_related("unit__pictures", "unit__complex__pictures")
    )


def request_tabs(user, conversations):
    """Everything the Pending Requests / Waitlist / Archive tabs show.

    conversations: this user's threads from services._conversations_for_tab
    (one per renter-landlord pair), used for the Message column.
    """
    on = today()
    landlord_view = user.role == "landlord"
    by_pair = {
        (c.renter_id, c.landlord_id): c for c in conversations
    }

    applications = list(_visible(user))
    for application in applications:
        pair = (application.renter_id, application.unit.complex.landlord_id)
        _decorate(user, application, by_pair.get(pair), on)

    pending = [a for a in applications if a.status == Application.Status.PENDING]
    waitlisted = sorted(
        (a for a in applications if a.status == Application.Status.WAITLISTED), key=lambda a: a.since,
    )
    archived = sorted(
        (a for a in applications if a.status in Application.ARCHIVED_STATUSES),
        key=lambda a: a.since, reverse=True,
    )

    # Is each waitlisted unit vacant / occupied / ending soon?
    unit_ids = {a.unit_id for a in waitlisted}
    tenancies = {
        t.unit_id: t
        for t in Tenancy.objects.filter(unit_id__in=unit_ids, status=Tenancy.Status.ACTIVE).select_related("unit__complex")
    }
    groups = {}
    for application in waitlisted:
        unit = application.unit
        if unit.pk not in groups:
            groups[unit.pk] = {
                "unit": unit,
                "cover_url": application.cover_url,
                "photo_count": application.photo_count,
                "outlook": unit_outlook(unit, tenancies.get(unit.pk), on),
                "applications": [],
            }
        group = groups[unit.pk]
        application.outlook = group["outlook"]
        application.can_notify = group["outlook"]["key"] == "vacant"
        group["applications"].append(application)

    return {
        "pending_requests": pending,
        "waitlist_groups": list(groups.values()),
        "waitlisted_requests": waitlisted,
        "archived_requests": archived,
        "pending_requests_count": len(pending),
        "waitlist_count": len(waitlisted),
        "archive_count": len(archived),
        "archive_days": ARCHIVE_DAYS,
        "reject_reasons": [(r.value, r.label) for r in LANDLORD_REASONS],
        "cancel_reasons": [(r.value, r.label) for r in RENTER_REASONS],
        # Every request (incl. recently approved ones) for the notifications panel
        "all_requests": applications,
    }


def visit_label(application):
    """"Oct 25, 2026 · 2:00 PM"."""
    if not application.site_visit_date:
        return ""
    label = date_label(application.site_visit_date)
    if application.site_visit_time:
        t = application.site_visit_time
        label += f" · {t.hour % 12 or 12}:{t:%M %p}"
    return label