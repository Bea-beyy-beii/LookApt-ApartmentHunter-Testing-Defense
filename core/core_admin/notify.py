"""
Tell a user something: a notice in their bell (core_admin.Notice) and an email.

Every message is a subclass of Notification that fills in its own title, text,
tone and email, then the parent's send() does the rest:

    Reactivated(user).send()
    ReportUpdated(report).send()

The email goes out after the database change is saved, and a failed email never
undoes the change (core_accounts/emails.py logs it instead).
"""
from abc import ABC, abstractmethod

from django.db import transaction

from core.core_accounts.emails import NoticeEmail
from core.core_reports.services import SUPPORT_EMAIL
from core.roles import RoleBased

from .models import Notice

DASHBOARD = ("Open LookApt", "/login/")


class Notification(ABC):
    """Abstraction + polymorphism: each kind of message answers title, message,
    subject and paragraphs its own way; send() is the same for all of them."""

    tone = Notice.Tone.GREEN
    in_bell = True            # False when they can't log in to see it
    button = None             # (label, path) at the bottom of the email

    def __init__(self, user):
        self.user = user

    # ---- what each subclass fills in

    @property
    def title(self):
        return ""

    @property
    def message(self):
        return ""

    @property
    @abstractmethod
    def subject(self):
        """The email's subject line."""

    @property
    @abstractmethod
    def paragraphs(self):
        """The email's paragraphs (a list)."""

    @property
    def quote(self):
        return ""

    @property
    def should_send(self):
        return True

    # ---- the same for every message

    def email(self):
        email = {"subject": self.subject, "paragraphs": self.paragraphs}
        if self.quote:
            email["quote"] = self.quote
        if self.button:
            email["button"] = self.button
        return email

    def send(self):
        if not self.should_send:
            return
        if self.in_bell:
            Notice.objects.create(user=self.user, title=self.title, message=self.message, tone=self.tone)
        email, user = self.email(), self.user
        transaction.on_commit(lambda: NoticeEmail(user, **email).send())


# ------------------------------------------------------------------ welcome

class Welcome(RoleBased, Notification):
    """Sent after sign-up; renters and landlords get different first steps."""

    title = "Welcome to LookApt!"
    subject = "Welcome to LookApt!"
    button = DASHBOARD

    @classmethod
    def for_user(cls, user):
        return cls.class_for(user)(user)


class LandlordWelcome(Welcome):
    ROLE = "landlord"
    message = "Verify your account to start publishing listings."
    paragraphs = ["Welcome to LookApt! Your landlord account is ready.",
                  "Before you can publish listings, please verify your account: upload a government ID, a selfie "
                  "holding it, and a business permit or proof of ownership. It takes about 2 minutes."]


class RenterWelcome(Welcome):
    ROLE = "renter"
    message = "Start browsing apartments near you."
    paragraphs = ["Welcome to LookApt! Your account is ready.",
                  "Browse apartments near you, save the ones you like, and message landlords or apply right from LookApt."]


# ------------------------------------------------------------------ verification

class VerificationNotice(Notification):
    """A decision about a landlord's verification, with the admin's reason if any."""

    def __init__(self, user, reason=""):
        super().__init__(user)
        self.reason = reason

    @classmethod
    def for_request(cls, request):
        """The notice for a VerificationRequest's status, or None when there's nothing to tell."""
        notice_class = {"approved": Verified, "resubmit": NewDocumentsNeeded,
                        "rejected": VerificationRejected}.get(request.status)
        return notice_class(request.landlord.user, request.message) if notice_class else None


class Verified(VerificationNotice):
    title = "You're verified!"
    message = "You can now publish listings, post bulletins and file reports."
    subject = "You're verified on LookApt"
    paragraphs = ["Good news: your landlord account is verified.",
                  "You can now publish your listings, post bulletins and file reports. Renters will "
                  "see a verified badge on your profile."]
    button = DASHBOARD


class VerificationRemoved(VerificationNotice):
    """An admin took back a landlord's verification (Users)."""
    tone = Notice.Tone.RED
    title = "Your verification was removed"
    subject = "LookApt: your verification was removed"
    button = DASHBOARD

    @property
    def message(self):
        return self.reason

    @property
    def quote(self):
        return self.reason

    @property
    def paragraphs(self):
        return ["Our team removed the verified badge from your landlord account. Until you're verified again "
                "you can't publish listings, post bulletins or file reports.",
                f"You can upload new documents from your dashboard, or reply to {SUPPORT_EMAIL}. The reason:"]


