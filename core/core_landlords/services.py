# core_landlords/services.py
# Data for the landlord's Home tab:
#   - the 4 cards (listings, occupancy, inquiries, monthly receivables)
#   - Monthly Receivables drawer (any month)
#   - Listing Performance chart (views, saves, inquiries, successful rentals)
#   - Needs Your Attention + Managed Properties
# Built from what Manage Rentals and Inquiries already compute, so the
# numbers always match those tabs.
import calendar
import json
from collections import defaultdict
from datetime import date, timedelta

from django.db.models import Count
from django.db.models.functions import TruncDate
from django.urls import reverse

from core.core_inquiries.models import Application, Conversation
from core.core_inquiries.services import today
from core.core_listings.models import ListingView, SavedListing
from core.core_rentals.models import Tenancy
from core.core_rentals.services import DUE_SOON_DAYS, due_dates, payable_months

PERFORMANCE_MONTHS = 6       # months in the chart's dropdown


# =========================================================
# MONTHS
# =========================================================

def month_start(day):
    return day.replace(day=1)


def month_end(day):
    return day.replace(day=calendar.monthrange(day.year, day.month)[1])


def add_months(day, n):
    month = day.month - 1 + n
    return date(day.year + month // 12, month % 12 + 1, 1)


def parse_month(value, default):
    """"2026-10" -> date(2026, 10, 1); anything else -> default."""
    try:
        year, month = (int(part) for part in (value or "").split("-"))
        return date(year, month, 1)
    except (TypeError, ValueError):
        return default


def month_label(day):
    return f"{day:%B} {day.year}"


def peso(amount):
    return f"₱{amount:,.0f}"


# =========================================================
# MONTHLY RECEIVABLES
# =========================================================

def receivables(user, month, on=None):
    """Every rent due in `month` for this landlord's tenancies, with its status.

    Expected  = the monthly rent of every unit with a due date this month
    Collected = what was marked as paid for those due dates
    Ended (completed / terminated) contracts only count what was actually
    paid: their unpaid months aren't owed anymore, so they never show as
    overdue (same rule as the card and Manage Rentals).
    """
    on = on or today()
    first, last = month_start(month), month_end(month)
    tenancies = (
        Tenancy.objects.filter(unit__complex__landlord__user=user, start_date__lte=last)
        .select_related("unit__complex", "renter__user")
        .prefetch_related("payments")
    )

    rows = []
    for tenancy in tenancies:
        payments = {p.due_date: p for p in tenancy.payments.all()}
        payable = None
        for due in due_dates(tenancy, last):
            if due < first:
                continue
            payment = payments.get(due)
            if not payment and not tenancy.is_active:
                continue
            if payment:
                status = "paid"
            elif due < on:
                status = "overdue"
            elif due <= on + timedelta(days=DUE_SOON_DAYS):
                status = "due_soon"
            else:
                status = "not_due"
            if status != "paid" and payable is None:
                payable = json.dumps(payable_months(tenancy, on))
            rows.append({
                "tenancy": tenancy,
                "unit": tenancy.unit,
                "due": due,
                "amount": payment.amount if payment else tenancy.monthly_rent,
                "status": status,
                "payable_json": payable if status != "paid" else "",
                "pay_url": reverse("core_rentals:mark_paid", args=[tenancy.pk]),
            })
    rows.sort(key=lambda r: (r["due"], r["unit"].complex.complex_name, r["unit"].identifier))

    def total(status=None):
        chosen = [r for r in rows if status is None or r["status"] == status]
        return {"count": len(chosen), "amount": sum((r["amount"] for r in chosen), 0)}

    expected = total()
    paid = total("paid")

    # Expected income grouped by monthly rate
    by_rate = defaultdict(int)
    for row in rows:
        by_rate[row["tenancy"].monthly_rent] += 1
    breakdown = [
        {"rate": rate, "units": count, "amount": rate * count}
        for rate, count in sorted(by_rate.items(), key=lambda item: item[0], reverse=True)
    ]

    return {
        "month": first,
        "month_label": month_label(first),
        "month_value": f"{first:%Y-%m}",
        "prev_value": f"{add_months(first, -1):%Y-%m}",
        "next_value": f"{add_months(first, 1):%Y-%m}",
        "expected": expected,
        "paid": paid,
        "overdue": total("overdue"),
        "due_soon": total("due_soon"),
        "not_due": total("not_due"),
        "percent": round(paid["amount"] * 100 / expected["amount"]) if expected["amount"] else 0,
        "breakdown": breakdown,
        "upcoming": [r for r in rows if r["status"] in ("due_soon", "not_due")],
        "overdue_rows": [r for r in rows if r["status"] == "overdue"],
        "paid_rows": [r for r in rows if r["status"] == "paid"],
    }


# =========================================================
# LISTING PERFORMANCE
# =========================================================

def _per_day(queryset, field):
    return dict(
        queryset.annotate(day=TruncDate(field)).values("day").annotate(n=Count("pk")).values_list("day", "n")
    )


def _counts(user, first, last):
    """{series: {date: count}} for one landlord between two dates (inclusive)."""
    mine = {"complex__landlord__user": user}
    views = ListingView.objects.filter(**mine, viewed_on__range=(first, last))
    saves = SavedListing.objects.filter(**mine, saved_at__date__range=(first, last))
    applications = Application.objects.filter(unit__complex__landlord__user=user, created_at__date__range=(first, last))
    threads = Conversation.objects.filter(landlord__user=user, created_at__date__range=(first, last))
    # Successful rentals = tenancies that came from a LookApt application
    rentals = Tenancy.objects.filter(
        unit__complex__landlord__user=user, application__isnull=False, created_at__date__range=(first, last),
    )

    inquiries = defaultdict(int)
    for source in (_per_day(applications, "created_at"), _per_day(threads, "created_at")):
        for day, n in source.items():
            inquiries[day] += n
    return {
        "views": dict(views.values("viewed_on").annotate(n=Count("pk")).values_list("viewed_on", "n")),
        "saves": _per_day(saves, "saved_at"),
        "inquiries": dict(inquiries),
        "rentals": _per_day(rentals, "created_at"),
    }


def _change(now, before):
    if not before:
        return None if not now else 100
    return round((now - before) * 100 / before)


def performance(user, month, on=None):
    """Daily counts for the chart + month totals with the change vs the
    previous month (same number of days, so a half-finished month is fair)."""
    on = on or today()
    first = month_start(month)
    last = min(month_end(month), on) if first <= on else month_end(month)
    days = [first + timedelta(days=i) for i in range((last - first).days + 1)] if first <= on else []

    counts = _counts(user, first, last)
    prev_first = add_months(first, -1)
    prev_last = min(month_end(prev_first), prev_first + timedelta(days=max(len(days) - 1, 0)))
    prev = _counts(user, prev_first, prev_last)

    series = []
    for key, label in (("views", "Views"), ("saves", "Saves"), ("inquiries", "Inquiries"), ("rentals", "Successful Rentals")):
        values = [counts[key].get(day, 0) for day in days]
        total = sum(values)
        series.append({
            "key": key, "label": label, "values": values, "total": total,
            "change": _change(total, sum(prev[key].values())),
        })

    current = month_start(on)
    return {
        "month": f"{first:%Y-%m}",
        "month_label": month_label(first),
        "days": [f"{day:%b} {day.day}" for day in days],
        "series": series,
        "months": [
            {"value": f"{m:%Y-%m}", "label": month_label(m)}
            for m in (add_months(current, -i) for i in range(PERFORMANCE_MONTHS))
        ],
    }


# =========================================================
# HOME TAB
# =========================================================

def _attention(context, on):
    """Needs Your Attention: only rows that have something to do."""
    units = [u for g in context["rental_groups"] for u in g["units"]]
    items = []

    overdue = [u for u in units if u.tenancy and u.tenancy.pay["key"] == "overdue"]
    if overdue:
        amount = 0
        for u in overdue:
            paid = {p.due_date for p in u.tenancy.payments.all()}
            unpaid = [due for due in due_dates(u.tenancy, on - timedelta(days=1)) if due not in paid]
            amount += len(unpaid) * u.tenancy.monthly_rent
        items.append({
            "tone": "danger", "icon": "info", "count": len(overdue), "title": "Overdue rent",
            "detail": f"{len(overdue)} unit{'s' if len(overdue) != 1 else ''} overdue · {peso(amount)}",
            "tab": "rentals", "filter": "pay:overdue",
        })

    pending = context["pending_requests"]
    if pending:
        items.append({
            "tone": "warning", "icon": "document", "count": len(pending), "title": "Pending requests",
            "detail": f"{len(pending)} request{'s' if len(pending) != 1 else ''} waiting for review",
            "tab": "inquiries", "subtab": "requests",
        })

    visits = [a for a in pending if a.site_visit_status == Application.SiteVisit.PENDING]
    if visits:
        items.append({
            "tone": "warning", "icon": "calendar_check", "count": len(visits), "title": "Site visits to confirm",
            "detail": f"{len(visits)} visit{'s' if len(visits) != 1 else ''} awaiting confirmation",
            "tab": "inquiries", "subtab": "requests",
        })

    ending = sorted((u for u in units if u.ending_soon), key=lambda u: u.tenancy.term_end)
    if ending:
        first = ending[0]
        items.append({
            "tone": "caution", "icon": "lease", "count": len(ending), "title": "Contracts ending in 30 days",
            "detail": f"{first.unit_name} ({first.complex.complex_name}) ends {first.tenancy.term_end:%b} {first.tenancy.term_end.day}",
            "tab": "rentals", "filter": "ending:1",
        })

    vacant = [g for g in context["waitlist_groups"] if g["outlook"]["key"] == "vacant"]
    if vacant:
        group = vacant[0]
        waiting = len(group["applications"])
        items.append({
            "tone": "good", "icon": "occupants", "count": len(vacant), "title": "Vacant units with a waitlist",
            "detail": f"{group['unit'].unit_name} is vacant · {waiting} on the waitlist (notify)",
            "tab": "inquiries", "subtab": "waitlist",
        })
    return items


def home_context(user, context):
    """`context` already holds get_inquiries_context() + get_rentals_context()."""
    on = today()
    groups = context["rental_groups"]
    units = [u for g in groups for u in g["units"]]
    occupied = sum(1 for u in units if u.state == "occupied")

    properties = []
    for group in groups:
        stats = group["stats"]
        properties.append({
            "complex": group["complex"],
            "cover_url": group["cover_url"],
            "units": stats["total"],
            "occupied": stats["occupied"],
            "vacant": stats["vacant"],
            "percent": round(stats["occupied"] * 100 / stats["total"]) if stats["total"] else 0,
        })

    current = receivables(user, on, on)
    chart = performance(user, on, on)
    return {
        "home": {
            "first_name": user.first_name.split()[0].title() if user.first_name else user.display_name,
            "properties_count": len(groups),
            "units_count": len(units),
            "occupied": occupied,
            "occupancy": round(occupied * 100 / len(units)) if units else 0,
            "overdue_units": sum(1 for u in units if u.tenancy and u.tenancy.pay["key"] == "overdue"),
            "attention": _attention(context, on),
            "properties": properties,
        },
        "receivables": current,
        "performance": chart,
        "performance_json": json.dumps(chart),
    }