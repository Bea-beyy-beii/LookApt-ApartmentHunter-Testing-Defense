from django import template
from django.utils.html import format_html
from django.utils.safestring import mark_safe

register = template.Library()

# Input icons on the login / sign-up / forgot-password pages (replace the old PNGs).
# Line icons in the same style as the dashboards'; they take the text colour (navy).
ICONS = {
    "person": '<circle cx="12" cy="8" r="3.5"/><path d="M5 20c.8-3.6 3.2-5.3 7-5.3s6.2 1.7 7 5.3"/>',
    "lock": '<rect x="5" y="10.5" width="14" height="10" rx="2"/><path d="M8 10.5V8a4 4 0 0 1 8 0v2.5M12 14.5v2.5"/>',
    "phone": '<rect x="7" y="3" width="10" height="18" rx="2.2"/><path d="M11 18h2"/>',
    "mail": '<rect x="3.5" y="5.5" width="17" height="13" rx="2"/><path d="m4 7 8 6 8-6"/>',
    "gender": '<circle cx="10" cy="14" r="5"/><path d="M13.5 10.5 20 4M15 4h5v5"/>',
    "tag": '<path d="M3.5 12.6V4.5a1 1 0 0 1 1-1h8.1a1 1 0 0 1 .7.3l7.4 7.4a1 1 0 0 1 0 1.4l-8.1 8.1a1 1 0 0 1-1.4 0l-7.4-7.4a1 1 0 0 1-.3-.7Z"/><circle cx="8.5" cy="8.5" r="1.5"/>',
}

PNG_NAMES = {"inbox": "mail"}    # the old file name -> icon


@register.simple_tag
def auth_icon(name):
    name = PNG_NAMES.get(name, name)
    return format_html(
        '<svg class="input-icons" viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" '
        'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{}</svg>',
        mark_safe(ICONS.get(name, "")),
    )
