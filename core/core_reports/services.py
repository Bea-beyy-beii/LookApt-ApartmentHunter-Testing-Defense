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
from abc import ABC, abstractmethod

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q

from core.core_inquiries.models import Application, Conversation
from core.core_listings.models import Complex
from core.core_rentals.models import Tenancy
from core.models import User
from core.roles import RoleBased

from .models import LANDLORD_CATEGORIES, RENTER_CATEGORIES, Report, ReportEvidence

SUPPORT_EMAIL = "lookapt.support@gmail.com"     # every "Contact Support" link and email uses this


class EvidenceFile:
    """One uploaded evidence file: checks its type, size and real content."""

    MAX_MB = 10
    # extension -> kind
    TYPES = {
        ".jpg": "image", ".jpeg": "image", ".png": "image", ".webp": "image",
        ".mp4": "video", ".mov": "video", ".webm": "video",
        ".pdf": "document", ".docx": "document",
    }
    # extension -> how the file's first bytes must look
    SIGNATURES = {
        ".jpg": lambda head: head[:3] == b"\xff\xd8\xff", ".jpeg": lambda head: head[:3] == b"\xff\xd8\xff",
        ".png": lambda head: head[:8] == b"\x89PNG\r\n\x1a\n",
        ".webp": lambda head: head[:4] == b"RIFF" and head[8:12] == b"WEBP",
        ".mp4": lambda head: head[4:8] == b"ftyp",
        ".mov": lambda head: head[4:8] in (b"ftyp", b"moov", b"wide", b"mdat"),
        ".webm": lambda head: head[:4] == b"\x1a\x45\xdf\xa3",
        ".pdf": lambda head: head[:5] == b"%PDF-", ".docx": lambda head: head[:4] == b"PK\x03\x04",
    }

    def __init__(self, upload):
        self.upload = upload
        self.ext = os.path.splitext(upload.name)[1].lower()

    def check(self):
        """The file's kind (image / video / document), or ValidationError."""
        name = self.upload.name
        kind = self.TYPES.get(self.ext)
        if not kind:
            raise ValidationError({"evidence": f"{name}: use photos (JPG, PNG, WEBP), videos (MP4, MOV, WEBM) or documents (PDF, DOCX)."})
        if self.upload.size > self.MAX_MB * 1024 * 1024:
            raise ValidationError({"evidence": f"{name} is larger than {self.MAX_MB} MB."})

        # Check the content too, not just the name (a renamed .exe must not pass)
        head = self.upload.read(12)
        self.upload.seek(0)
        if not self.SIGNATURES[self.ext](head):
            raise ValidationError({"evidence": f"{name} doesn't look like a real {self.ext[1:].upper()} file."})
        return kind


