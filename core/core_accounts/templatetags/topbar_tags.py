from django import template
from django.urls import reverse

from core.core_reports.services import SUPPORT_EMAIL

register = template.Library()

DASHBOARDS = {"landlord": "core_landlords:dashboard", "renter": "core_renters:dashboard"}


@register.inclusion_tag("core_accounts/partials/topbar_right.html", takes_context=True)
def topbar_right(context):
    """Dark mode switch, notification bell and profile menu (landlord + renter pages)."""
    request = context["request"]
    if not request.user.is_authenticated:          # the preview pages (core_preview)
        return {"preview": True}
    return {
        "request": request,
        "user": request.user,
        "csrf_token": context.get("csrf_token"),
        "support_email": SUPPORT_EMAIL,
        "inquiries_url": inquiries_url(request.user),
    }


@register.simple_tag
def inquiries_url(user):
    """Where a notification takes you: the Inquiries tab of your own dashboard."""
    return reverse(DASHBOARDS.get(user.role, "core_renters:dashboard")) + "?tab=inquiries"