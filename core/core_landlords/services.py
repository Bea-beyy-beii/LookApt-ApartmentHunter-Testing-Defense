# core_landlords/services.py
# Data for the landlord's Home tab:
#   - Month: one calendar month (the < > arrows and dropdowns)
#   - ReceivablesReport: Monthly Receivables card + drawer (any month)
#   - PerformanceChart: Listing Performance (views, saves, inquiries, successful rentals)
#   - AttentionCheck and its subclasses: the Needs Your Attention rows
# Built from what Manage Rentals and Inquiries already compute, so the
# numbers always match those tabs.
import calendar
import json
from abc import ABC, abstractmethod
from collections import defaultdict
from datetime import date, timedelta
from functools import cached_property

from django.db.models import Count
from django.db.models.functions import TruncDate
from django.urls import reverse

from core.core_inquiries.models import Application, Conversation
from core.core_inquiries.services import today
from core.core_listings.models import ListingView, SavedListing
from core.core_rentals.models import Tenancy


# =========================================================
# MONTHS
# =========================================================

class Month:
    """One calendar month (a small value object): Month(date(2026, 10, 9)).label -> "October 2026"."""

    def __init__(self, day):
        self.first = day.replace(day=1)

    @classmethod
    def parse(cls, value, default):
        """"2026-10" -> October 2026; anything else -> the month of `default`."""
        try:
            year, month = (int(part) for part in (value or "").split("-"))
            return cls(date(year, month, 1))
        except (TypeError, ValueError):
            return cls(default)

    @property
    def last(self):
        return self.first.replace(day=calendar.monthrange(self.first.year, self.first.month)[1])

    @property
    def label(self):
        return f"{self.first:%B} {self.first.year}"

    @property
    def value(self):
        return f"{self.first:%Y-%m}"

    def shift(self, n):
        """The month n months later (negative: earlier)."""
        month = self.first.month - 1 + n
        return Month(date(self.first.year + month // 12, month % 12 + 1, 1))

    def recent(self, count):
        """This month and the count - 1 before it, newest first (for a dropdown)."""
        return [self.shift(-i) for i in range(count)]


# =========================================================
# MONTHLY RECEIVABLES
# =========================================================

class ReceivablesReport:
    """Every rent due in `month` for this landlord's tenancies, with its status.

    Expected  = the monthly rent of every unit with a due date this month
    Collected = what was marked as paid for those due dates
    Ended (completed / terminated) contracts only count what was actually
    paid: their unpaid months aren't owed anymore, so they never show as
    overdue (same rule as the card and Manage Rentals).
    """

    def __init__(self, user, month, on=None):
        self.user = user
        self.month = Month(month)
        self.on = on or today()

    def _status(self, due, payment):
        if payment:
            return "paid"
        if due < self.on:
            return "overdue"
        if due <= self.on + timedelta(days=Tenancy.DUE_SOON_DAYS):
            return "due_soon"
        return "not_due"

    def _tenancy_rows(self, tenancy):
        payments = {p.due_date: p for p in tenancy.payments.all()}
        payable = None
        rows = []
        for due in tenancy.due_dates(self.month.last):
            if due < self.month.first:
                continue
            payment = payments.get(due)
            if not payment and not tenancy.is_active:
                continue
            status = self._status(due, payment)
            if status != "paid" and payable is None:
                payable = json.dumps(tenancy.payable_months(self.on))
            rows.append({
                "tenancy": tenancy,
                "unit": tenancy.unit,
                "due": due,
                "amount": payment.amount if payment else tenancy.monthly_rent,
                "status": status,
                "payable_json": payable if status != "paid" else "",
                "pay_url": reverse("core_rentals:mark_paid", args=[tenancy.pk]),
            })
        return rows

    @cached_property
    def rows(self):
        tenancies = (
            Tenancy.objects.of_landlord(self.user).filter(start_date__lte=self.month.last)
            .select_related("unit__complex", "renter__user")
            .prefetch_related("payments")
        )
        rows = [row for tenancy in tenancies for row in self._tenancy_rows(tenancy)]
        rows.sort(key=lambda r: (r["due"], r["unit"].complex.complex_name, r["unit"].identifier))
        return rows

    def _rows_with(self, *statuses):
        return [r for r in self.rows if r["status"] in statuses]

    def _total(self, status=None):
        chosen = self.rows if status is None else self._rows_with(status)
        return {"count": len(chosen), "amount": sum((r["amount"] for r in chosen), 0)}

    def _breakdown(self):
        """Expected income grouped by monthly rate."""
        by_rate = defaultdict(int)
        for row in self.rows:
            by_rate[row["tenancy"].monthly_rent] += 1
        return [
            {"rate": rate, "units": count, "amount": rate * count}
            for rate, count in sorted(by_rate.items(), key=lambda item: item[0], reverse=True)
        ]

    def as_dict(self):
        expected = self._total()
        paid = self._total("paid")
        month = self.month
        return {
            "month": month.first,
            "month_label": month.label,
            "month_value": month.value,
            "prev_value": month.shift(-1).value,
            "next_value": month.shift(1).value,
            "expected": expected,
            "paid": paid,
            "overdue": self._total("overdue"),
            "due_soon": self._total("due_soon"),
            "not_due": self._total("not_due"),
            "percent": round(paid["amount"] * 100 / expected["amount"]) if expected["amount"] else 0,
            "breakdown": self._breakdown(),
            "upcoming": self._rows_with("due_soon", "not_due"),
            "overdue_rows": self._rows_with("overdue"),
            "paid_rows": self._rows_with("paid"),
        }


# =========================================================
# LISTING PERFORMANCE
# =========================================================

class PerformanceChart:
    """Daily counts for the chart + month totals with the change vs the
    previous month (same number of days, so a half-finished month is fair)."""

    MONTHS = 6       # months in the chart's dropdown
    SERIES = (("views", "Views"), ("saves", "Saves"), ("inquiries", "Inquiries"), ("rentals", "Successful Rentals"))

    def __init__(self, user, month, on=None):
        self.user = user
        self.month = Month(month)
        self.on = on or today()

    @property
    def _last(self):
        """Last day counted: today for the current month."""
        return min(self.month.last, self.on) if self.month.first <= self.on else self.month.last

    @property
    def days(self):
        """Every day of the month shown so far (none for a future month)."""
        first = self.month.first
        if first > self.on:
            return []
        return [first + timedelta(days=i) for i in range((self._last - first).days + 1)]

    @staticmethod
    def _per_day(queryset, field):
        return dict(
            queryset.annotate(day=TruncDate(field)).values("day").annotate(n=Count("pk")).values_list("day", "n")
        )

    @staticmethod
    def _change(now, before):
        if not before:
            return None if not now else 100
        return round((now - before) * 100 / before)

    def _counts(self, first, last):
        """{series: {date: count}} for this landlord between two dates (inclusive)."""
        user = self.user
        views = ListingView.objects.filter(complex__landlord__user=user, viewed_on__range=(first, last))
        saves = SavedListing.objects.filter(complex__landlord__user=user, saved_at__date__range=(first, last))
        applications = Application.objects.filter(unit__complex__landlord__user=user, created_at__date__range=(first, last))
        threads = Conversation.objects.filter(landlord__user=user, created_at__date__range=(first, last))
        # Successful rentals = tenancies that came from a LookApt application
        rentals = Tenancy.objects.of_landlord(user).filter(
            application__isnull=False, created_at__date__range=(first, last),
        )

        inquiries = defaultdict(int)
        for source in (self._per_day(applications, "created_at"), self._per_day(threads, "created_at")):
            for day, n in source.items():
                inquiries[day] += n
        return {
            "views": dict(views.values("viewed_on").annotate(n=Count("pk")).values_list("viewed_on", "n")),
            "saves": self._per_day(saves, "saved_at"),
            "inquiries": dict(inquiries),
            "rentals": self._per_day(rentals, "created_at"),
        }

    def as_dict(self):
        days = self.days
        counts = self._counts(self.month.first, self._last)
        prev_first = self.month.shift(-1).first
        prev_last = min(Month(prev_first).last, prev_first + timedelta(days=max(len(days) - 1, 0)))
        prev = self._counts(prev_first, prev_last)

        series = []
        for key, label in self.SERIES:
            values = [counts[key].get(day, 0) for day in days]
            total = sum(values)
            series.append({
                "key": key, "label": label, "values": values, "total": total,
                "change": self._change(total, sum(prev[key].values())),
            })

        return {
            "month": self.month.value,
            "month_label": self.month.label,
            "days": [f"{day:%b} {day.day}" for day in days],
            "series": series,
            "months": [{"value": m.value, "label": m.label} for m in Month(self.on).recent(self.MONTHS)],
        }


# =========================================================
# NEEDS YOUR ATTENTION
# =========================================================

class AttentionCheck(ABC):
    """One row of Needs Your Attention, shown only when there's something to do.

    Polymorphism: every subclass answers item() its own way; the Home tab
    (HomeSection.ATTENTION_CHECKS) just keeps the ones that aren't None.
    `context` = the dashboard context so far (Manage Rentals + Inquiries).
    """

    def __init__(self, context, on):
        self.context = context
        self.on = on

    @property
    def units(self):
        return [u for g in self.context["rental_groups"] for u in g["units"]]

    @property
    def pending(self):
        return self.context["pending_requests"]

    @staticmethod
    def _peso(amount):
        return f"₱{amount:,.0f}"

    @staticmethod
    def _plural(n, word):
        return f"{n} {word}{'s' if n != 1 else ''}"

    @abstractmethod
    def item(self):
        """The row's dict, or None when nothing needs doing."""


class OverdueRent(AttentionCheck):

    def item(self):
        overdue = [u for u in self.units if u.tenancy and u.tenancy.pay["key"] == "overdue"]
        if not overdue:
            return None
        amount = 0
        for u in overdue:
            amount += len(u.tenancy.unpaid_dates(self.on - timedelta(days=1))) * u.tenancy.monthly_rent
        return {
            "tone": "danger", "icon": "info", "count": len(overdue), "title": "Overdue rent",
            "detail": f"{self._plural(len(overdue), 'unit')} overdue · {self._peso(amount)}",
            "tab": "rentals", "filter": "pay:overdue",
        }


class PendingRequests(AttentionCheck):

    def item(self):
        pending = self.pending
        if not pending:
            return None
        return {
            "tone": "warning", "icon": "document", "count": len(pending), "title": "Pending requests",
            "detail": f"{self._plural(len(pending), 'request')} waiting for review",
            "tab": "inquiries", "subtab": "requests",
        }


class SiteVisitsToConfirm(AttentionCheck):

    def item(self):
        visits = [a for a in self.pending if a.site_visit_status == Application.SiteVisit.PENDING]
        if not visits:
            return None
        return {
            "tone": "warning", "icon": "calendar_check", "count": len(visits), "title": "Site visits to confirm",
            "detail": f"{self._plural(len(visits), 'visit')} awaiting confirmation",
            "tab": "inquiries", "subtab": "requests",
        }


class ContractsEndingSoon(AttentionCheck):

    def item(self):
        ending = sorted((u for u in self.units if u.ending_soon), key=lambda u: u.tenancy.term_end)
        if not ending:
            return None
        first = ending[0]
        end = first.tenancy.term_end
        return {
            "tone": "caution", "icon": "lease", "count": len(ending), "title": "Contracts ending in 30 days",
            "detail": f"{first.unit_name} ({first.complex.complex_name}) ends {end:%b} {end.day}",
            "tab": "rentals", "filter": "ending:1",
        }


class VacantWithWaitlist(AttentionCheck):

    def item(self):
        vacant = [g for g in self.context["waitlist_groups"] if g["outlook"]["key"] == "vacant"]
        if not vacant:
            return None
        group = vacant[0]
        waiting = len(group["applications"])
        return {
            "tone": "good", "icon": "occupants", "count": len(vacant), "title": "Vacant units with a waitlist",
            "detail": f"{group['unit'].unit_name} is vacant · {waiting} on the waitlist (notify)",
            "tab": "inquiries", "subtab": "waitlist",
        }
