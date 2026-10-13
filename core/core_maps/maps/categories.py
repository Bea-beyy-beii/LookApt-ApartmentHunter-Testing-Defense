# core_maps/maps/categories.py
# Icon + colour for every Landmark category. Used by both the side panel
# (HTML) and the Folium markers so they always look the same.
from core.core_listings.models import Landmark

Types = Landmark.LandmarkTypes


# Inner SVG markup for a 24x24 viewBox, drawn with stroke="currentColor"
_ICONS = {
    Types.SCHOOL: '<path d="M2 9l10-5 10 5-10 5z"/><path d="M6 11v5c3 2.5 9 2.5 12 0v-5"/><path d="M22 9v6"/>',
    Types.HEALTHCENTER: '<rect x="4" y="4" width="16" height="16" rx="3"/><path d="M12 8v8M8 12h8"/>',
    Types.MARKET: '<path d="M4 9h16l-1.5 11h-13z"/><path d="M8 9V7a4 4 0 0 1 8 0v2"/>',
    Types.PHARMACY: '<rect x="3" y="9" width="18" height="6" rx="3" transform="rotate(-45 12 12)"/><path d="M9.5 9.5l5 5"/>',
    Types.BANK: '<path d="M3 10l9-5 9 5"/><path d="M5 10v8M10 10v8M14 10v8M19 10v8M3 20h18"/>',
    Types.RESTAURANT: '<path d="M7 3v8M5 3v5a2 2 0 0 0 4 0V3M7 11v10"/><path d="M17 3c-2 2-2 6 0 8v10"/>',
    Types.TERMINAL: '<rect x="4" y="4" width="16" height="13" rx="2"/><path d="M4 11h16M7 20l1-3M17 20l-1-3"/><circle cx="8" cy="14" r=".6"/><circle cx="16" cy="14" r=".6"/>',
    Types.AIRPORT: '<path d="M10.5 20l1.5-6-6 2v-2l6-4V5a1.5 1.5 0 0 1 3 0v5l6 4v2l-6-2 1.5 6z"/>',
    Types.CHURCH: '<path d="M12 2v5M10 4h4"/><path d="M6 21v-8l6-5 6 5v8z"/><path d="M10 21v-4a2 2 0 0 1 4 0v4"/>',
    Types.GOVERNMENT: '<path d="M3 21h18M5 21V10h14v11M12 3l8 5H4z"/><path d="M9 14v4M15 14v4"/>',
    Types.MALL: '<rect x="4" y="3" width="16" height="18" rx="1"/><path d="M8 7h2M14 7h2M8 11h2M14 11h2M8 15h2M14 15h2"/>',
    Types.PARK: '<path d="M12 3a5 5 0 0 0-4 8 4 4 0 0 0 4 6 4 4 0 0 0 4-6 5 5 0 0 0-4-8z"/><path d="M12 17v4"/>',
    Types.GYM: '<path d="M6 8v8M18 8v8M3 10v4M21 10v4M6 12h12"/>',
    Types.OTHER: '<path d="M12 21s7-6.1 7-12A7 7 0 1 0 5 9c0 5.9 7 12 7 12z"/><circle cx="12" cy="9" r="2.5"/>',
}

# (icon colour, soft background)
_COLORS = {
    Types.SCHOOL: ("#1f5fbf", "#e3edfb"),
    Types.HEALTHCENTER: ("#d64545", "#fbe6e6"),
    Types.MARKET: ("#e8901a", "#fdf0dc"),
    Types.PHARMACY: ("#2c9a6a", "#e1f4ea"),
    Types.BANK: ("#4a5a78", "#e8ebf1"),
    Types.RESTAURANT: ("#e0702d", "#fdeadf"),
    Types.TERMINAL: ("#178a94", "#ddf2f3"),
    Types.AIRPORT: ("#3b6fd1", "#e4ecfb"),
    Types.CHURCH: ("#b8323a", "#f9e3e4"),
    Types.GOVERNMENT: ("#6d4bc2", "#ece6f8"),
    Types.MALL: ("#203a68", "#e4e9f2"),
    Types.PARK: ("#3d9a4b", "#e3f3e5"),
    Types.GYM: ("#7a5a2e", "#f2eadf"),
    Types.OTHER: ("#69758a", "#eceef2"),
}

class MarkerStyle:
    """Colours + icon of a map marker (the side panel and Folium use the same)."""

    def __init__(self, color, bg, icon):
        self.color = color
        self.bg = bg
        self.icon = icon        # inner SVG markup for a 24x24 viewBox

    def svg(self, size=18, stroke_width=1.9):
        return (
            f'<svg viewBox="0 0 24 24" width="{size}" height="{size}" fill="none" stroke="currentColor" '
            f'stroke-width="{stroke_width}" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{self.icon}</svg>'
        )

    def as_dict(self):
        return {"color": self.color, "bg": self.bg, "icon": self.icon}


class CategoryStyle(MarkerStyle):
    """Inheritance: a MarkerStyle picked from a Landmark category (unknown -> Other)."""

    def __init__(self, category):
        self.category = category if category in _ICONS else Types.OTHER
        color, bg = _COLORS[self.category]
        super().__init__(color, bg, _ICONS[self.category])

    @property
    def label(self):
        return Types(self.category).label

    def as_dict(self):
        return {"category": str(self.category), "label": self.label, **super().as_dict()}

    @classmethod
    def all(cls):
        return [cls(category).as_dict() for category in Types.values]


# Complex markers on the renter map
COMPLEX_STYLE = MarkerStyle(
    "#c98a3c", "#fdf1e0",
    '<path d="M3 21h18M5 21V7l7-4 7 4v14"/><path d="M9 10h1M14 10h1M9 14h1M14 14h1M10 21v-3h4v3"/>',
)
