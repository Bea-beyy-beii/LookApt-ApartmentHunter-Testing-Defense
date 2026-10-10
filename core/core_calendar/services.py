# core_calendar/services.py
# What appears on a calendar, and "Post on Bulletin".
#
# Landlord: their bulletin events, rent due dates (grouped per complex),
#           contract end dates, and site visits renters asked for.
# Renter:   their own rent due dates, contract end and confirmed site visits,
#           plus bulletin events for the complexes they currently rent in
#           (only from their move-in date on).
# Site visits show up only once the landlord confirms them; until then they
# live in Inquiries → Pending Requests.
# Only bulletin events are stored (CalendarEvent); the rest is read live.
from collections import defaultdict
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q

from core.core_inquiries.models import Application
from core.core_inquiries.services import start_landlord_message, today
from core.core_listings.models import Complex
from core.core_rentals.models import Tenancy
from core.core_rentals.services import current_term, due_dates

from .models import CalendarEvent

MAX_RANGE_DAYS = 62        # one month view (6 weeks) at most per request
MAX_MESSAGE = 500
MAX_TITLE = 100

# Category = filter checkbox + colour on the calendar
CATEGORY_FOR_TYPE = {
    CalendarEvent.Type.ANNOUNCEMENT: "announcement",
    CalendarEvent.Type.MEETING: "announcement",
    CalendarEvent.Type.OTHER: "announcement",
    CalendarEvent.Type.MAINTENANCE: "maintenance",
}


def _time(value):
    hour = value.hour % 12 or 12
    return f"{hour}:{value:%M %p}"


def _date_label(day):
    return f"{day:%b} {day.day}, {day.year}"


def _item(day, category, title, detail="", end_day=None, time_label="", all_day=True):
    return {
        "date": day.isoformat(),
        "end_date": (end_day or day).isoformat(),
        "category": category,
        "title": title,
        "detail": detail,
        "time_label": time_label or ("All-day" if all_day else ""),
        "all_day": all_day,
    }


# =========================================================
# ITEMS FOR A DATE RANGE
# =========================================================

def _event_items(events, visible_complexes=None):
    """visible_complexes: for renters, only name the complexes they rent in
    (an event posted to several complexes shouldn't reveal the others)."""
    items = []
    for event in events:
        if event.all_day:
            time_label = "All week" if event.end_date > event.start_date else "All-day"
        else:
            time_label = _time(event.start_time) + (f" – {_time(event.end_time)}" if event.end_time else "")
        names = ", ".join(
            c.complex_name for c in event.complexes.all()
            if visible_complexes is None or c.pk in visible_complexes
        )
        items.append(_item(
            event.start_date, CATEGORY_FOR_TYPE.get(event.event_type, "announcement"),
            event.title, detail=names, end_day=event.end_date, time_label=time_label, all_day=event.all_day,
        ) | {"message": event.message, "type_label": event.get_event_type_display()})
    return items


def _tenancy_items(tenancies, start, end, group_rent):
    """Rent due dates + contract end dates."""
    items = []
    rent_by_day = defaultdict(list)          # (date, complex name) -> [unit names]

    for tenancy in tenancies:
        unit = tenancy.unit
        for due in due_dates(tenancy, end):
            if due >= start:
                rent_by_day[(due, unit.complex.complex_name)].append(unit.unit_name)

        _, contract_end = current_term(tenancy, today())
        if start <= contract_end <= end:
            who = f" · {tenancy.tenant_name}" if group_rent else ""
            items.append(_item(contract_end, "contract", f"Contract ends – {unit.unit_name}",
                               detail=f"{unit.complex.complex_name}{who}"))

    for (day, complex_name), units in sorted(rent_by_day.items()):
        if group_rent and len(units) > 1:
            title = f"Rental due ({len(units)} units)"
        else:
            title = f"Rent due – {units[0]}" if not group_rent else f"Rental due – {units[0]}"
        items.append(_item(day, "rent", title, detail=complex_name))
    return items


def _site_visit_items(applications, landlord_view):
    items = []
    for application in applications:
        unit = application.unit
        detail = application.renter.user.display_name if landlord_view else unit.complex.complex_name
        visit_time = application.site_visit_time
        items.append(_item(application.site_visit_date, "site_visit",
                           f"{unit.unit_name} – Site Visit", detail=detail,
                           time_label=_time(visit_time) if visit_time else "", all_day=visit_time is None))
    return items


