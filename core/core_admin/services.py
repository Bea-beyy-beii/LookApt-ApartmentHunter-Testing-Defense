"""
The admin panel (/admin-panel/): data for each page, and the actions admins take.

    Overview      overview_context()
    Verification  verification_queue(), decide_verification()
    Users         user_list(), user_profile(), suspend(), reactivate(), delete_account(), ...
    Reports       report_list(), set_report_status(), warn(), unpublish_listings()

Every decision tells the user through core_admin/notify.py (bell + email).
"""
import logging
from collections import Counter
from datetime import timedelta

from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import models, router, transaction
from django.db.models import Count, Q
from django.db.models.deletion import Collector
from django.utils import timezone

from core.core_inquiries.models import Application
from core.core_listings.models import Complex
from core.core_rentals.models import Tenancy
from core.core_reports.models import Report
from core.core_verification import services as verification
from core.core_verification.models import VerificationRequest
from core.models import User

from . import notify

logger = logging.getLogger(__name__)

PAGE_SIZE = 25
VStatus = VerificationRequest.Status
RStatus = Report.Status

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

CHART_PERIODS = (7, 30, 90)


def _page(queryset, number):
    return Paginator(queryset, PAGE_SIZE).get_page(number)


# =========================================================
# OVERVIEW
# =========================================================

BADGES_KEY = "core_admin:badges"


def badge_counts():
    """The sidebar's red counts. Kept for a minute so switching pages doesn't
    ask the database again; any admin decision clears it (forget_badges)."""
    counts = cache.get(BADGES_KEY)
    if counts is None:
        counts = {
            "verification": VerificationRequest.objects.filter(status=VStatus.REVIEW).count(),
            "reports": Report.objects.filter(status__in=Report.OPEN_STATUSES).count(),
        }
        cache.set(BADGES_KEY, counts, 60)
    return counts


def forget_badges():
    cache.delete(BADGES_KEY)


def activity_series(days):
    """Per day for the last `days` days: new users, new listings, reports filed."""
    today = timezone.localdate()
    start = today - timedelta(days=days - 1)

    def per_day(queryset, field):
        counts = Counter(
            timezone.localtime(value).date()
            for value in queryset.filter(**{f"{field}__date__gte": start}).values_list(field, flat=True)
        )
        return [counts.get(start + timedelta(days=i), 0) for i in range(days)]

    users = User.objects.filter(role__in=("renter", "landlord"))
    return {
        "dates": [(start + timedelta(days=i)).isoformat() for i in range(days)],
        "series": [
            {"key": "users", "label": "New users", "values": per_day(users, "date_joined")},
            {"key": "listings", "label": "New listings", "values": per_day(Complex.objects.all(), "created_at")},
            {"key": "reports", "label": "Reports filed", "values": per_day(Report.objects.all(), "created_at")},
        ],
    }


def overview_context():
    badges = badge_counts()
    week_ago = timezone.now() - timedelta(days=7)
    users = User.objects.filter(role__in=("renter", "landlord"))
    counts = users.aggregate(
        renters=Count("pk", filter=Q(role="renter")),
        landlords=Count("pk", filter=Q(role="landlord")),
        verified=Count("pk", filter=Q(role="landlord", is_verified=True)),
        new_week=Count("pk", filter=Q(date_joined__gte=week_ago)),
        suspended=Count("pk", filter=Q(is_active=False, suspended_at__isnull=False)),
    )
    return {
        "stats": {
            **counts,
            "to_verify": badges["verification"],
            "open_reports": badges["reports"],
            "active_listings": Complex.objects.filter(status=Complex.ComplexStatus.ACTIVE).count(),
            "active_tenancies": Tenancy.objects.filter(status=Tenancy.Status.ACTIVE).count(),
        },
        "waiting_verifications": VerificationRequest.objects.filter(status=VStatus.REVIEW)
                                 .select_related("landlord__user").order_by("created_at")[:5],
        "waiting_reports": Report.objects.filter(status__in=Report.OPEN_STATUSES)
                           .select_related("reporter", "reported_user").order_by("created_at")[:5],
        "chart_periods": CHART_PERIODS,
        "chart_data": activity_series(30),     # in the page, so the chart draws without a second request
    }


# =========================================================
# VERIFICATION
# =========================================================

VERIFICATION_TABS = [
    (VStatus.REVIEW, "Needs review"), (VStatus.CHECKING, "Checking"), (VStatus.RESUBMIT, "Asked to resubmit"),
    (VStatus.APPROVED, "Approved"), (VStatus.REJECTED, "Rejected"),
]


def verification_queue(status, query, page):
    counts = dict(VerificationRequest.objects.values_list("status").annotate(n=Count("pk")))
    requests = VerificationRequest.objects.select_related("landlord__user").filter(status=status)
    if query:
        requests = requests.filter(
            Q(landlord__user__first_name__icontains=query) | Q(landlord__user__last_name__icontains=query)
            | Q(landlord__user__email__icontains=query) | Q(landlord__user__phone_number__icontains=query)
        )
    # Oldest first while waiting, newest first once decided
    order = "created_at" if status in (VStatus.REVIEW, VStatus.CHECKING) else "-created_at"
    return {
        "tabs": [{"value": v, "label": label, "count": counts.get(v, 0)} for v, label in VERIFICATION_TABS],
        "page": _page(requests.order_by(order), page),
    }


