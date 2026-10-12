# core_rentals/services.py
# Manage Rentals (landlord): tenancies, monthly rent status, assign / end a tenancy.
#
# Rent is due every month on the tenancy's start day (Oct 26 start -> due
# every 26th; a 31st start is due on the last day of shorter months).
#   Overdue  = a due date has passed and it isn't paid
#   Due soon = the next due date is within DUE_SOON_DAYS and isn't paid
#   Paid     = everything due so far is paid
import json
from datetime import date, timedelta

from dateutil.relativedelta import relativedelta
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Prefetch, Q
from django.utils import timezone

from core.core_inquiries.models import Application
from core.core_inquiries.services import LEASE_MONTHS, today
from core.core_listings.models import Complex, Unit

from .models import RentPayment, Tenancy

DUE_SOON_DAYS = 7
ENDING_SOON_DAYS = 30
MAX_NAME_LENGTH = 150


# =========================================================
# DATES & RENT
# =========================================================

def lease_months(unit):
    return LEASE_MONTHS.get(unit.complex.lease_term, 12)


def lease_end(unit, start_date):
    """Last day of the first lease term: start + lease term - 1 day (Oct 1, 2026 -> Sep 30, 2027 for annual)."""
    return start_date + relativedelta(months=lease_months(unit)) - timedelta(days=1)


def _term_end(tenancy, n, months):
    """Last day of lease term number n (0 = the first term)."""
    return tenancy.start_date + relativedelta(months=months * (n + 1)) - timedelta(days=1)


def current_term(tenancy, on):
    """(start, end) shown as the contract period on `on`.

    start = first day of the lease term running on `on`
    end   = the contract end: end_date, which "Renew Lease Contract" pushes
            forward. If nobody renewed or ended it in time, the lease rolls over
            on its own (a monthly lease from Jan 10 is in its Oct 10 – Nov 9 term
            on Oct 20).
    """
    months = lease_months(tenancy.unit)
    if not tenancy.is_active:
        return tenancy.start_date, tenancy.end_date
    n = 0
    while _term_end(tenancy, n, months) < on:
        n += 1
    term_start = tenancy.start_date + relativedelta(months=months * n)
    return term_start, max(tenancy.end_date, _term_end(tenancy, n, months))


def renewal_end(tenancy, on=None):
    """The contract end after one more lease term (what "Renew" would set)."""
    months = lease_months(tenancy.unit)
    _, end = current_term(tenancy, on or today())
    n = 0
    while _term_end(tenancy, n, months) < end:
        n += 1
    return _term_end(tenancy, n + 1, months)


@transaction.atomic
def renew_tenancy(tenancy, on=None):
    """Add one more lease term after the current contract end."""
    if not tenancy.is_active:
        raise ValidationError({"__all__": "This contract has ended. Assign the renter again instead."})
    tenancy.end_date = renewal_end(tenancy, on)
    tenancy.save(update_fields=["end_date"])
    return tenancy


def _billing_stop(tenancy):
    """Active: rent keeps coming due. Ended: nothing after the day it ended."""
    return None if tenancy.is_active else (tenancy.ended_on or tenancy.end_date)


def due_dates(tenancy, until):
    """Every monthly due date from the start up to `until`."""
    stop = _billing_stop(tenancy)
    last = min(until, stop) if stop else until
    dates, n = [], 0
    while True:
        due = tenancy.start_date + relativedelta(months=n)   # relativedelta keeps "the 31st" sane
        if due > last:
            return dates
        dates.append(due)
        n += 1


def next_due_date(tenancy, after):
    """First due date after `after`, or None once the tenancy has ended."""
    stop = _billing_stop(tenancy)
    n = 0
    while True:
        due = tenancy.start_date + relativedelta(months=n)
        if stop and due > stop:
            return None
        if due > after:
            return due
        n += 1


def month_label(day):
    return f"{day:%B %Y}"


