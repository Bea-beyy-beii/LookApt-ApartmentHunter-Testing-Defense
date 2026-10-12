# core_reports/services.py
# Reports Filed (renter + landlord dashboards).
#
# Who can be reported:
#   Renter   -> any landlord whose listings renters can see (e.g. a listing with
#               malicious content, even without an inquiry), plus landlords
#               they've dealt with before.
#   Landlord -> only renters with a real link to them: applied to one of their
#               units, messaged them, or rents / rented from them.
import os
from collections import Counter

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q

from core.core_inquiries.models import Application, Conversation
from core.core_listings.models import Complex
from core.core_listings.services import renter_visible_complexes
from core.core_rentals.models import Tenancy
from core.models import User

from .models import LANDLORD_CATEGORIES, RENTER_CATEGORIES, Report, ReportEvidence

MAX_DESCRIPTION = 500
MAX_OTHER = 200
MAX_FILES = 5
MAX_FILE_MB = 10
SUPPORT_EMAIL = "lookapt.support@gmail.com"     # every "Contact Support" link and email uses this

# extension -> kind, and how the file's first bytes must look
EVIDENCE_TYPES = {
    ".jpg": "image", ".jpeg": "image", ".png": "image", ".webp": "image",
    ".mp4": "video", ".mov": "video", ".webm": "video",
    ".pdf": "document", ".docx": "document",
}


def categories_for(user):
    return RENTER_CATEGORIES if user.role == "renter" else LANDLORD_CATEGORIES


def _initials(user):
    return f"{user.first_name[:1]}{user.last_name[:1]}".upper() or "?"


# =========================================================
# WHO CAN BE REPORTED
# =========================================================

def reportable_people(user):
    """[{id, name, initials, avatar, role, detail, verified}] the user may report, sorted by name."""
    people = {}

    def add(person, detail):
        if person.pk == user.pk:
            return
        entry = people.setdefault(person.pk, {
            "id": str(person.pk), "name": person.display_name, "initials": _initials(person),
            "avatar": person.avatar_url, "role": person.role,
            "verified": person.is_verified, "details": [],
        })
        if detail and detail not in entry["details"]:
            entry["details"].append(detail)

    if user.role == "renter":
        # Every landlord with a visible listing...
        complexes = (
            renter_visible_complexes().select_related("landlord__user").prefetch_related("units")
            .order_by("complex_name")
        )
        # ...plus landlords they've dealt with (even if the listing is gone now)
        dealt = Complex.objects.filter(
            Q(units__applications__renter__user=user)
            | Q(units__tenancies__renter__user=user)
            | Q(conversations__renter__user=user)
        ).select_related("landlord__user").prefetch_related("units").distinct()
        for complex_obj in [*complexes, *dealt]:
            units = len(complex_obj.units.all())
            add(complex_obj.landlord.user, f"{complex_obj.complex_name} · {units} unit{'s' if units != 1 else ''}")
    else:
        mine = Q(unit__complex__landlord__user=user)
        for t in Tenancy.objects.filter(mine, renter__isnull=False).select_related("renter__user", "unit__complex"):
            word = "Tenant" if t.is_active else "Former tenant"
            add(t.renter.user, f"{word} · {t.unit.unit_name}, {t.unit.complex.complex_name}")
        for a in Application.objects.filter(mine).select_related("renter__user", "unit__complex"):
            add(a.renter.user, f"Applied · {a.unit.unit_name}, {a.unit.complex.complex_name}")
        for c in Conversation.objects.filter(landlord__user=user).select_related("renter__user", "complex"):
            add(c.renter.user, f"Messaged you · {c.complex.complex_name}")

    result = []
    for entry in people.values():
        details = entry.pop("details")
        entry["detail"] = details[0] + (f" (+{len(details) - 1} more)" if len(details) > 1 else "") if details else ""
        entry["search"] = f"{entry['name']} {' '.join(details)}".lower()
        result.append(entry)
    return sorted(result, key=lambda p: p["name"].lower())


# =========================================================
# FILING A REPORT
# =========================================================

