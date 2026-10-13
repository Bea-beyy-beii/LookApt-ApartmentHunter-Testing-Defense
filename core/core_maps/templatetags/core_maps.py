# core_maps/templatetags/core_maps.py
#
# Usage:
#   {% load core_maps %}
#   {% location_picker kind="landlord" %}                       -> landlord wizard (pin + landmarks)
#   {% location_picker kind="renter" results="#nearby-results" %} -> renter "find near"
#   {% location_picker kind="landlord" editable=False lat=property.latitude lng=property.longitude complex=property.pk %}
#   {% location_picker kind="landlord" saved=property|saved_landmarks saved_complex=property.pk %}
#       -> editing: start from the saved landmarks instead of looking them up again
import uuid

from django import template
from django.utils.safestring import mark_safe

from core.core_maps.maps.categories import COMPLEX_STYLE, CategoryStyle
from core.core_maps.maps.geo import SearchRadius, TravelMode
from core.core_maps.maps.services import ComplexLandmarks

register = template.Library()


class LocationPicker:
    """One map picker on a page: its unique id and the context of its template."""

    def __init__(self, kind="landlord", editable=True, lat=None, lng=None, radius=SearchRadius.DEFAULT_KM,
                 mode=TravelMode.DEFAULT_KEY, complex=None, results="", height=380, mirror="", label="",
                 saved=None, saved_complex=None):
        self.picker_id = f"lk-map-{uuid.uuid4().hex[:8]}"
        self.kind = kind
        self.editable = editable
        self.lat = lat
        self.lng = lng
        self.radius = radius
        self.mode = TravelMode.get(mode)
        self.complex = complex
        self.results = results
        self.height = height
        self.mirror = mirror
        self.label = label
        self.saved = saved
        self.saved_complex = saved_complex

    @staticmethod
    def _blank_if_none(value):
        return "" if value in (None, "") else value

    def context(self):
        return {
            "saved": list(self.saved or []),
            "saved_id": f"{self.picker_id}-saved",
            "saved_complex": self.saved_complex or "",
            "picker_id": self.picker_id,
            "kind": self.kind,
            "editable": self.editable,
            "lat": self._blank_if_none(self.lat),
            "lng": self._blank_if_none(self.lng),
            "radius": self.radius,
            "mode": self.mode.key,
            "complex": self.complex or "",
            "results": self.results,
            "height": self.height,
            "mirror": self.mirror,
            "label": self.label,
            "modes": TravelMode.all(),
            "presets": SearchRadius.presets(),
        }


@register.inclusion_tag("core_maps/location_picker.html")
def location_picker(**options):
    return LocationPicker(**options).context()


@register.simple_tag
def landmark_icon(category, size=18):
    """Inline SVG for a landmark category (trusted markup from categories.py)."""
    return mark_safe(CategoryStyle(category).svg(size=size))


@register.filter
def landmark_style(category):
    return CategoryStyle(category).as_dict()


@register.simple_tag
def landmark_categories():
    """Every landmark category with its label, colours and icon (manual landmark form)."""
    return CategoryStyle.all()


@register.simple_tag
def complex_icon(size=18):
    return mark_safe(COMPLEX_STYLE.svg(size=size))


@register.filter
def saved_landmarks(complex_obj):
    """{{ property|saved_landmarks }} -> the landmarks saved for a complex."""
    return ComplexLandmarks(complex_obj).as_list()