class NewDocumentsNeeded(VerificationNotice):
    tone = Notice.Tone.YELLOW
    title = "Please upload new documents"
    subject = "LookApt: please upload new verification documents"
    paragraphs = ["We couldn't verify your account with the documents you sent. Here's what to fix:"]
    button = ("Upload again", "/login/")

    @property
    def message(self):
        return self.reason

    @property
    def quote(self):
        return self.reason


class VerificationRejected(VerificationNotice):
    tone = Notice.Tone.RED
    title = "Verification not approved"
    subject = "LookApt: your verification wasn't approved"
    paragraphs = ["We reviewed your documents and couldn't approve your verification.",
                  f"If you think this is a mistake, reply to {SUPPORT_EMAIL}."]

    @property
    def message(self):
        return self.reason

    @property
    def quote(self):
        return self.reason


# ------------------------------------------------------------------ reports

class ReportNotice(Notification):
    """Sent to the person who filed the report."""

    def __init__(self, report):
        super().__init__(report.reporter)
        self.report = report
        self.name = report.reported_user.display_name


class ReportReceived(ReportNotice):
    tone = Notice.Tone.YELLOW
    title = "Report received"
    subject = "LookApt: we received your report"

    @property
    def message(self):
        return f"We received your report about {self.name} and will review it soon."

    @property
    def paragraphs(self):
        return [f"Thank you for your report about {self.name}. Our team will review it and let you know "
                "what we decide."]


class ReportUpdated(ReportNotice):
    """Each status change (with the admin's note, if any)."""

    button = ("See your reports", "/login/")
    LINES = {
        "reviewing": "Our team is now reviewing your report about {name}.",
        "resolved": "Your report about {name} has been resolved.",
        "dismissed": "Your report about {name} has been closed.",
    }

    @property
    def line(self):
        line = self.LINES.get(self.report.status)
        return line.format(name=self.name) if line else None

    @property
    def should_send(self):
        return self.line is not None

    @property
    def tone(self):
        return Notice.Tone.GREEN if self.report.status == "resolved" else Notice.Tone.YELLOW

    @property
    def status(self):
        return self.report.get_status_display().lower()

    @property
    def title(self):
        return f"Report {self.status}"

    @property
    def message(self):
        return self.report.admin_note or self.line

    @property
    def subject(self):
        return f"LookApt: your report is {self.status}"

    @property
    def paragraphs(self):
        return [self.line]

    @property
    def quote(self):
        return self.report.admin_note


# ------------------------------------------------------------------ the account

class ReasonNotice(Notification):
    """A message that quotes what the admin wrote."""

    def __init__(self, user, reason):
        super().__init__(user)
        self.reason = reason

    @property
    def quote(self):
        return self.reason


class AccountWarning(ReasonNotice):
    tone = Notice.Tone.RED
    title = "Warning from LookApt"
    subject = "LookApt: a warning about your account"
    paragraphs = ["We received a report about your account. Please read this message from our team:"]
    button = DASHBOARD

    @property
    def message(self):
        return self.reason


class Suspended(ReasonNotice):
    in_bell = False           # they can't log in to see it
    subject = "LookApt: your account has been suspended"

    @property
    def paragraphs(self):
        return ["Your LookApt account has been suspended, so you can't log in for now."
                + (" Your listings are hidden from renters." if self.user.is_landlord else ""),
                f"If you think this is a mistake, email {SUPPORT_EMAIL}."]


class Reactivated(Notification):
    title = "Your account is active again"
    message = "Welcome back! You can use LookApt as usual."
    subject = "LookApt: your account is active again"
    paragraphs = ["Your LookApt account has been reactivated. You can log in again."]
    button = DASHBOARD


class ListingsUnpublished(ReasonNotice):
    tone = Notice.Tone.RED
    title = "Your listings were unpublished"
    subject = "LookApt: your listings were unpublished"
    paragraphs = ["Our team unpublished your listings after reviewing a report. Renters can't see "
                  "them until you publish them again."]
    button = DASHBOARD

    @property
    def message(self):
        return self.reason


class AccountDeleted(Notification):
    # Email only: the account (and its bell) is gone. user still holds the email address in memory.
    in_bell = False
    subject = "LookApt: your account has been deleted"
    paragraphs = ["As you asked, your LookApt account and the data linked to it have been deleted.",
                  "Thank you for using LookApt. You're welcome to sign up again anytime."]