def _check_file(upload):
    ext = os.path.splitext(upload.name)[1].lower()
    kind = EVIDENCE_TYPES.get(ext)
    if not kind:
        raise ValidationError({"evidence": f"{upload.name}: use photos (JPG, PNG, WEBP), videos (MP4, MOV, WEBM) or documents (PDF, DOCX)."})
    if upload.size > MAX_FILE_MB * 1024 * 1024:
        raise ValidationError({"evidence": f"{upload.name} is larger than {MAX_FILE_MB} MB."})

    # Check the content too, not just the name (a renamed .exe must not pass)
    head = upload.read(12)
    upload.seek(0)
    ok = {
        ".jpg": head[:3] == b"\xff\xd8\xff", ".jpeg": head[:3] == b"\xff\xd8\xff",
        ".png": head[:8] == b"\x89PNG\r\n\x1a\n",
        ".webp": head[:4] == b"RIFF" and head[8:12] == b"WEBP",
        ".mp4": head[4:8] == b"ftyp", ".mov": head[4:8] in (b"ftyp", b"moov", b"wide", b"mdat"),
        ".webm": head[:4] == b"\x1a\x45\xdf\xa3",
        ".pdf": head[:5] == b"%PDF-", ".docx": head[:4] == b"PK\x03\x04",
    }[ext]
    if not ok:
        raise ValidationError({"evidence": f"{upload.name} doesn't look like a real {ext[1:].upper()} file."})
    return kind


@transaction.atomic
def file_report(user, reported_id, category, description, other_text="", files=()):
    """Validate and save a report. Raises ValidationError({field: message})."""
    allowed = {p["id"] for p in reportable_people(user)}
    if not reported_id or str(reported_id) not in allowed:
        who = "landlord" if user.role == "renter" else "renter"
        raise ValidationError({"reported_user": f"Pick the {who} you want to report."})

    if category not in dict(categories_for(user)):
        raise ValidationError({"category": "Pick a reason for reporting."})
    other_text = (other_text or "").strip()
    if category == "others":
        if not other_text:
            raise ValidationError({"other_category_text": "Tell us the reason in a few words."})
        if len(other_text) > MAX_OTHER:
            raise ValidationError({"other_category_text": f"Keep it under {MAX_OTHER} characters."})
    else:
        other_text = ""

    description = (description or "").strip()
    if not description:
        raise ValidationError({"description": "Describe what happened."})
    if len(description) > MAX_DESCRIPTION:
        raise ValidationError({"description": f"Keep it under {MAX_DESCRIPTION} characters."})

    files = list(files)
    if len(files) > MAX_FILES:
        raise ValidationError({"evidence": f"You can attach up to {MAX_FILES} files."})
    kinds = [_check_file(f) for f in files]

    reported = User.objects.get(pk=reported_id)
    duplicate = Report.objects.filter(
        reporter=user, reported_user=reported, category=category, status__in=Report.OPEN_STATUSES,
    )
    if duplicate.exists():
        raise ValidationError({"__all__": f"You already have an open report about {reported.display_name} for this reason. We'll update you on that one."})

    report = Report.objects.create(
        reporter=user, reported_user=reported, category=category,
        other_category_text=other_text, description=description,
    )
    for upload, kind in zip(files, kinds):
        ReportEvidence.objects.create(
            report=report, file=upload, name=os.path.basename(upload.name)[:255], kind=kind, size=upload.size,
        )
    return report


# =========================================================
# PAGE DATA
# =========================================================

STATUS_TABS = [
    ("waiting", "Pending", "clock"),
    ("reviewing", "Under Review", "document"),
    ("resolved", "Resolved", "check"),
    ("dismissed", "Closed", "info"),
]


def get_reports_context(user):
    reports = list(
        Report.objects.filter(reporter=user)
        .select_related("reported_user")
        .prefetch_related("evidence")
        .order_by("-created_at")
    )
    labels = dict(categories_for(user))
    for report in reports:
        other = report.reported_user
        report.other_name = other.display_name
        report.other_initials = _initials(other)
        report.other_avatar = other.avatar_url
        report.other_role_key = other.role
        report.other_role = other.get_role_display()
        report.reason = report.other_category_text if report.category == "others" and report.other_category_text \
            else labels.get(report.category, report.get_category_display())

    counts = Counter(r.status for r in reports)
    renter = user.role == "renter"
    return {
        "reports": reports,
        "report_tabs": [
            {"value": value, "label": label, "icon": icon, "count": counts.get(value, 0)}
            for value, label, icon in STATUS_TABS
        ],
        "report_people": reportable_people(user),
        "report_categories": categories_for(user),
        "report_target": "landlord" if renter else "renter",
        "report_support_email": SUPPORT_EMAIL,
        "report_max_files": MAX_FILES,
        "report_max_mb": MAX_FILE_MB,
    }