def calendar_items(user, start, end):
    """Everything on this user's calendar between start and end (inclusive), sorted."""
    if (end - start).days > MAX_RANGE_DAYS:
        end = start + timedelta(days=MAX_RANGE_DAYS)

    overlapping = Q(start_date__lte=end, end_date__gte=start)
    # Only visits the landlord confirmed (pending ones stay in Pending Requests)
    visits = (
        Application.objects
        .filter(site_visit_date__range=(start, end), site_visit_status=Application.SiteVisit.CONFIRMED)
        .exclude(status__in=Application.ARCHIVED_STATUSES)
        .select_related("unit__complex", "renter__user")
    )
    active = Tenancy.objects.filter(status=Tenancy.Status.ACTIVE).select_related("unit__complex").prefetch_related("payments")

    if user.role == "landlord":
        events = CalendarEvent.objects.filter(overlapping, landlord__user=user).prefetch_related("complexes")
        items = (
            _event_items(events)
            + _tenancy_items(active.filter(unit__complex__landlord__user=user), start, end, group_rent=True)
            + _site_visit_items(visits.filter(unit__complex__landlord__user=user), landlord_view=True)
        )
    else:
        mine = list(active.filter(renter__user=user))
        # Bulletins only for complexes they're an approved tenant of, from their move-in date on
        moved_in = {}
        for tenancy in mine:
            complex_id = tenancy.unit.complex_id
            moved_in[complex_id] = min(tenancy.start_date, moved_in.get(complex_id, tenancy.start_date))
        if moved_in:
            renting = Q()
            for complex_id, since in moved_in.items():
                renting |= Q(complexes=complex_id, end_date__gte=since)
            events = CalendarEvent.objects.filter(overlapping).filter(renting).distinct().prefetch_related("complexes")
        else:
            events = CalendarEvent.objects.none()
        items = (
            _event_items(events, visible_complexes=set(moved_in))
            + _tenancy_items(mine, start, end, group_rent=False)
            + _site_visit_items(visits.filter(renter__user=user), landlord_view=False)
        )

    order = {"announcement": 0, "maintenance": 1, "site_visit": 2, "rent": 3, "contract": 4}
    items.sort(key=lambda i: (i["date"], i["all_day"], i["time_label"], order.get(i["category"], 9)))
    return items


# =========================================================
# POST ON BULLETIN
# =========================================================

def _week_of(day):
    """Sunday–Saturday week containing `day` (the calendar's rows start on Sunday)."""
    sunday = day - timedelta(days=(day.weekday() + 1) % 7)
    return sunday, sunday + timedelta(days=6)


def _event_when(event):
    if event.end_date > event.start_date:
        return f"{_date_label(event.start_date)} – {_date_label(event.end_date)} (whole week)"
    when = _date_label(event.start_date)
    if event.start_time:
        when += f", {_time(event.start_time)}" + (f" – {_time(event.end_time)}" if event.end_time else "")
    return when


@transaction.atomic
def post_bulletin(user, *, message, complex_ids=None, event_date=None, start_time=None, end_time=None,
                  event_title="", event_type=CalendarEvent.Type.ANNOUNCEMENT, whole_week=False):
    """Send an announcement to the tenants of the chosen complexes (Messages) and,
    when it has a date, put it on the calendars.

    complex_ids=None means all of the landlord's complexes.
    Returns (event or None, number of tenants messaged).
    """
    message = (message or "").strip()
    if not message:
        raise ValidationError({"message": "Write your announcement first."})
    if len(message) > MAX_MESSAGE:
        raise ValidationError({"message": f"Keep it under {MAX_MESSAGE} characters."})
    event_title = (event_title or "").strip()[:MAX_TITLE]
    if event_type not in CalendarEvent.Type.values:
        raise ValidationError({"event_type": "Pick an event type."})

    complexes = Complex.objects.filter(landlord__user=user)
    if complex_ids is not None:
        complexes = complexes.filter(pk__in=complex_ids)
    complexes = list(complexes)
    if not complexes:
        raise ValidationError({"complexes": "Pick at least one of your complexes."})

    event = None
    if event_date or start_time or end_time:
        if not event_date:
            raise ValidationError({"__all__": "Pick a date for the event."})
        if event_date < today():
            raise ValidationError({"event_date": "The event can't be in the past."})
        if whole_week:
            start_date, end_date = _week_of(event_date)
            start_time = end_time = None
        else:
            start_date = end_date = event_date
            if end_time and not start_time:
                raise ValidationError({"__all__": "Add a start time, or leave both times empty for an all-day event."})
            if start_time and end_time and end_time <= start_time:
                raise ValidationError({"__all__": "The end time must be after the start time."})

        event = CalendarEvent.objects.create(
            landlord=user.landlord,
            title=event_title or CalendarEvent.Type(event_type).label,
            message=message, event_type=event_type,
            start_date=start_date, end_date=end_date, start_time=start_time, end_time=end_time,
        )
        event.complexes.set(complexes)

    # Message every current tenant on LookApt in those complexes (once each)
    tenants = Tenancy.objects.filter(
        status=Tenancy.Status.ACTIVE, unit__complex__in=complexes, renter__isnull=False,
    ).select_related("renter")
    body = f"📢 Bulletin from your landlord\n\n{message}"
    if event:
        body += f"\n\n📅 {event.title} · {_event_when(event)}"

    sent = set()
    for tenancy in tenants:
        if tenancy.renter_id in sent:
            continue
        start_landlord_message(user, tenancy.renter, body)
        sent.add(tenancy.renter_id)

    if not event and not sent:
        raise ValidationError({"__all__": "None of your current tenants in those complexes are on LookApt yet, so there's no one to send this to. Add a date to post it on your calendar instead."})
    return event, len(sent)