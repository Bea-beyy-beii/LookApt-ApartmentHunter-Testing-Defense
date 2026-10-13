# core_inquiries/labels.py
# How dates, times and file sizes are written on the Inquiries and Calendar pages.
# Pure formatting (no state, no database), shared by the models and the services.
from django.utils import timezone


def date_label(day):
    """"Nov 30, 2026". Built by hand: strftime's no-padding flag crashes on Windows."""
    return f"{day:%b} {day.day}, {day.year}"


def clock_label(value):
    """"2:00 PM"."""
    return f"{value.hour % 12 or 12}:{value:%M %p}"


def time_label(moment):
    """"Oct 6, 3:05 PM" in local time."""
    moment = timezone.localtime(moment)
    return f"{moment:%b} {moment.day}, {clock_label(moment)}"


def size_label(size):
    """"1.5 MB" or "300 KB"."""
    return f"{size / (1024 * 1024):.1f} MB" if size >= 1024 * 1024 else f"{max(1, round(size / 1024))} KB"