class Reporter(RoleBased, ABC):
    """A user filing reports. Polymorphism: renters and landlords pick from
    different reasons and may report different people (RenterReporter /
    LandlordReporter); for_user() picks the class."""

    MAX_DESCRIPTION = 500
    MAX_OTHER = 200
    MAX_FILES = 5

    categories = ()       # (value, label) reasons this side can pick
    target = ""           # who they report: "landlord" / "renter"

    def __init__(self, user):
        self.user = user

    @classmethod
    def for_user(cls, user):
        return cls.class_for(user)(user)

    @staticmethod
    def _initials(user):
        return f"{user.first_name[:1]}{user.last_name[:1]}".upper() or "?"

    # ---------------------------------------------------------- who can be reported

    @abstractmethod
    def _links(self):
        """(person, detail) for everyone this user has a link to."""

    def reportable_people(self):
        """[{id, name, initials, avatar, role, detail, verified}] the user may report, sorted by name."""
        people = {}
        for person, detail in self._links():
            if person.pk == self.user.pk:
                continue
            entry = people.setdefault(person.pk, {
                "id": str(person.pk), "name": person.display_name, "initials": self._initials(person),
                "avatar": person.avatar_url, "role": person.role,
                "verified": person.is_verified, "details": [],
            })
            if detail and detail not in entry["details"]:
                entry["details"].append(detail)

        result = []
        for entry in people.values():
            details = entry.pop("details")
            entry["detail"] = details[0] + (f" (+{len(details) - 1} more)" if len(details) > 1 else "") if details else ""
            entry["search"] = f"{entry['name']} {' '.join(details)}".lower()
            result.append(entry)
        return sorted(result, key=lambda p: p["name"].lower())

    # ---------------------------------------------------------- filing a report

    def _clean_reported(self, reported_id):
        allowed = {p["id"] for p in self.reportable_people()}
        if not reported_id or str(reported_id) not in allowed:
            raise ValidationError({"reported_user": f"Pick the {self.target} you want to report."})
        return User.objects.get(pk=reported_id)

    def _clean_category(self, category, other_text):
        if category not in dict(self.categories):
            raise ValidationError({"category": "Pick a reason for reporting."})
        other_text = (other_text or "").strip()
        if category != "others":
            return ""
        if not other_text:
            raise ValidationError({"other_category_text": "Tell us the reason in a few words."})
        if len(other_text) > self.MAX_OTHER:
            raise ValidationError({"other_category_text": f"Keep it under {self.MAX_OTHER} characters."})
        return other_text

    def _clean_description(self, description):
        description = (description or "").strip()
        if not description:
            raise ValidationError({"description": "Describe what happened."})
        if len(description) > self.MAX_DESCRIPTION:
            raise ValidationError({"description": f"Keep it under {self.MAX_DESCRIPTION} characters."})
        return description

    def _clean_files(self, files):
        files = list(files)
        if len(files) > self.MAX_FILES:
            raise ValidationError({"evidence": f"You can attach up to {self.MAX_FILES} files."})
        return [(upload, EvidenceFile(upload).check()) for upload in files]

    @transaction.atomic
    def file_report(self, reported_id, category, description, other_text="", files=()):
        """Validate and save a report. Raises ValidationError({field: message})."""
        reported = self._clean_reported(reported_id)
        other_text = self._clean_category(category, other_text)
        description = self._clean_description(description)
        evidence = self._clean_files(files)

        duplicate = Report.objects.open().filter(reporter=self.user, reported_user=reported, category=category)
        if duplicate.exists():
            raise ValidationError({"__all__": f"You already have an open report about {reported.display_name} for this reason. We'll update you on that one."})

        report = Report.objects.create(
            reporter=self.user, reported_user=reported, category=category,
            other_category_text=other_text, description=description,
        )
        for upload, kind in evidence:
            ReportEvidence.from_upload(report, upload, kind)
        return report

    # ---------------------------------------------------------- the Reports Filed tab

    def reports(self):
        """Their reports, newest first, with what the page shows about the other person."""
        reports = list(
            Report.objects.filter(reporter=self.user)
            .select_related("reported_user")
            .prefetch_related("evidence")
            .order_by("-created_at")
        )
        for report in reports:
            other = report.reported_user
            report.other_name = other.display_name
            report.other_initials = self._initials(other)
            report.other_avatar = other.avatar_url
            report.other_role_key = other.role
            report.other_role = other.get_role_display()
        return reports


class RenterReporter(Reporter):
    ROLE = "renter"
    categories = RENTER_CATEGORIES
    target = "landlord"

    def _links(self):
        # Every landlord with a visible listing...
        complexes = (
            Complex.objects.renter_visible().select_related("landlord__user").prefetch_related("units")
            .order_by("complex_name")
        )
        # ...plus landlords they've dealt with (even if the listing is gone now)
        dealt = Complex.objects.filter(
            Q(units__applications__renter__user=self.user)
            | Q(units__tenancies__renter__user=self.user)
            | Q(conversations__renter__user=self.user)
        ).select_related("landlord__user").prefetch_related("units").distinct()
        for complex_obj in [*complexes, *dealt]:
            units = len(complex_obj.units.all())
            yield complex_obj.landlord.user, f"{complex_obj.complex_name} · {units} unit{'s' if units != 1 else ''}"


class LandlordReporter(Reporter):
    ROLE = "landlord"
    categories = LANDLORD_CATEGORIES
    target = "renter"

    def _links(self):
        mine = Q(unit__complex__landlord__user=self.user)
        for t in Tenancy.objects.filter(mine, renter__isnull=False).select_related("renter__user", "unit__complex"):
            word = "Tenant" if t.is_active else "Former tenant"
            yield t.renter.user, f"{word} · {t.unit.unit_name}, {t.unit.complex.complex_name}"
        for a in Application.objects.filter(mine).select_related("renter__user", "unit__complex"):
            yield a.renter.user, f"Applied · {a.unit.unit_name}, {a.unit.complex.complex_name}"
        for c in Conversation.objects.filter(landlord__user=self.user).select_related("renter__user", "complex"):
            yield c.renter.user, f"Messaged you · {c.complex.complex_name}"
