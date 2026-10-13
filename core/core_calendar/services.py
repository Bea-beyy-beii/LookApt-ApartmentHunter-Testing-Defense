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
from abc import ABC, abstractmethod
from collections import defaultdict
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils.functional import cached_property

from core.core_inquiries.labels import clock_label
from core.core_inquiries.models import Application, Message
from core.core_inquiries.services import LandlordMessage, today
from core.core_listings.models import Complex
from core.core_rentals.models import Tenancy

from .models import CalendarEvent


# =========================================================
# ITEMS FOR A DATE RANGE
# =========================================================

class Calendar(ABC):
    """Everything on one user's calendar between start and end (inclusive).

    Polymorphism: LandlordCalendar and RenterCalendar each pick their own
    events, tenancies and site visits, and word some items differently;
    items() puts them together and sorts them the same way for both.
    """

    MAX_RANGE_DAYS = 62        # one month view (6 weeks) at most per request
    ORDER = {"announcement": 0, "maintenance": 1, "site_visit": 2, "rent": 3, "contract": 4}

    def __init__(self, user, start, end):
        if (end - start).days > self.MAX_RANGE_DAYS:
            end = start + timedelta(days=self.MAX_RANGE_DAYS)
        self.user = user
        self.start = start
        self.end = end

    @classmethod
    def for_user(cls, user, start, end):
        calendar_class = LandlordCalendar if user.is_landlord else RenterCalendar
        return calendar_class(user, start, end)

    def items(self):
        """Every item, sorted by day, then all-day first, then time."""
        items = (
            self._event_items(self._events())
            + self._tenancy_items(self._tenancies())
            + self._site_visit_items(self._visits())
        )
        items.sort(key=lambda i: (i["date"], i["all_day"], i["time_label"], self.ORDER.get(i["category"], 9)))
        return items

    # ---------- what each kind of user sees

    @abstractmethod
    def _events(self):
        """CalendarEvents (bulletins) to show."""

    @abstractmethod
    def _tenancies(self):
        """Active tenancies whose rent / contract end to show."""

    @abstractmethod
    def _visits(self):
        """Confirmed site visits to show."""

    @abstractmethod
    def _rent_title(self, unit_names):
        """Title of a rent due item for these units (same day, same complex)."""

    @abstractmethod
    def _contract_detail(self, tenancy):
        """Second line of a contract end item."""

    @abstractmethod
    def _visit_detail(self, application):
        """Second line of a site visit item."""

    def _visible_complexes(self):
        """Complexes an event may name (None = all of them)."""
        return None

    # ---------- shared

    @property
    def _overlapping(self):
        return Q(start_date__lte=self.end, end_date__gte=self.start)

    def _active_tenancies(self):
        return Tenancy.objects.filter(status=Tenancy.Status.ACTIVE).select_related("unit__complex").prefetch_related("payments")

    @staticmethod
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

    def _event_items(self, events):
        visible = self._visible_complexes()
        items = []
        for event in events:
            names = ", ".join(
                c.complex_name for c in event.complexes.all() if visible is None or c.pk in visible
            )
            items.append(self._item(
                event.start_date, event.category, event.title, detail=names, end_day=event.end_date,
                time_label=event.time_label, all_day=event.all_day,
            ) | {"message": event.message, "type_label": event.get_event_type_display()})
        return items

    def _tenancy_items(self, tenancies):
        """Rent due dates + contract end dates."""
        items = []
        rent_by_day = defaultdict(list)          # (date, complex name) -> [unit names]

        for tenancy in tenancies:
            unit = tenancy.unit
            for due in tenancy.due_dates(self.end):
                if due >= self.start:
                    rent_by_day[(due, unit.complex.complex_name)].append(unit.unit_name)

            _, contract_end = tenancy.current_term(today())
            if self.start <= contract_end <= self.end:
                items.append(self._item(contract_end, "contract", f"Contract ends – {unit.unit_name}",
                                        detail=self._contract_detail(tenancy)))

        for (day, complex_name), units in sorted(rent_by_day.items()):
            items.append(self._item(day, "rent", self._rent_title(units), detail=complex_name))
        return items

    def _site_visit_items(self, applications):
        items = []
        for application in applications:
            visit_time = application.site_visit_time
            items.append(self._item(application.site_visit_date, "site_visit",
                                    f"{application.unit.unit_name} – Site Visit", detail=self._visit_detail(application),
                                    time_label=clock_label(visit_time) if visit_time else "", all_day=visit_time is None))
        return items


class LandlordCalendar(Calendar):
    """Rent is grouped per complex ("Rental due (3 units)") and items name the tenant."""

    def _events(self):
        return CalendarEvent.objects.filter(self._overlapping, landlord__user=self.user).prefetch_related("complexes")

    def _tenancies(self):
        return self._active_tenancies().filter(unit__complex__landlord__user=self.user)

    def _visits(self):
        return Application.objects.confirmed_visits(self.start, self.end).filter(unit__complex__landlord__user=self.user)

    def _rent_title(self, unit_names):
        if len(unit_names) > 1:
            return f"Rental due ({len(unit_names)} units)"
        return f"Rental due – {unit_names[0]}"

    def _contract_detail(self, tenancy):
        return f"{tenancy.unit.complex.complex_name} · {tenancy.tenant_name}"

    def _visit_detail(self, application):
        return application.renter.user.display_name


