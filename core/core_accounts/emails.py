"""
LookApt's emails.

    NoticeEmail(user, subject, paragraphs, quote="", button=("Open LookApt", "/login/")).send()

LookAptEmail is the parent of every email we send: the same design and logo,
and each subclass only gives its words (NoticeEmail here, CodeEmail in otp.py).
"""
import logging
from abc import ABC, abstractmethod
from functools import cache

from django.conf import settings
from django.contrib.staticfiles import finders
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string

logger = logging.getLogger(__name__)


class EmailWithInlineLogo(EmailMultiAlternatives):
    """HTML email whose logo sits *inside* the HTML part (multipart/related),
    so mail apps show it in the message and not as an attachment."""

    def __init__(self, *args, logo=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.logo = logo

    def message(self, *args, **kwargs):
        msg = super().message(*args, **kwargs)
        if self.logo:
            for part in msg.walk():
                if part.get_content_type() == 'text/html':
                    part.add_related(self.logo, maintype='image', subtype='png',
                                     cid='<lookapt-logo@lookapt>', filename='lookapt-logo.png',
                                     disposition='inline')
                    break
        return msg


class LookAptEmail(ABC):
    """One email with LookApt's logo (abstraction: subclasses give the subject, text and template)."""

    LOGO = 'core/images/logo2.png'          # the house logo in the email's signature
    template_name = None

    def __init__(self, to, subject):
        self.to = to
        self.subject = subject

    @abstractmethod
    def text(self):
        """The plain-text version."""

    @abstractmethod
    def html_context(self):
        """What the HTML template needs (the logo is added by build())."""

    @staticmethod
    @cache
    def _logo_bytes():
        path = finders.find(LookAptEmail.LOGO)
        if not path:
            return None
        with open(path, 'rb') as f:
            return f.read()

    @staticmethod
    def _linked_logo():
        # The logo is a link only if EMAIL_LOGO_URL is a full public http(s) URL
        # (mail apps can't open /media/... or localhost); otherwise it's embedded.
        linked_logo = settings.EMAIL_LOGO_URL.strip()
        if not linked_logo.startswith(('http://', 'https://')) or '://localhost' in linked_logo or '://127.0.0.1' in linked_logo:
            return ''
        return linked_logo

    def build(self):
        linked_logo = self._linked_logo()
        logo = None if linked_logo else self._logo_bytes()
        html = render_to_string(self.template_name, {
            **self.html_context(),
            'logo_src': linked_logo or ('cid:lookapt-logo@lookapt' if logo else ''),
        })
        message = EmailWithInlineLogo(self.subject, self.text(), settings.DEFAULT_FROM_EMAIL, [self.to], logo=logo)
        message.attach_alternative(html, 'text/html')
        return message

    def send(self):
        self.build().send()


class NoticeEmail(LookAptEmail):
    """A notice to a user (welcome, verified, suspended ...), with an optional quote and button."""

    template_name = 'core_accounts/emails/notice.html'

    def __init__(self, user, subject, paragraphs, quote="", button=None):
        super().__init__(user.email, subject)
        self.user = user
        self.paragraphs = paragraphs
        self.quote = quote
        self.button_label, button_path = button or ("", "")
        self.button_url = self.absolute_url(button_path) if button_path else ""

    @staticmethod
    def absolute_url(path):
        """/login/ -> https://lookapt.onrender.com/login/ (settings.SITE_URL)."""
        return settings.SITE_URL.rstrip("/") + path

    @property
    def support_email(self):
        from core.core_reports.services import SUPPORT_EMAIL
        return SUPPORT_EMAIL

    @property
    def greeting(self):
        return f"Hello, {self.user.first_name.title()}!" if self.user.first_name else "Hello!"

    def text(self):
        text = "\n\n".join([self.greeting, *self.paragraphs] + ([self.quote] if self.quote else []))
        if self.button_url:
            text += f"\n\n{self.button_label}: {self.button_url}"
        return text + f"\n\nQuestions? Email us at {self.support_email}.\n\nBest,\nLookApt"

    def html_context(self):
        return {
            "subject": self.subject, "greeting": self.greeting, "paragraphs": self.paragraphs, "quote": self.quote,
            "button_label": self.button_label, "button_url": self.button_url, "support_email": self.support_email,
        }

    def send(self):
        """True if it went out. Never raises (see the top of this file)."""
        if not self.user.email:
            return False
        message = self.build()
        try:
            message.send()
        except Exception:
            logger.exception("Couldn't send %r to %s", self.subject, self.user.email)
            return False
        return True