AI_CHECKS = [
    ("government_id", "readable", "ID is readable", True),
    ("government_id", "is_government_id", "It's a government ID", True),
    ("government_id", "name_matches_account", "Name on ID matches the account", True),
    ("government_id", "is_expired", "ID isn't expired", False),
    ("government_id", "signs_of_editing", "No signs of editing on the ID", False),
    ("selfie", "readable", "Selfie is clear", True),
    ("selfie", "shows_person_holding_id", "Selfie shows a person holding an ID", True),
    ("ownership_document", "readable", "Ownership document is readable", True),
    ("ownership_document", "matches_claimed_type", "Document is the type they picked", True),
    ("ownership_document", "name_matches_account", "Name on document matches the account", True),
    ("ownership_document", "signs_of_editing", "No signs of editing on the document", False),
]


def ai_checks(result):
    """Claude's reading as ✅ / ❌ rows (ok=None when it didn't say)."""
    if not result:
        return []
    rows = []
    for section, key, label, good in AI_CHECKS:
        value = (result.get(section) or {}).get(key)
        rows.append({"label": label, "ok": None if value is None else value is good})
    return rows


def decide_verification(request, admin, action, reason):
    """action: approve | resubmit | reject (also takes back an approval)."""
    forget_badges()
    reason = (reason or "").strip()
    if action == "approve":
        verification.approve(request, admin)
    elif action in ("resubmit", "reject"):
        if not reason:
            raise ValidationError("Write or pick a reason; the landlord will see it.")
        (verification.ask_resubmit if action == "resubmit" else verification.reject)(request, admin, reason)
    else:
        raise ValidationError("Pick a decision.")


# =========================================================
# USERS
# =========================================================

JOINED_OPTIONS = [
    ("", "Joined any time"), ("today", "Joined today"), ("7", "Last 7 days"), ("30", "Last 30 days"),
    ("90", "Last 90 days"), ("year", "This year"), ("custom", "Custom dates…"),
]


def _date(value):
    from datetime import date
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


def joined_filter(users, joined, joined_from="", joined_to=""):
    """Date joined: a preset (today / 7 / 30 / 90 days / this year) or custom from–to dates."""
    today = timezone.localdate()
    if joined == "today":
        return users.filter(date_joined__date=today)
    if joined in ("7", "30", "90"):
        return users.filter(date_joined__date__gt=today - timedelta(days=int(joined)))
    if joined == "year":
        return users.filter(date_joined__year=today.year)
    if joined == "custom":
        start, end = _date(joined_from), _date(joined_to)
        if start:
            users = users.filter(date_joined__date__gte=start)
        if end:
            users = users.filter(date_joined__date__lte=end)
    return users


def user_list(role, status, query, page, joined="", joined_from="", joined_to=""):
    users = User.objects.exclude(role="admin").order_by("-date_joined")
    users = joined_filter(users, joined, joined_from, joined_to)
    if role in ("renter", "landlord"):
        users = users.filter(role=role)
    if status == "active":
        users = users.filter(is_active=True)
    elif status == "suspended":
        users = users.filter(is_active=False)
    if query:
        users = users.filter(
            Q(first_name__icontains=query) | Q(last_name__icontains=query) | Q(email__icontains=query)
            | Q(phone_number__icontains=query) | Q(username__icontains=query)
        )
    users = users.annotate(reports_count=Count("reports_received", distinct=True))
    return _page(users, page)


def user_profile(user):
    context = {
        "reports_filed": Report.objects.filter(reporter=user).select_related("reported_user")[:20],
        "reports_received": Report.objects.filter(reported_user=user).select_related("reporter")[:20],
        "listings": [], "verifications": [],
        "tenancies": Tenancy.objects.filter(
            Q(renter__user=user) | Q(unit__complex__landlord__user=user)
        ).select_related("unit__complex", "renter__user").order_by("-start_date")[:20],
        "applications_count": Application.objects.filter(renter__user=user).count(),
    }
    if user.role == "landlord" and hasattr(user, "landlord"):
        context["listings"] = (Complex.objects.filter(landlord=user.landlord)
                               .annotate(units_count=Count("units")).order_by("-created_at"))
        context["verifications"] = user.landlord.verification_requests.all()
    return context


def _check_can_moderate(user):
    if user.role not in ("renter", "landlord"):
        raise ValidationError("Admin accounts can't be suspended here.")


@transaction.atomic
def suspend(user, reason):
    _check_can_moderate(user)
    reason = (reason or "").strip()
    if not reason:
        raise ValidationError("Write the reason; the user will see it in the email.")
    user.is_active = False
    user.suspended_at = timezone.now()
    user.suspension_reason = reason
    user.save(update_fields=["is_active", "suspended_at", "suspension_reason"])
    notify.suspended(user, reason)


