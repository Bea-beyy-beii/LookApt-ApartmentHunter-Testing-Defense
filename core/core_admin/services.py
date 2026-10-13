"""
The admin panel (/admin-panel/): the overview's numbers, and the actions admins take.

    Overview      SidebarBadges, ActivityChart, Overview
    Verification  VerificationDecision
    Users         UserModeration (suspend, reactivate, warn, delete, ...)
    Reports       ReportModeration

The list tabs (verification / users / reports) are in tabs.py. Every decision
tells the user through core_admin/notify.py (bell + email).
"""
import logging
from collections import Counter
from datetime import timedelta

from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import models, router, transaction
from django.db.models import Count, Q
from django.db.models.deletion import Collector
from django.utils import timezone

from core.core_inquiries.models import Application
from core.core_listings.models import Complex
from core.core_rentals.models import Tenancy
from core.core_reports.models import Report
from core.core_verification.models import VerificationRequest
from core.models import User

from .notify import AccountDeleted, AccountWarning, ListingsUnpublished, Reactivated, ReportUpdated, Suspended

logger = logging.getLogger(__name__)


# =========================================================
# OVERVIEW
# =========================================================

class SidebarBadges:
    """The sidebar's red counts. Kept for a minute so switching pages doesn't
    ask the database again; any admin decision clears it (forget())."""

    KEY = "core_admin:badges"
    TIMEOUT = 60

    @property
    def counts(self):
        counts = cache.get(self.KEY)
        if counts is None:
            counts = {
                "verification": VerificationRequest.objects.waiting().count(),
                "reports": Report.objects.open().count(),
            }
            cache.set(self.KEY, counts, self.TIMEOUT)
        return counts

    @classmethod
    def forget(cls):
        cache.delete(cls.KEY)


class ActivityChart:
    """Per day for the last `days` days: new users, new listings, reports filed."""

    PERIODS = (7, 30, 90)
    DEFAULT = 30

    def __init__(self, days=DEFAULT):
        self.days = days
        self.start = timezone.localdate() - timedelta(days=days - 1)

    @classmethod
    def from_param(cls, value):
        """?days=7|30|90 (anything else: 30)."""
        try:
            days = int(value if value is not None else cls.DEFAULT)
        except ValueError:
            days = cls.DEFAULT
        return cls(days if days in cls.PERIODS else cls.DEFAULT)

    def _per_day(self, queryset, field):
        counts = Counter(
            timezone.localtime(value).date()
            for value in queryset.filter(**{f"{field}__date__gte": self.start}).values_list(field, flat=True)
        )
        return [counts.get(self.start + timedelta(days=i), 0) for i in range(self.days)]

    def data(self):
        users = User.objects.filter(role__in=("renter", "landlord"))
        return {
            "dates": [(self.start + timedelta(days=i)).isoformat() for i in range(self.days)],
            "series": [
                {"key": "users", "label": "New users", "values": self._per_day(users, "date_joined")},
                {"key": "listings", "label": "New listings",
                 "values": self._per_day(Complex.objects.all(), "created_at")},
                {"key": "reports", "label": "Reports filed", "values": self._per_day(Report.objects.all(), "created_at")},
            ],
        }


class Overview:
    """The Overview tab: totals, what's waiting, and the activity chart."""

    def __init__(self, badges):
        self.badges = badges

    def _stats(self):
        week_ago = timezone.now() - timedelta(days=7)
        counts = User.objects.filter(role__in=("renter", "landlord")).aggregate(
            renters=Count("pk", filter=Q(role="renter")),
            landlords=Count("pk", filter=Q(role="landlord")),
            verified=Count("pk", filter=Q(role="landlord", is_verified=True)),
            new_week=Count("pk", filter=Q(date_joined__gte=week_ago)),
            suspended=Count("pk", filter=Q(is_active=False, suspended_at__isnull=False)),
        )
        return {
            **counts,
            "to_verify": self.badges["verification"],
            "open_reports": self.badges["reports"],
            "active_listings": Complex.objects.filter(status=Complex.ComplexStatus.ACTIVE).count(),
            "active_tenancies": Tenancy.objects.filter(status=Tenancy.Status.ACTIVE).count(),
        }

    def context(self):
        return {
            "stats": self._stats(),
            "waiting_verifications": VerificationRequest.objects.waiting()
                                     .select_related("landlord__user").order_by("created_at")[:5],
            "waiting_reports": Report.objects.open()
                               .select_related("reporter", "reported_user").order_by("created_at")[:5],
            "chart_periods": ActivityChart.PERIODS,
            "chart_data": ActivityChart().data(),     # in the page, so the chart draws without a second request
        }


# =========================================================
# VERIFICATION
# =========================================================

class VerificationDecision:
    """An admin's decision on one VerificationRequest: approve | resubmit | reject
    (reject also takes back an approval)."""

    # Ready-made reasons (admins can also write their own)
    RESUBMIT_REASONS = [
        "Your ID photo is blurry or cut off. Please retake it in good light with all four corners showing.",
        "Your selfie is too dark or doesn't clearly show you holding your ID.",
        "The name on your documents doesn't match your account name.",
        "Your ID is expired. Please upload a valid government ID.",
        "Your proof of ownership is unreadable or isn't one of the accepted documents.",
    ]
    REJECT_REASONS = [
        "The documents appear to be edited or fake.",
        "The documents belong to someone else.",
        "Repeated invalid submissions.",
    ]

    def __init__(self, request, admin):
        self.request = request
        self.admin = admin

    def make(self, action, reason):
        SidebarBadges.forget()
        reason = (reason or "").strip()
        if action == "approve":
            self.request.approve(self.admin)
        elif action in ("resubmit", "reject"):
            if not reason:
                raise ValidationError("Write or pick a reason; the landlord will see it.")
            (self.request.ask_resubmit if action == "resubmit" else self.request.reject)(self.admin, reason)
        else:
            raise ValidationError("Pick a decision.")


