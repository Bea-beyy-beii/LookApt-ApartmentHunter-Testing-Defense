from django import template
from django.urls import reverse

from core.core_feedback.forms import FeedbackForm
from core.core_feedback.guide import UserGuide
from core.core_reports.services import SUPPORT_EMAIL

register = template.Library()


@register.inclusion_tag("core_accounts/partials/topbar_right.html", takes_context=True)
def topbar_right(context):
    """Dark mode switch, notification bell and profile menu (landlord + renter pages)."""
    request = context["request"]
    if not request.user.is_authenticated:          # the preview pages (core_preview)
        return {"preview": True}
    profile = request.user.profile                 # Renter / Landlord (None for admins)
    return {
        "request": request,
        "user": request.user,
        "csrf_token": context.get("csrf_token"),
        "support_email": SUPPORT_EMAIL,
        "inquiries_url": inquiries_url(request.user),
        # Profile menu > LookApt Guide / Feedback Form (renters and landlords)
        "guide": UserGuide.for_user(request.user),
        "feedback_form": FeedbackForm(),
        # Stars beside the name: Landlord.rating (renters' profiles have none)
        "landlord_rating": profile.rating if profile else None,
    }


@register.simple_tag
def inquiries_url(user):
    """Where a notification takes you: the Inquiries tab of your own dashboard."""
    return reverse(user.home_url_name) + "?tab=inquiries"