def payment_status(tenancy, on=None):
    """{"key": "paid" | "due_soon" | "overdue", "label": ..., "detail": ...}"""
    on = on or today()
    paid = {p.due_date for p in tenancy.payments.all()}

    overdue = [d for d in due_dates(tenancy, on - timedelta(days=1)) if d not in paid]
    if overdue:
        detail = month_label(overdue[0]) if len(overdue) == 1 else f"{len(overdue)} months unpaid"
        return {"key": "overdue", "label": "Overdue", "detail": detail}

    upcoming = [d for d in due_dates(tenancy, on + timedelta(days=DUE_SOON_DAYS)) if d >= on and d not in paid]
    if upcoming:
        when = "today" if upcoming[0] == on else f"{upcoming[0]:%b} {upcoming[0].day}"
        return {"key": "due_soon", "label": "Due Soon", "detail": f"Due {when}"}

    latest = max(paid) if paid else None
    return {"key": "paid", "label": "Paid", "detail": month_label(latest) if latest else "Nothing due yet"}


def payable_months(tenancy, on=None):
    """Months the landlord can mark as paid: everything unpaid so far + the next one."""
    on = on or today()
    paid = {p.due_date for p in tenancy.payments.all()}
    months = [d for d in due_dates(tenancy, on) if d not in paid]
    upcoming = next_due_date(tenancy, on)
    while upcoming and upcoming in paid:            # already paid in advance: offer the one after
        upcoming = next_due_date(tenancy, upcoming)
    if upcoming and upcoming not in months:
        months.append(upcoming)
    return [
        {"value": d.isoformat(), "label": month_label(d), "due": f"Due {d:%b} {d.day}, {d.year}", "overdue": d < on}
        for d in months
    ]


@transaction.atomic
def mark_paid(tenancy, due_date_values, on=None):
    """Record payments for the chosen months. Only months offered by payable_months() are accepted."""
    if not tenancy.is_active:
        raise ValidationError({"__all__": "This tenancy has ended."})
    allowed = {m["value"] for m in payable_months(tenancy, on)}
    chosen = [v for v in (due_date_values or []) if v in allowed]
    if not chosen:
        raise ValidationError({"months": "Pick at least one month to mark as paid."})

    for value in chosen:
        RentPayment.objects.get_or_create(
            tenancy=tenancy, due_date=date.fromisoformat(value),
            defaults={"amount": tenancy.monthly_rent, "paid_on": on or today()},
        )
    return len(chosen)


# =========================================================
# ASSIGN / END
# =========================================================

def candidates(unit):
    """Renters who applied for / joined the waitlist of this unit (pending or waitlisted)."""
    return (
        unit.applications
        .filter(status__in=Application.OPEN_STATUSES)
        .select_related("renter__user")
        .order_by("created_at")
    )


@transaction.atomic
def assign_tenant(unit, start_date, application=None, tenant_name="", occupant_count=1, on=None):
    """Make someone the unit's tenant: a LookApt applicant, or a typed name for people not on the app."""
    on = on or today()
    if unit.availability == Unit.Availability.UNPUBLISHED:
        raise ValidationError({"__all__": "Publish this unit before assigning a renter."})
    if unit.tenancies.filter(status=Tenancy.Status.ACTIVE).exists():
        raise ValidationError({"__all__": f"{unit.unit_name} already has a tenant. End that contract first."})
    if not start_date:
        raise ValidationError({"start_date": "Pick the date the rental starts."})
    if start_date > on + timedelta(days=365):
        raise ValidationError({"start_date": "The start date can't be more than a year away."})
    if start_date < on - timedelta(days=5 * 365):
        raise ValidationError({"start_date": "The start date can't be more than 5 years ago."})

    if application:
        if application.unit_id != unit.pk or not application.is_open:
            raise ValidationError({"application": "That application is no longer open."})
        renter = application.renter
        name = renter.user.display_name
        occupants = list(application.occupants) or [name]
    else:
        name = (tenant_name or "").strip()
        if not name:
            raise ValidationError({"tenant_name": "Pick an applicant or type the tenant's full name."})
        if len(name) > MAX_NAME_LENGTH:
            raise ValidationError({"tenant_name": f"Names can be up to {MAX_NAME_LENGTH} characters."})
        try:
            count = int(occupant_count)
        except (TypeError, ValueError):
            count = 0
        if not 1 <= count <= unit.max_occupant:
            raise ValidationError({"occupant_count": f"{unit.unit_name} allows 1 to {unit.max_occupant} occupants."})
        renter = None
        occupants = [name] + [""] * (count - 1)      # only the primary tenant's name is known

    try:
        tenancy = Tenancy.objects.create(
            unit=unit, renter=renter, application=application, tenant_name=name, occupants=occupants,
            monthly_rent=unit.price, start_date=start_date, end_date=lease_end(unit, start_date),
        )
    except IntegrityError:
        raise ValidationError({"__all__": f"{unit.unit_name} already has a tenant."})

    now = timezone.now()
    if application:
        application.status = Application.Status.ACCEPTED
        application.decided_at = now
        application.save(update_fields=["status", "decided_at", "updated_at"])
    # The vacancy is filled: every other request (pending or waitlisted) moves to the Archive.
    # Recording the tenant already living in an occupied unit keeps its waitlist.
    others = unit.applications.filter(status__in=Application.OPEN_STATUSES)
    if application:
        others = others.exclude(pk=application.pk)
    elif unit.availability == Unit.Availability.OCCUPIED:
        others = others.filter(kind=Application.Kind.APPLY)
    others.update(
        status=Application.Status.CLOSED, reason=Application.Reason.UNIT_RENTED,
        reason_note="", decided_at=now, updated_at=now,
    )

    unit.availability = Unit.Availability.OCCUPIED
    unit.occupied_since = start_date
    unit.save(update_fields=["availability", "occupied_since", "updated_at"])
    return tenancy


