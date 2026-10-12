"""
LookApt's account emails (everything except the sign-up / reset codes in otp.py).

    send_email(user, subject, paragraphs, quote="", button=("Open LookApt", "/login/"))

Same design and logo as the code email. A failed email is logged, never
raised: an admin's decision or a sign-up must not fail because SMTP is down.
"""
import logging

from django.conf import settings
from django.template.loader import render_to_string

from core.core_reports.services import SUPPORT_EMAIL

from .otp import EmailWithInlineLogo, _logo_bytes

logger = logging.getLogger(__name__)


def absolute_url(path):
    """/login/ -> https://lookapt.onrender.com/login/ (settings.SITE_URL)."""
    return settings.SITE_URL.rstrip("/") + path


def send_email(user, subject, paragraphs, quote="", button=None):
    if not user.email:
        return False
    greeting = f"Hello, {user.first_name.title()}!" if user.first_name else "Hello!"
    button_label, button_path = button or ("", "")
    button_url = absolute_url(button_path) if button_path else ""

    text = "\n\n".join([greeting, *paragraphs] + ([quote] if quote else []))
    if button_url:
        text += f"\n\n{button_label}: {button_url}"
    text += f"\n\nQuestions? Email us at {SUPPORT_EMAIL}.\n\nBest,\nLookApt"

    linked_logo = settings.EMAIL_LOGO_URL.strip()
    if not linked_logo.startswith(("http://", "https://")) or "://localhost" in linked_logo or "://127.0.0.1" in linked_logo:
        linked_logo = ""
    logo = None if linked_logo else _logo_bytes()
    html = render_to_string("core_accounts/emails/notice.html", {
        "subject": subject, "greeting": greeting, "paragraphs": paragraphs, "quote": quote,
        "button_label": button_label, "button_url": button_url, "support_email": SUPPORT_EMAIL,
        "logo_src": linked_logo or ("cid:lookapt-logo@lookapt" if logo else ""),
    })

    message = EmailWithInlineLogo(subject, text, settings.DEFAULT_FROM_EMAIL, [user.email], logo=logo)
    message.attach_alternative(html, "text/html")
    try:
        message.send()
    except Exception:
        logger.exception("Couldn't send %r to %s", subject, user.email)
        return False
    return True