class RenterCalendar(Calendar):
    """Bulletins only for complexes they're an approved tenant of, from their move-in date on."""

    @cached_property
    def _my_tenancies(self):
        return list(self._active_tenancies().filter(renter__user=self.user))

    @cached_property
    def _moved_in(self):
        """complex id -> the day they first moved in there."""
        moved_in = {}
        for tenancy in self._my_tenancies:
            complex_id = tenancy.unit.complex_id
            moved_in[complex_id] = min(tenancy.start_date, moved_in.get(complex_id, tenancy.start_date))
        return moved_in

    def _events(self):
        if not self._moved_in:
            return CalendarEvent.objects.none()
        renting = Q()
        for complex_id, since in self._moved_in.items():
            renting |= Q(complexes=complex_id, end_date__gte=since)
        return CalendarEvent.objects.filter(self._overlapping).filter(renting).distinct().prefetch_related("complexes")

    def _visible_complexes(self):
        # An event posted to several complexes shouldn't reveal the others
        return set(self._moved_in)

    def _tenancies(self):
        return self._my_tenancies

    def _visits(self):
        return Application.objects.confirmed_visits(self.start, self.end).filter(renter__user=self.user)

    def _rent_title(self, unit_names):
        return f"Rent due – {unit_names[0]}"

    def _contract_detail(self, tenancy):
        return tenancy.unit.complex.complex_name

    def _visit_detail(self, application):
        return application.unit.complex.complex_name


# =========================================================
# POST ON BULLETIN
# =========================================================

class Bulletin:
    """A landlord's "Post on Bulletin": an announcement sent to the tenants of the
    chosen complexes (Messages) and, when it has a date, put on the calendars.

    complex_ids=None means all of the landlord's complexes.
    """

    MAX_MESSAGE = 500
    MAX_TITLE = 100

    def __init__(self, user, *, message, complex_ids=None, event_date=None, start_time=None, end_time=None,
                 event_title="", event_type=CalendarEvent.Type.ANNOUNCEMENT, whole_week=False):
        self.user = user
        self.message = (message or "").strip()
        self.complex_ids = complex_ids
        self.event_date = event_date
        self.start_time = start_time
        self.end_time = end_time
        self.event_title = (event_title or "").strip()[:self.MAX_TITLE]
        self.event_type = event_type
        self.whole_week = whole_week
        self.event = None
        self.sent_count = 0

    @transaction.atomic
    def post(self):
        """Returns (event or None, number of tenants messaged)."""
        if not self.message:
            raise ValidationError({"message": "Write your announcement first."})
        if len(self.message) > self.MAX_MESSAGE:
            raise ValidationError({"message": f"Keep it under {self.MAX_MESSAGE} characters."})
        if self.event_type not in CalendarEvent.Type.values:
            raise ValidationError({"event_type": "Pick an event type."})

        complexes = self._complexes()
        if self.event_date or self.start_time or self.end_time:
            self.event = self._create_event(complexes)
        self.sent_count = self._send(complexes)

        if not self.event and not self.sent_count:
            raise ValidationError({"__all__": "None of your current tenants in those complexes are on LookApt yet, so there's no one to send this to. Add a date to post it on your calendar instead."})
        return self.event, self.sent_count

    @property
    def summary(self):
        """"Bulletin sent to 3 tenants and added to the calendar."."""
        parts = []
        if self.sent_count:
            parts.append(f"sent to {self.sent_count} tenant{'s' if self.sent_count != 1 else ''}")
        if self.event:
            parts.append("added to the calendar")
        return "Bulletin " + " and ".join(parts) + "."

    def _complexes(self):
        complexes = Complex.objects.filter(landlord__user=self.user)
        if self.complex_ids is not None:
            complexes = complexes.filter(pk__in=self.complex_ids)
        complexes = list(complexes)
        if not complexes:
            raise ValidationError({"complexes": "Pick at least one of your complexes."})
        return complexes

    @staticmethod
    def _week_of(day):
        """Sunday–Saturday week containing `day` (the calendar's rows start on Sunday)."""
        sunday = day - timedelta(days=(day.weekday() + 1) % 7)
        return sunday, sunday + timedelta(days=6)

    def _create_event(self, complexes):
        start_time, end_time = self.start_time, self.end_time
        if not self.event_date:
            raise ValidationError({"__all__": "Pick a date for the event."})
        if self.event_date < today():
            raise ValidationError({"event_date": "The event can't be in the past."})
        if self.whole_week:
            start_date, end_date = self._week_of(self.event_date)
            start_time = end_time = None
        else:
            start_date = end_date = self.event_date
            if end_time and not start_time:
                raise ValidationError({"__all__": "Add a start time, or leave both times empty for an all-day event."})
            if start_time and end_time and end_time <= start_time:
                raise ValidationError({"__all__": "The end time must be after the start time."})

        event = CalendarEvent.objects.create(
            landlord=self.user.landlord,
            title=self.event_title or CalendarEvent.Type(self.event_type).label,
            message=self.message, event_type=self.event_type,
            start_date=start_date, end_date=end_date, start_time=start_time, end_time=end_time,
        )
        event.complexes.set(complexes)
        return event

    def _send(self, complexes):
        """Message every current tenant on LookApt in those complexes (once each)."""
        tenants = Tenancy.objects.filter(
            status=Tenancy.Status.ACTIVE, unit__complex__in=complexes, renter__isnull=False,
        ).select_related("renter")
        # Shown in their chat as a yellow "Bulletin Announcement" banner (chat.js)
        event_label = f"{self.event.title} · {self.event.when_label}" if self.event else ""

        sent = set()
        for tenancy in tenants:
            if tenancy.renter_id in sent:
                continue
            LandlordMessage(self.user, tenancy.renter, message_kind=Message.Kind.BULLETIN,
                            bulletin_event=event_label).send(self.message)
            sent.add(tenancy.renter_id)
        return len(sent)