@transaction.atomic
def reactivate(user):
    user.is_active = True
    user.suspended_at = None
    user.suspension_reason = ""
    user.save(update_fields=["is_active", "suspended_at", "suspension_reason"])
    notify.reactivated(user)


def _files_deleted_with(user):
    """Every uploaded file (photos, videos, chat attachments, report evidence,
    verification documents ...) on the rows that deleting this user removes."""
    collector = Collector(using=router.db_for_write(User))
    collector.collect([user])
    groups = [(model, list(rows)) for model, rows in collector.data.items()]
    groups += [(qs.model, list(qs)) for qs in collector.fast_deletes]
    files = []
    for model, rows in groups:
        fields = [f for f in model._meta.concrete_fields if isinstance(f, models.FileField)]
        for row in rows:
            files += [(file.storage, file.name) for file in (getattr(row, f.name) for f in fields) if file]
    return files


def _delete_files(files):
    for storage, name in files:
        try:
            storage.delete(name)
        except Exception:
            logger.exception("Couldn't delete %s", name)


@transaction.atomic
def delete_account(user, confirm, requested):
    """Delete an account and everything linked to it, only when its owner asked
    (Terms: users request deletion by email). The landlord's own tenancy records
    keep the tenant's name; everything else of theirs goes."""
    if user.role not in ("renter", "landlord"):
        raise ValidationError("Admin accounts can't be deleted here.")
    if not requested:
        raise ValidationError("Only delete an account when its owner asked for it.")
    if (confirm or "").strip().lower() != user.username.lower():
        raise ValidationError(f"Type the username ({user.username}) to confirm.")
    files = _files_deleted_with(user)
    name = user.display_name
    notify.account_deleted(user)
    user.delete()
    transaction.on_commit(lambda: _delete_files(files))
    transaction.on_commit(forget_badges)
    logger.info("Account %s deleted at the owner's request", name)
    return name


def send_password_help(user):
    """Email the steps to reset their password (the code itself comes from Forgot Password)."""
    from core.core_accounts.emails import NoticeEmail
    if not user.email:
        raise ValidationError("This user has no email address.")
    return NoticeEmail(
        user, "LookApt: resetting your password",
        ["Our team was asked to help you get back into your LookApt account.",
         "Open the link below, enter your email and phone number, and we'll send you a code to choose a new password."],
        button=("Reset my password", "/forgot-password/"),
    ).send()


# =========================================================
# REPORTS
# =========================================================

REPORT_TABS = [
    (RStatus.WAITING, "Pending"), (RStatus.REVIEWING, "Under review"),
    (RStatus.RESOLVED, "Resolved"), (RStatus.DISMISSED, "Closed"),
]


def repeat_counts(user_ids):
    """How many reports each of these users has received (for the ⚠ repeat flag)."""
    return dict(Report.objects.filter(reported_user_id__in=user_ids)
                .values_list("reported_user_id").annotate(n=Count("pk")))


def report_list(status, category, query, page):
    counts = dict(Report.objects.values_list("status").annotate(n=Count("pk")))
    reports = Report.objects.select_related("reporter", "reported_user")
    if status in RStatus.values:
        reports = reports.filter(status=status)
    if category:
        reports = reports.filter(category=category)
    if query:
        reports = reports.filter(
            Q(reporter__first_name__icontains=query) | Q(reporter__last_name__icontains=query)
            | Q(reported_user__first_name__icontains=query) | Q(reported_user__last_name__icontains=query)
            | Q(description__icontains=query)
        )
    order = "created_at" if status in Report.OPEN_STATUSES else "-created_at"
    page_obj = _page(reports.order_by(order), page)
    repeats = repeat_counts([r.reported_user_id for r in page_obj])
    for report in page_obj:
        report.repeat_count = repeats.get(report.reported_user_id, 0)
    return {
        "tabs": [{"value": v, "label": label, "count": counts.get(v, 0)} for v, label in REPORT_TABS],
        "page": page_obj,
    }


@transaction.atomic
def set_report_status(report, admin, status, note=""):
    if status not in RStatus.values:
        raise ValidationError("Pick a status.")
    note = (note or "").strip()
    if status in (RStatus.RESOLVED, RStatus.DISMISSED) and not note:
        raise ValidationError("Write a short note for the person who filed the report.")
    forget_badges()
    report.status = status
    report.admin_note = note or report.admin_note
    report.handled_by = admin
    report.handled_at = timezone.now()
    report.save()
    notify.report_updated(report)


def warn(user, message):
    _check_can_moderate(user)
    message = (message or "").strip()
    if not message:
        raise ValidationError("Write the warning message.")
    notify.warning(user, message)


@transaction.atomic
def unpublish_listings(user, reason):
    if user.role != "landlord":
        raise ValidationError("Only landlords have listings.")
    reason = (reason or "").strip()
    if not reason:
        raise ValidationError("Write the reason; the landlord will see it.")
    count = Complex.objects.filter(landlord__user=user, status=Complex.ComplexStatus.ACTIVE).update(
        status=Complex.ComplexStatus.UNPUBLISHED, updated_at=timezone.now())
    notify.unpublished_by_admin(user, reason)
    return count