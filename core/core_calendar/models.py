# core_calendar/models.py
# CalendarEvent: something a landlord posts with "Post on Bulletin" that has a
# date (aircon maintenance, a meeting...). It shows on the landlord's calendar
# and on the calendar widget of renters living in the chosen complexes.
#
# Rent due dates, contract end dates and site visits are NOT stored here: the
# calendar reads them live from core_rentals / core_inquiries, so they can
# never get out of date.
from django.db import models

from core.core_inquiries.labels import clock_label, date_label


class CalendarEvent(models.Model):

    class Type(models.TextChoices):
        ANNOUNCEMENT = "announcement", "Announcement"
        MAINTENANCE = "maintenance", "Maintenance / Inspection"
        MEETING = "meeting", "Meeting"
        OTHER = "other", "Other"

    landlord = models.ForeignKey("core.Landlord", on_delete=models.CASCADE, related_name="calendar_events")
    complexes = models.ManyToManyField("core_listings.Complex", related_name="calendar_events")

    title = models.CharField(max_length=100)
    message = models.TextField(max_length=500)
    event_type = models.CharField(max_length=15, choices=Type.choices, default=Type.ANNOUNCEMENT)

    start_date = models.DateField()
    end_date = models.DateField()                       # same as start_date for one-day events
    start_time = models.TimeField(null=True, blank=True)   # empty = all day
    end_time = models.TimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["start_date", "start_time"]

    def __str__(self):
        return f"{self.title} ({self.start_date})"

    # Category = filter checkbox + colour on the calendar
    CATEGORIES = {
        Type.ANNOUNCEMENT: "announcement",
        Type.MEETING: "announcement",
        Type.OTHER: "announcement",
        Type.MAINTENANCE: "maintenance",
    }

    @property
    def all_day(self):
        return self.start_time is None

    @property
    def is_whole_week(self):
        return self.end_date > self.start_date

    @property
    def category(self):
        return self.CATEGORIES.get(self.event_type, "announcement")

    @property
    def hours_label(self):
        """"2:00 PM – 4:00 PM" (or just the start time)."""
        return clock_label(self.start_time) + (f" – {clock_label(self.end_time)}" if self.end_time else "")

    @property
    def time_label(self):
        """What the calendar shows in the time column."""
        if self.all_day:
            return "All week" if self.is_whole_week else "All-day"
        return self.hours_label

    @property
    def when_label(self):
        """"Oct 11, 2026 – Oct 17, 2026 (whole week)" or "Oct 20, 2026, 2:00 PM – 4:00 PM"."""
        if self.is_whole_week:
            return f"{date_label(self.start_date)} – {date_label(self.end_date)} (whole week)"
        when = date_label(self.start_date)
        if self.start_time:
            when += f", {self.hours_label}"
        return when