# =========================================================
# USERS
# =========================================================

class UserModeration:
    """What an admin can do to one renter or landlord account."""

    def __init__(self, user):
        self.user = user

    def profile(self):
        """What the user's page shows about them."""
        user = self.user
        context = {
            "reports_filed": Report.objects.filter(reporter=user).select_related("reported_user")[:20],
            "reports_received": Report.objects.filter(reported_user=user).select_related("reporter")[:20],
            "listings": [], "verifications": [],
            "tenancies": Tenancy.objects.filter(
                Q(renter__user=user) | Q(unit__complex__landlord__user=user)
            ).select_related("unit__complex", "renter__user").order_by("-start_date")[:20],
            "applications_count": Application.objects.filter(renter__user=user).count(),
        }
        if user.is_landlord and hasattr(user, "landlord"):
            context["listings"] = (Complex.objects.filter(landlord=user.landlord)
                                   .annotate(units_count=Count("units")).order_by("-created_at"))
            context["verifications"] = user.landlord.verification_requests.all()
        return context

    def _check_can_moderate(self):
        if self.user.role not in ("renter", "landlord"):
            raise ValidationError("Admin accounts can't be suspended here.")

    @staticmethod
    def _required(text, error):
        text = (text or "").strip()
        if not text:
            raise ValidationError(error)
        return text

    @transaction.atomic
    def suspend(self, reason):
        self._check_can_moderate()
        reason = self._required(reason, "Write the reason; the user will see it in the email.")
        user = self.user
        user.is_active = False
        user.suspended_at = timezone.now()
        user.suspension_reason = reason
        user.save(update_fields=["is_active", "suspended_at", "suspension_reason"])
        Suspended(user, reason).send()

    @transaction.atomic
    def reactivate(self):
        user = self.user
        user.is_active = True
        user.suspended_at = None
        user.suspension_reason = ""
        user.save(update_fields=["is_active", "suspended_at", "suspension_reason"])
        Reactivated(user).send()

    def warn(self, message):
        self._check_can_moderate()
        message = self._required(message, "Write the warning message.")
        AccountWarning(self.user, message).send()

    @transaction.atomic
    def unpublish_listings(self, reason):
        if not self.user.is_landlord:
            raise ValidationError("Only landlords have listings.")
        reason = self._required(reason, "Write the reason; the landlord will see it.")
        count = Complex.objects.filter(landlord__user=self.user, status=Complex.ComplexStatus.ACTIVE).update(
            status=Complex.ComplexStatus.UNPUBLISHED, updated_at=timezone.now())
        ListingsUnpublished(self.user, reason).send()
        return count

    def send_password_help(self):
        """Email the steps to reset their password (the code itself comes from Forgot Password)."""
        from core.core_accounts.emails import send_email
        if not self.user.email:
            raise ValidationError("This user has no email address.")
        return send_email(
            self.user, "LookApt: resetting your password",
            ["Our team was asked to help you get back into your LookApt account.",
             "Open the link below, enter your email and phone number, and we'll send you a code to choose a new password."],
            button=("Reset my password", "/forgot-password/"),
        )

    # ---------------------------------------------------------- deleting

    def _files_deleted_with(self):
        """Every uploaded file (photos, videos, chat attachments, report evidence,
        verification documents ...) on the rows that deleting this user removes."""
        collector = Collector(using=router.db_for_write(User))
        collector.collect([self.user])
        groups = [(model, list(rows)) for model, rows in collector.data.items()]
        groups += [(qs.model, list(qs)) for qs in collector.fast_deletes]
        files = []
        for model, rows in groups:
            fields = [f for f in model._meta.concrete_fields if isinstance(f, models.FileField)]
            for row in rows:
                files += [(file.storage, file.name) for file in (getattr(row, f.name) for f in fields) if file]
        return files

    @staticmethod
    def _delete_files(files):
        for storage, name in files:
            try:
                storage.delete(name)
            except Exception:
                logger.exception("Couldn't delete %s", name)

    @transaction.atomic
    def delete_account(self, confirm, requested):
        """Delete an account and everything linked to it, only when its owner asked
        (Terms: users request deletion by email). The landlord's own tenancy records
        keep the tenant's name; everything else of theirs goes."""
        user = self.user
        if user.role not in ("renter", "landlord"):
            raise ValidationError("Admin accounts can't be deleted here.")
        if not requested:
            raise ValidationError("Only delete an account when its owner asked for it.")
        if (confirm or "").strip().lower() != user.username.lower():
            raise ValidationError(f"Type the username ({user.username}) to confirm.")
        files = self._files_deleted_with()
        name = user.display_name
        AccountDeleted(user).send()
        user.delete()
        transaction.on_commit(lambda: self._delete_files(files))
        transaction.on_commit(SidebarBadges.forget)
        logger.info("Account %s deleted at the owner's request", name)
        return name


# =========================================================
# REPORTS
# =========================================================

class ReportModeration:
    """An admin handling one report."""

    def __init__(self, report, admin):
        self.report = report
        self.admin = admin

    @transaction.atomic
    def set_status(self, status, note=""):
        if status not in Report.Status.values:
            raise ValidationError("Pick a status.")
        note = (note or "").strip()
        if status in (Report.Status.RESOLVED, Report.Status.DISMISSED) and not note:
            raise ValidationError("Write a short note for the person who filed the report.")
        SidebarBadges.forget()
        report = self.report
        report.status = status
        report.admin_note = note or report.admin_note
        report.handled_by = self.admin
        report.handled_at = timezone.now()
        report.save()
        ReportUpdated(report).send()
