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
#
# Each other arrow is a RequestAction subclass; RequestTabs builds the tabs.
import json
from abc import ABC, abstractmethod
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.urls import reverse
from django.utils.functional import cached_property

from core.core_listings.models import Unit
from core.core_rentals.models import Tenancy
from core.core_rentals.services import ENDING_SOON_DAYS, current_term, lease_months

from .labels import time_label
from .models import Application
from .services import LandlordMessage, LeaseSchedule, today

R = Application.Reason
S = Application.Status


# =========================================================
# ACTIONS (one class per button on a request card)
# =========================================================

class RequestAction(ABC):
    """One status change of a request, done by `actor` with the posted `data`.

    Template method: run() checks the request is in one of `from_statuses`,
    then the subclass's own _check() and _apply(). Each subclass also writes
    the message the page shows when it worked.
    """

    from_statuses = ()
    wrong_status_message = ""

    def __init__(self, application, actor=None, data=None):
        self.application = application
        self.actor = actor
        self.data = data or {}

    @transaction.atomic
    def run(self):
        if self.application.status not in self.from_statuses:
            raise ValidationError({"__all__": self.wrong_status_message})
        self._check()
        self._apply()
        return self.application

    def _check(self):
        """Extra checks before the change (raise ValidationError)."""

    @abstractmethod
    def _apply(self):
        """Change the request."""

    @property
    @abstractmethod
    def success_message(self):
        """What the page shows once it's done."""

    @property
    def renter_name(self):
        return self.application.renter.user.display_name

    @property
    def unit_name(self):
        return self.application.unit.unit_name


class CloseRequest(RequestAction):
    """Moves an open request to the Archive with a reason from `reasons`."""

    from_statuses = Application.OPEN_STATUSES
    wrong_status_message = "This request was already closed."
    MAX_NOTE = 500

    new_status = None
    reasons = ()
    reason_required = False

    @classmethod
    def reason_choices(cls):
        """(value, label) pairs for the form's dropdown."""
        return [(reason.value, reason.label) for reason in cls.reasons]

    def _check(self):
        reason = self.data.get("reason")
        note = (self.data.get("reason_note") or "").strip()
        if len(note) > self.MAX_NOTE:
            raise ValidationError({"reason_note": f"Keep it under {self.MAX_NOTE} characters."})
        if not reason:
            if self.reason_required:
                raise ValidationError({"reason": "Pick a reason."})
            reason = ""
        elif reason not in self.reasons:
            raise ValidationError({"reason": "Pick one of the listed reasons."})
        elif reason == R.OTHER and not note:
            raise ValidationError({"reason_note": "Tell them the reason in a few words."})
        self.reason, self.note = reason, note

    def _apply(self):
        self.application.close(self.new_status, self.reason, self.note)


class RejectRequest(CloseRequest):
    """Landlord: "Reject Request" (pending) or "Remove from Waitlist" (waitlisted). Reason required."""

    new_status = S.DECLINED
    reasons = (R.UNIT_UNAVAILABLE, R.REQUIREMENTS, R.MOVE_IN_DATE, R.OCCUPANTS, R.CHOSE_OTHER, R.OTHER)
    reason_required = True

    def __init__(self, application, actor=None, data=None):
        super().__init__(application, actor, data)
        self.was_waitlisted = application.status == S.WAITLISTED

    @property
    def success_message(self):
        action = "removed from the waitlist" if self.was_waitlisted else "rejected"
        return f"{self.renter_name}'s request was {action} and moved to the Archive."


class CancelRequest(CloseRequest):
    """Renter: "Cancel Application" / "Leave Waitlist". The reason is optional."""

    new_status = S.WITHDRAWN
    reasons = (R.FOUND_OTHER, R.PLANS_CHANGED, R.MOVE_IN_DATE, R.BUDGET, R.LOCATION, R.OTHER)

    @property
    def success_message(self):
        return f"Your request for {self.unit_name} was cancelled."


class ApproveWaitlist(RequestAction):
    """Landlord: "Approve for Waitlist" (waitlist requests only)."""

    from_statuses = (S.PENDING,)
    wrong_status_message = "Only pending requests can be approved."

    def _check(self):
        if self.application.kind != Application.Kind.WAITLIST:
            raise ValidationError({"__all__": "This is a tenant application. Approve it as a tenant instead."})

    def _apply(self):
        self.application.move_to_waitlist()

    @property
    def success_message(self):
        return f"{self.renter_name} is now on the waitlist for {self.unit_name}."


