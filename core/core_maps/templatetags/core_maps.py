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

from core.core_maps.maps.categories import COMPLEX_STYLE, all_categories, category_style, svg
from core.core_maps.maps.geo import DEFAULT_MODE, DEFAULT_RADIUS_KM, TRAVEL_MODES, radius_presets

register = template.Library()


@register.inclusion_tag("core_maps/location_picker.html")
def location_picker(kind="landlord", editable=True, lat=None, lng=None, radius=DEFAULT_RADIUS_KM,
                    mode=DEFAULT_MODE, complex=None, results="", height=380, mirror="", label="",
                    saved=None, saved_complex=None):
    picker_id = f"lk-map-{uuid.uuid4().hex[:8]}"
    return {
        "saved": list(saved or []),
        "saved_id": f"{picker_id}-saved",
        "saved_complex": saved_complex or "",
        "picker_id": picker_id,
        "kind": kind,
        "editable": editable,
        "lat": "" if lat in (None, "") else lat,
        "lng": "" if lng in (None, "") else lng,
        "radius": radius,
        "mode": mode if mode in TRAVEL_MODES else DEFAULT_MODE,
        "complex": complex or "",
        "results": results,
        "height": height,
        "mirror": mirror,
        "label": label,
        "modes": [{"key": key, **value} for key, value in TRAVEL_MODES.items()],
        "presets": radius_presets(),
    }


@register.simple_tag
def landmark_icon(category, size=18):
    """Inline SVG for a landmark category (trusted markup from categories.py)."""
    from django.utils.safestring import mark_safe
    return mark_safe(svg(category_style(category)["icon"], size=size))


@register.filter
def landmark_style(category):
    return category_style(category)


@register.simple_tag
def landmark_categories():
    """Every landmark category with its label, colours and icon (manual landmark form)."""
    return all_categories()


@register.simple_tag
def complex_icon(size=18):
    from django.utils.safestring import mark_safe
    return mark_safe(svg(COMPLEX_STYLE["icon"], size=size))


@register.filter
def saved_landmarks(complex_obj):
    """{{ property|saved_landmarks }} -> the landmarks saved for a complex."""
    from core.core_maps.maps.services import complex_landmarks
    if not complex_obj:
        return []
    return complex_landmarks(complex_obj)