@transaction.atomic
def end_tenancy(tenancy, status, on=None):
    """Mark a contract completed or terminated: it moves to the Archive, the unit is vacant again."""
    if status not in (Tenancy.Status.COMPLETED, Tenancy.Status.TERMINATED):
        raise ValidationError({"__all__": "Unknown action."})
    if not tenancy.is_active:
        raise ValidationError({"__all__": "This contract has already ended."})

    tenancy.status = status
    tenancy.ended_on = on or today()
    tenancy.save(update_fields=["status", "ended_on"])

    unit = tenancy.unit
    unit.availability = Unit.Availability.AVAILABLE
    unit.occupied_since = None
    unit.save(update_fields=["availability", "occupied_since", "updated_at"])
    return tenancy


# =========================================================
# PAGE DATA
# =========================================================

def landlord_tenancy(user, pk):
    return Tenancy.objects.select_related("unit__complex", "renter__user").get(
        pk=pk, unit__complex__landlord__user=user,
    )


def _cover_url(pictures):
    pictures = list(pictures)
    cover = next((p for p in pictures if p.is_cover), None) or (pictures[0] if pictures else None)
    return cover.image.url if cover else ""


def _initials(name):
    parts = [p for p in name.split() if p]
    return (parts[0][:1] + (parts[-1][:1] if len(parts) > 1 else "")).upper() or "?"


def _decorate(tenancy, on):
    tenancy.initials = _initials(tenancy.tenant_name)
    tenancy.avatar_url = tenancy.renter.user.avatar_url if tenancy.renter_id else ""     # their profile photo
    tenancy.occupant_count = max(1, len(tenancy.occupants))
    tenancy.is_app_user = tenancy.renter_id is not None
    # The term running now (leases renew until completed/terminated)
    tenancy.term_start, tenancy.term_end = current_term(tenancy, on)
    tenancy.renewed = tenancy.term_end > lease_end(tenancy.unit, tenancy.start_date)
    tenancy.days_left = (tenancy.term_end - on).days
    # "Ending soon" only makes sense for leases longer than a month
    tenancy.ending_soon = (
        tenancy.is_active and lease_months(tenancy.unit) > 1 and 0 <= tenancy.days_left <= ENDING_SOON_DAYS
    )
    if tenancy.is_active:
        tenancy.pay = payment_status(tenancy, on)
        tenancy.payable = payable_months(tenancy, on)
        tenancy.payable_json = json.dumps(tenancy.payable)
        tenancy.renew_to = renewal_end(tenancy, on)
    return tenancy


