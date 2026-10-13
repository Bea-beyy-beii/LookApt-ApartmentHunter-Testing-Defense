"""
Sample numbers for the landlord preview's Home tab (nothing is read from or
saved to the database). The shapes match core_landlords.sections.HomeSection.context().
"""
import json
import uuid
from datetime import timedelta
from types import SimpleNamespace

from core.core_inquiries.services import today
from core.core_landlords.services import Month, PerformanceChart

# Daily Views / Saves / Inquiries / Successful Rentals, repeated across the month
VIEWS = [3, 5, 4, 6, 8, 7, 5, 9, 11, 8, 10, 12, 9, 7]
SAVES = [1, 0, 2, 1, 3, 2, 1, 2, 4, 3, 2, 5, 3, 2]
INQUIRIES = [0, 1, 0, 1, 2, 1, 0, 1, 2, 1, 3, 2, 1, 1]
RENTALS = [0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 1, 0, 0, 0]

PROPERTIES = [
    ("Sunrise Residences", "Poblacion District, Davao City", 6, 5),
    ("Bea's Residences", "Matina, Davao City", 4, 3),
]


def _performance(on):
    month = Month(on)
    first = month.first
    days = [first + timedelta(days=i) for i in range((on - first).days + 1)]
    series = []
    for key, label, pattern in (("views", "Views", VIEWS), ("saves", "Saves", SAVES),
                                ("inquiries", "Inquiries", INQUIRIES), ("rentals", "Successful Rentals", RENTALS)):
        values = [pattern[i % len(pattern)] for i in range(len(days))]
        series.append({"key": key, "label": label, "values": values, "total": sum(values), "change": 12})
    return {
        "month": f"{first:%Y-%m}",
        "month_label": month.label,
        "days": [f"{day:%b} {day.day}" for day in days],
        "series": series,
        "months": [{"value": m.value, "label": m.label} for m in month.recent(PerformanceChart.MONTHS)],
    }


def _receivables(on):
    month = Month(on)
    first = month.first
    rates = [(6500, 5), (5500, 3)]
    expected = sum(rate * units for rate, units in rates)
    paid = 6500 * 3 + 5500 * 2
    total = lambda count, amount: {"count": count, "amount": amount}
    return {
        "month": first,
        "month_label": month.label,
        "month_value": month.value,
        "prev_value": month.shift(-1).value,
        "next_value": month.shift(1).value,
        "expected": total(8, expected),
        "paid": total(5, paid),
        "overdue": total(0, 0),
        "due_soon": total(2, 12000),
        "not_due": total(1, 5500),
        "percent": round(paid * 100 / expected),
        "breakdown": [{"rate": rate, "units": units, "amount": rate * units} for rate, units in rates],
        "upcoming": [],
        "overdue_rows": [],
    }


def landlord_home():
    """Context for core_landlords/home/home.html."""
    on = today()
    properties = []
    for i, (name, address, units, occupied) in enumerate(PROPERTIES):
        properties.append({
            # A made-up id: the link only opens the sign-up prompt (preview.js)
            "complex": SimpleNamespace(pk=uuid.UUID(int=i + 1), complex_name=name, address=address),
            "cover_url": "",
            "units": units, "occupied": occupied, "vacant": units - occupied,
            "percent": round(occupied * 100 / units),
        })
    units_count = sum(p["units"] for p in properties)
    occupied = sum(p["occupied"] for p in properties)
    performance = _performance(on)
    return {
        "home": {
            "first_name": "Landlord",
            "properties_count": len(properties),
            "units_count": units_count,
            "occupied": occupied,
            "occupancy": round(occupied * 100 / units_count),
            "overdue_units": 0,
            "attention": [],
            "properties": properties,
        },
        "pending_requests_count": 3,
        "waitlist_count": 2,
        "unread_messages_count": 1,
        "receivables": _receivables(on),
        "performance": performance,
        "performance_json": json.dumps(performance),
    }