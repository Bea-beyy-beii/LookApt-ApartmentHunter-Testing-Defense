"""
Reading values that arrive as text (query string, posted JSON or form).

    class MyView(ParsesDates, View):  ...  self.parse_date("2026-10-17") -> date
"""
from datetime import date, time


class ParsesDates:
    """For views and admin tabs that read YYYY-MM-DD dates and HH:MM times."""

    @staticmethod
    def parse_date(value):
        """A date, or None when it's empty or not a real date."""
        try:
            return date.fromisoformat(value) if value else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def parse_time(value):
        """A time, or None when it's empty or not a real time."""
        try:
            return time.fromisoformat(value) if value else None
        except (TypeError, ValueError):
            return None