def get_rentals_context(user):
    on = today()
    active = Prefetch(
        "tenancies",
        queryset=Tenancy.objects.filter(status=Tenancy.Status.ACTIVE)
        .select_related("renter__user").prefetch_related("payments"),
        to_attr="active_tenancies",
    )
    units_qs = (
        Unit.objects.exclude(availability=Unit.Availability.UNPUBLISHED)
        .prefetch_related("pictures", active)
        .order_by("identifier")
    )
    # Only published complexes; an unpublished one (and its units) stays out of Manage Rentals
    complexes = (
        Complex.objects.filter(landlord__user=user, status=Complex.ComplexStatus.ACTIVE)
        .prefetch_related("pictures", Prefetch("units", queryset=units_qs))
        .order_by("complex_name")
    )

    pending = (
        Application.objects.filter(unit__complex__landlord__user=user, status__in=Application.OPEN_STATUSES)
        .select_related("renter__user").order_by("created_at")
    )
    candidates_by_unit = {}
    for application in pending:
        candidates_by_unit.setdefault(application.unit_id, []).append(application)

    groups = []
    for complex_obj in complexes:
        rows = []
        for unit in complex_obj.units.all():
            tenancy = unit.active_tenancies[0] if unit.active_tenancies else None
            if tenancy:
                _decorate(tenancy, on)
            unit.tenancy = tenancy
            unit.cover_url = _cover_url(unit.pictures.all())
            unit.candidates = candidates_by_unit.get(unit.pk, [])
            # For the "Assign a Renter" pop-up (read from a data-* attribute)
            unit.candidates_json = json.dumps([
                {
                    "id": str(a.pk),
                    "name": a.renter.user.display_name,
                    "kind": "On the waitlist" if a.status == Application.Status.WAITLISTED else a.get_kind_display(),
                    "occupants": len(a.occupants) or 1,
                    "move_in": a.move_in_date.isoformat(),
                    "move_in_label": f"{a.move_in_date:%b} {a.move_in_date.day}, {a.move_in_date.year}",
                }
                for a in unit.candidates
            ])
            # "Occupied" without a tenancy record = landlord set it by hand (before this feature)
            unit.state = "occupied" if tenancy or unit.availability == Unit.Availability.OCCUPIED else "vacant"
            unit.ending_soon = bool(tenancy and tenancy.ending_soon)
            rows.append(unit)

        stats = {
            "total": len(rows),
            "occupied": sum(1 for u in rows if u.state == "occupied"),
            "vacant": sum(1 for u in rows if u.state == "vacant"),
            "ending_soon": sum(1 for u in rows if u.ending_soon),
        }
    
        groups.append({"complex": complex_obj, "cover_url": _cover_url(complex_obj.pictures.all()), "units": rows, "stats": stats})

    archive = [
        _decorate(t, on) for t in
        Tenancy.objects.filter(unit__complex__landlord__user=user)
        .exclude(status=Tenancy.Status.ACTIVE)
        .select_related("unit__complex", "renter__user")
        .prefetch_related("unit__pictures")
        .order_by("-ended_on", "-start_date")
    ]
    for tenancy in archive:
        tenancy.unit.cover_url = _cover_url(tenancy.unit.pictures.all())
  

    return {
        "rental_groups": groups,
        "rental_archive": archive,
        "rental_counts": {"archive": len(archive)},
        "bulletin_complexes": [g for g in groups],
        "today_iso": on.isoformat(),
    }

def get_renter_rentals_context(user):
    """Rental History (renter): current rentals (incl. approved ones that start later) + past ones."""
    on = today()
    tenancies = (
        Tenancy.objects.filter(renter__user=user)
        .select_related("unit__complex__landlord__user")
        .prefetch_related("payments", "unit__pictures", "unit__complex__pictures")
    )
    current, past = [], []
    for tenancy in tenancies:
        _decorate(tenancy, on)
        unit = tenancy.unit
        tenancy.cover_url = _cover_url(unit.pictures.all()) or _cover_url(unit.complex.pictures.all())
        landlord = unit.complex.landlord.user
        tenancy.landlord_name = landlord.display_name
        tenancy.landlord_initials = landlord.initials
        tenancy.landlord_avatar = landlord.avatar_url
        tenancy.landlord_contact = landlord.shared_contact      # only what they chose to show (Settings)
        tenancy.upcoming = tenancy.start_date > on
        tenancy.days_to_start = (tenancy.start_date - on).days
        (current if tenancy.is_active else past).append(tenancy)
    past.sort(key=lambda t: t.ended_on or t.end_date, reverse=True)
    return {"current_rentals": current, "past_rentals": past}