"""
Tell a user something: a notice in their bell (core_admin.Notice) and an email.

    notify(user, "You're verified!", "You can now publish your listings.",
           tone="green", email=dict(subject=..., paragraphs=[...], quote="", button=(label, path)))

The email goes out after the database change is saved, and a failed email never
undoes the change (core_accounts/emails.py logs it instead).
"""
from django.db import transaction

from core.core_accounts.emails import send_email
from core.core_reports.services import SUPPORT_EMAIL

from .models import Notice

DASHBOARD = ("Open LookApt", "/login/")


def notify(user, title, message, tone=Notice.Tone.GREEN, email=None):
    Notice.objects.create(user=user, title=title, message=message, tone=tone)
    if email:
        transaction.on_commit(lambda: send_email(user, **email))


# ------------------------------------------------------------------ the messages

def welcome(user):
    if user.role == "landlord":
        lines = ["Welcome to LookApt! Your landlord account is ready.",
                 "Before you can publish listings, please verify your account: upload a government ID, a selfie "
                 "holding it, and a business permit or proof of ownership. It takes about 2 minutes."]
        note = "Verify your account to start publishing listings."
    else:
        lines = ["Welcome to LookApt! Your account is ready.",
                 "Browse apartments near you, save the ones you like, and message landlords or apply right from LookApt."]
        note = "Start browsing apartments near you."
    notify(user, "Welcome to LookApt!", note, Notice.Tone.GREEN,
           email=dict(subject="Welcome to LookApt!", paragraphs=lines, button=DASHBOARD))


def verified(user):
    notify(user, "You're verified!", "You can now publish listings, post bulletins and file reports.",
           Notice.Tone.GREEN,
           email=dict(subject="You're verified on LookApt",
                      paragraphs=["Good news: your landlord account is verified.",
                                  "You can now publish your listings, post bulletins and file reports. Renters will "
                                  "see a verified badge on your profile."],
                      button=DASHBOARD))


def new_documents_needed(user, reason):
    notify(user, "Please upload new documents", reason, Notice.Tone.YELLOW,
           email=dict(subject="LookApt: please upload new verification documents",
                      paragraphs=["We couldn't verify your account with the documents you sent. Here's what to fix:"],
                      quote=reason, button=("Upload again", "/login/")))


def verification_rejected(user, reason):
    notify(user, "Verification not approved", reason, Notice.Tone.RED,
           email=dict(subject="LookApt: your verification wasn't approved",
                      paragraphs=["We reviewed your documents and couldn't approve your verification.",
                                  f"If you think this is a mistake, reply to {SUPPORT_EMAIL}."],
                      quote=reason))


def report_received(report):
    name = report.reported_user.display_name
    notify(report.reporter, "Report received", f"We received your report about {name} and will review it soon.",
           Notice.Tone.YELLOW,
           email=dict(subject="LookApt: we received your report",
                      paragraphs=[f"Thank you for your report about {name}. Our team will review it and let you know "
                                  "what we decide."]))


def report_updated(report):
    """The reporter hears about each status change (with the admin's note, if any)."""
    name = report.reported_user.display_name
    status = report.get_status_display()
    lines = {
        "reviewing": f"Our team is now reviewing your report about {name}.",
        "resolved": f"Your report about {name} has been resolved.",
        "dismissed": f"Your report about {name} has been closed.",
    }
    line = lines.get(report.status)
    if not line:
        return
    tone = Notice.Tone.GREEN if report.status == "resolved" else Notice.Tone.YELLOW
    notify(report.reporter, f"Report {status.lower()}", report.admin_note or line, tone,
           email=dict(subject=f"LookApt: your report is {status.lower()}", paragraphs=[line], quote=report.admin_note,
                      button=("See your reports", "/login/")))


def warning(user, message):
    notify(user, "Warning from LookApt", message, Notice.Tone.RED,
           email=dict(subject="LookApt: a warning about your account",
                      paragraphs=["We received a report about your account. Please read this message from our team:"],
                      quote=message,
                      button=DASHBOARD))


def suspended(user, reason):
    # No bell notice: they can't log in to see it
    transaction.on_commit(lambda: send_email(
        user, subject="LookApt: your account has been suspended",
        paragraphs=["Your LookApt account has been suspended, so you can't log in for now."
                    + (" Your listings are hidden from renters." if user.role == "landlord" else ""),
                    f"If you think this is a mistake, email {SUPPORT_EMAIL}."],
        quote=reason))


def reactivated(user):
    notify(user, "Your account is active again", "Welcome back! You can use LookApt as usual.", Notice.Tone.GREEN,
           email=dict(subject="LookApt: your account is active again",
                      paragraphs=["Your LookApt account has been reactivated. You can log in again."],
                      button=DASHBOARD))


def unpublished_by_admin(user, reason):
    notify(user, "Your listings were unpublished", reason, Notice.Tone.RED,
           email=dict(subject="LookApt: your listings were unpublished",
                      paragraphs=["Our team unpublished your listings after reviewing a report. Renters can't see "
                                  "them until you publish them again."],
                      quote=reason, button=DASHBOARD))


def account_deleted(user):
    # Email only: the account (and its bell) is gone. user still holds the email address in memory.
    transaction.on_commit(lambda: send_email(
        user, subject="LookApt: your account has been deleted",
        paragraphs=["As you asked, your LookApt account and the data linked to it have been deleted.",
                    "Thank you for using LookApt. You're welcome to sign up again anytime."]))