class NotifyApplicant(RequestAction):
    """Landlord: "Notify Applicant" once a waitlisted unit is vacant.
    Sends the renter a message (Inquiries → Messages) and remembers when."""

    from_statuses = (S.WAITLISTED,)
    wrong_status_message = "Only renters on the waitlist can be notified."

    def _check(self):
        if not self.unit_is_vacant(self.application.unit):
            raise ValidationError({"__all__": f"{self.unit_name} isn't vacant yet."})

    @staticmethod
    def unit_is_vacant(unit):
        return (
            unit.availability == Unit.Availability.AVAILABLE
            and not unit.tenancies.filter(status=Tenancy.Status.ACTIVE).exists()
        )

    def _apply(self):
        unit = self.application.unit
        LandlordMessage(self.actor, self.application.renter).send(
            f"Good news! {unit.unit_name} at {unit.complex.complex_name} is now available. "
            f"You're on its waitlist, so let me know if you're still interested and we can arrange your move-in.",
        )
        self.application.mark_notified()

    @property
    def success_message(self):
        return f"{self.renter_name} was notified that {self.unit_name} is available."


class DecideSiteVisit(RequestAction):
    """Landlord confirms or declines the site visit a renter asked for."""

    from_statuses = (S.PENDING,)
    wrong_status_message = "This request is no longer pending."
    DECISIONS = {"confirm": Application.SiteVisit.CONFIRMED, "decline": Application.SiteVisit.DECLINED}

    def _check(self):
        if not self.application.site_visit_date:
            raise ValidationError({"__all__": "No site visit was requested."})
        if self.data.get("decision") not in self.DECISIONS:
            raise ValidationError({"__all__": "Unknown action."})

    def _apply(self):
        self.application.set_site_visit_status(self.DECISIONS[self.data["decision"]])

    @property
    def success_message(self):
        word = self.application.get_site_visit_status_display().lower()
        return f"Site visit {word} for {self.renter_name} ({self.application.visit_label})."


# =========================================================
# TAB DATA
# =========================================================

