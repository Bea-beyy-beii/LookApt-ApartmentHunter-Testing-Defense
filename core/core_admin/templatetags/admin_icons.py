from django import template
from django.utils.html import format_html
from django.utils.safestring import mark_safe

register = template.Library()

# Same stroke style as the dashboards' icons (core_listings/icons.py)
ICONS = {
    "arrow_left": '<path d="M19 12H5M11 18l-6-6 6-6"/>',
    "arrow_right": '<path d="M5 12h14M13 6l6 6-6 6"/>',
    "external": '<path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/>',
    "play": '<path d="M7 5v14l11-7Z"/>',
    "warning": '<path d="M12 4 2.5 20h19Z"/><path d="M12 10v4M12 17h.01"/>',
    "check": '<path d="m5 12.5 4.5 4.5L19 7.5"/>',
    "x": '<path d="M6 6l12 12M18 6 6 18"/>',
    "question": '<circle cx="12" cy="12" r="9"/><path d="M9.5 9.5a2.5 2.5 0 1 1 3.5 2.3c-.6.3-1 .8-1 1.5V14M12 17h.01"/>',
    "alert": '<circle cx="12" cy="12" r="9"/><path d="M12 7.5v5M12 16h.01"/>',
    "verified": '<path d="M12 3 5 6v5.5c0 4.3 3 8 7 9.5 4-1.5 7-5.2 7-9.5V6l-7-3Z"/><path d="m9 12 2 2 4-4"/>',
    "inbox": '<path d="M4 13h4l1.5 3h5L16 13h4"/><path d="M5.5 5h13l1.5 8v6H4v-6Z"/>',
    "search": '<circle cx="11" cy="11" r="7"/><path d="m20 20-4-4"/>',
    "file": '<path d="M6 3h8l4 4v14H6Z"/><path d="M14 3v4h4"/>',
}


@register.simple_tag
def ap_icon(name, size=16):
    """An inline SVG icon, e.g. {% ap_icon "warning" %} or {% ap_icon "check" 14 %}."""
    return format_html(
        '<svg class="ap-icon" viewBox="0 0 24 24" width="{0}" height="{0}" fill="none" stroke="currentColor" '
        'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{1}</svg>',
        size, mark_safe(ICONS.get(name, "")),
    )


@register.simple_tag
def page_query(params, number):
    """?…&page=N keeping this list's filters (and only one page=)."""
    params = params.copy()
    params["page"] = number
    return "?" + params.urlencode()