class RequestTabs:
    """Everything the Pending Requests / Waitlist / Archive tabs show for one user.

    conversations: this user's threads from Inbox (one per renter-landlord
    pair), used for the Message column.
    """

    def __init__(self, user, conversations, on=None):
        self.user = user
        self.landlord_view = user.is_landlord
        self.on = on or today()
        self.by_pair = {(c.renter_id, c.landlord_id): c for c in conversations}

    @cached_property
    def applications(self):
        """Every visible request (incl. recently approved ones), decorated for the cards."""
        applications = list(Application.objects.visible_to(self.user))
        for application in applications:
            pair = (application.renter_id, application.unit.complex.landlord_id)
            self._decorate(application, self.by_pair.get(pair))
        return applications

    @property
    def pending(self):
        return [a for a in self.applications if a.status == S.PENDING]

    @cached_property
    def waitlisted(self):
        return sorted((a for a in self.applications if a.status == S.WAITLISTED), key=lambda a: a.since)

    @property
    def archived(self):
        return sorted(
            (a for a in self.applications if a.status in Application.ARCHIVED_STATUSES),
            key=lambda a: a.since, reverse=True,
        )

    def context(self):
        pending, waitlisted, archived = self.pending, self.waitlisted, self.archived
        return {
            "pending_requests": pending,
            "waitlist_groups": self._waitlist_groups(),
            "waitlisted_requests": waitlisted,
            "archived_requests": archived,
            "pending_requests_count": len(pending),
            "waitlist_count": len(waitlisted),
            "archive_count": len(archived),
            "archive_days": Application.ARCHIVE_DAYS,
            "reject_reasons": RejectRequest.reason_choices(),
            "cancel_reasons": CancelRequest.reason_choices(),
        }

    # ---------- waitlist: one group per unit

    def _waitlist_groups(self):
        """Is each waitlisted unit vacant / occupied / ending soon?"""
        unit_ids = {a.unit_id for a in self.waitlisted}
        tenancies = {
            t.unit_id: t
            for t in Tenancy.objects.filter(unit_id__in=unit_ids, status=Tenancy.Status.ACTIVE).select_related("unit__complex")
        }
        groups = {}
        for application in self.waitlisted:
            unit = application.unit
            if unit.pk not in groups:
                groups[unit.pk] = {
                    "unit": unit,
                    "cover_url": application.cover_url,
                    "photo_count": application.photo_count,
                    "outlook": self._outlook(unit, tenancies.get(unit.pk)),
                    "applications": [],
                }
            group = groups[unit.pk]
            application.outlook = group["outlook"]
            application.can_notify = group["outlook"]["key"] == "vacant"
            group["applications"].append(application)
        return list(groups.values())

    def _outlook(self, unit, tenancy):
        """Waitlist header: is the unit vacant, occupied, or about to be free?"""
        on = self.on
        if tenancy is None and unit.availability == Unit.Availability.AVAILABLE:
            return {"key": "vacant", "label": "Vacant", "expected": None}
        if tenancy is not None:
            _, end = current_term(tenancy, on)
            expected = end + timedelta(days=1 + unit.complex.turnover_days)
            ending = lease_months(unit) > 1 and (end - on).days <= ENDING_SOON_DAYS
        else:
            expected = LeaseSchedule(unit, on).earliest_move_in
            ending = False
        if ending:
            return {"key": "ending", "label": "Tenancy Ending Soon", "expected": expected}
        return {"key": "occupied", "label": "Currently Occupied", "expected": expected}

    # ---------- one request card

    @staticmethod
    def _cover(pictures):
        pictures = list(pictures)
        cover = next((p for p in pictures if p.is_cover), None) or (pictures[0] if pictures else None)
        return (cover.image.url if cover else ""), len(pictures)

    def _decorate(self, application, conversation):
        unit = application.unit
        application.cover_url, application.photo_count = self._cover(unit.pictures.all())
        if not application.cover_url:
            application.cover_url, application.photo_count = self._cover(unit.complex.pictures.all())

        renter_user = application.renter.user
        application.renter_name = renter_user.display_name
        application.renter_initials = renter_user.initials
        application.renter_avatar = renter_user.avatar_url
        application.renter_contact = renter_user.shared_contact       # only what the renter chose to share (Settings)
        landlord_user = unit.complex.landlord.user
        application.landlord_name = landlord_user.display_name
        application.landlord_initials = landlord_user.initials
        application.landlord_avatar = landlord_user.avatar_url
        application.landlord_verified = landlord_user.is_verified
        application.other_occupants = application.occupants[1:]
        application.chat = self._chat(application, conversation)
        application.since = application.decided_at or application.created_at
        application.can_notify = False      # set for vacant units in the waitlist

        if self.user.is_renter and application.status == S.PENDING:
            # "Edit Application" re-opens the form with these values
            lease = LeaseSchedule(unit, self.on)
            application.earliest_move_in = lease.earliest_move_in
            application.lease_known = lease.current_end is not None
            visit_time = application.site_visit_time
            application.prefill_json = json.dumps({
                "occupants": application.occupants[1:],
                "move_in_date": application.move_in_date.isoformat(),
                "site_visit_date": application.site_visit_date.isoformat() if application.site_visit_date else "",
                "site_visit_time": visit_time.strftime("%H:%M") if visit_time else "",
            })
        return application

    def _chat(self, application, conversation):
        """What the Message column and the chat pop-up need."""
        landlord_view = self.landlord_view
        other = application.renter.user if landlord_view else application.unit.complex.landlord.user
        latest = conversation.latest_message if conversation else None
        return {
            "name": other.display_name,
            "initials": other.initials,
            "avatar": other.avatar_url,
            "role": other.role,
            "subject": f"{application.unit.unit_name} · {application.unit.complex.complex_name}",
            "detail_url": reverse("core_inquiries:conversation_detail", args=[conversation.pk]) if conversation else "",
            "send_url": reverse("core_inquiries:send_to_renter" if landlord_view else "core_inquiries:send_inquiry"),
            "send_params": json.dumps({"renter": str(application.renter_id)} if landlord_view else {"unit": str(application.unit_id)}),
            "preview": latest.preview if latest else "",
            "mine": bool(latest and latest.sender_id == self.user.pk),
            "time": time_label(latest.created_at) if latest else "",
            "unread": conversation.unread_count if conversation else 0,
        }
