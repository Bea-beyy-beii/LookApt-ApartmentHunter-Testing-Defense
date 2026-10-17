"""
Landlord verification.

    1. The landlord uploads an ID, a selfie holding it, and a business permit or
       proof of ownership (dashboard pop-up -> LandlordVerification.submit()).
    2. Claude reads them in the background (DocumentCheck, extractors/ai_reader.py).
    3. AIVerdict: every check clear -> approved right away; a bad photo or the
       wrong document -> the landlord uploads again; anything else -> an admin
       decides (admin panel or Django admin).

Approved landlords get User.is_verified (the "verified" badge renters see) and
can publish listings.
"""
import logging
import threading
from datetime import timedelta
from functools import cached_property

from django.core.cache import cache
from django.db import close_old_connections, transaction
from django.utils import timezone

from .extractors import ai_reader
from .models import VerificationRequest

logger = logging.getLogger(__name__)

Status = VerificationRequest.Status

NOT_VERIFIED_TO_POST = "Verify your account first: you can post bulletins and file reports once you're approved."


# ------------------------------------------------------------------ one landlord

class LandlordVerification:
    """Where one user stands with verification (works for any role: renters
    are never asked to verify)."""

    def __init__(self, user):
        self.user = user

    @cached_property
    def latest(self):
        return self.user.landlord.verification_requests.first()

    @property
    def state(self):
        """none | checking | review | resubmit | rejected | approved"""
        if self.user.is_verified:
            return "approved"
        latest = self.latest
        if latest is None or latest.status == Status.APPROVED:     # approval taken back by an admin
            return "none"
        latest.expire_stale_check()
        return latest.status

    @property
    def can_submit(self):
        return self.state in ("none", Status.RESUBMIT)

    @property
    def can_publish(self):
        """Only verified landlords can make listings visible to renters."""
        return self.user.is_verified

    @property
    def must_verify(self):
        """True for landlords who aren't verified yet (they can't post bulletins or file reports)."""
        return self.user.is_landlord and not self.user.is_verified

    @property
    def show_welcome(self):
        """The one-time "you're verified" pop-up."""
        latest = self.latest
        return self.state == "approved" and latest is not None and latest.status == Status.APPROVED \
            and not latest.welcome_seen

    def submit(self, form):
        """Save the documents and start Claude's check once the save is committed."""
        request = form.save(commit=False)
        request.landlord = self.user.landlord
        request.save()
        transaction.on_commit(lambda: DocumentCheck.start(request.pk))
        return request

    def mark_welcome_seen(self):
        if self.latest and self.latest.status == Status.APPROVED:
            self.latest.mark_welcome_seen()


# ------------------------------------------------------------------ Claude's check

class AIVerdict:
    """Claude's reading -> (status, message for the landlord).
    Auto-approve only when Claude says "pass" AND every single check agrees."""

    # (document, key, label for admins, the good answer)
    CHECKS = [
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

    def __init__(self, result):
        self.result = result or {}

    def _answer(self, section, key):
        return (self.result.get(section) or {}).get(key)

    @property
    def all_clear(self):
        return self.result.get("verdict") == "pass" and all(
            self._answer(section, key) is good for section, key, _, good in self.CHECKS)

    @property
    def status(self):
        if self.result.get("verdict") == "resubmit":
            return Status.RESUBMIT
        return Status.APPROVED if self.all_clear else Status.REVIEW

    @property
    def message(self):
        if self.status == Status.RESUBMIT:
            return self.result.get("message_for_landlord") or VerificationRequest.RESUBMIT_DEFAULT
        return ""

    def decide(self):
        return self.status, self.message

    @property
    def rows(self):
        """For the admin panel: each check as ✅ / ❌ (ok=None when Claude didn't say)."""
        if not self.result:
            return []
        rows = []
        for section, key, label, good in self.CHECKS:
            value = self._answer(section, key)
            rows.append({"label": label, "ok": None if value is None else value is good})
        return rows


class DocumentCheck:
    """Claude's check of one request, run in a background thread
    (reading three documents takes longer than a page load should)."""

    def __init__(self, request_pk):
        self.request_pk = request_pk

    @classmethod
    def start(cls, request_pk):
        threading.Thread(target=cls(request_pk)._run_in_thread, daemon=True).start()

    def _run_in_thread(self):
        close_old_connections()
        try:
            self.run()
        finally:
            close_old_connections()       # this thread's own database connection

    def run(self):
        if self._check():
            self._tell_admins()

    def _check(self):
        """Claude reads the documents and decides; False if there was nothing to check."""
        try:
            request = VerificationRequest.objects.select_related("landlord__user").get(pk=self.request_pk)
            if request.status != Status.CHECKING:
                return False
            try:
                result = ai_reader.AIReader(request).read()
            except ai_reader.AIReadError as e:
                logger.warning("Verification %s goes to admin review: %s", self.request_pk, e)
                request.send_to_review(f"No automatic check: {e}")
                return True
            request.apply_result(AIVerdict(result))
        except Exception:
            logger.exception("Verification check %s failed", self.request_pk)
            VerificationRequest.objects.filter(pk=self.request_pk, status=Status.CHECKING).update(
                status=Status.REVIEW, ai_summary="The automatic check failed. Please review by hand.")
        return True

    def _tell_admins(self):
        """Bell + email to the admins: what the landlord sent and what Claude decided."""
        from core.core_admin.notify import DocumentsChecked       # core_admin imports this app
        request = VerificationRequest.objects.select_related("landlord__user").filter(pk=self.request_pk).first()
        if request:
            DocumentsChecked.send_to_admins(request)


# ------------------------------------------------------------------ deleting old documents

class DocumentPurge:
    """Privacy Notice: documents from a rejected request, or ones the landlord had
    to replace, are deleted RETENTION after the decision (approved ones stay
    while the account exists)."""

    RETENTION = timedelta(days=90)
    CACHE_KEY = "core_verification:purge"

    def run(self):
        """Delete the old files; the request rows stay, so a rejection still counts.
        Returns how many requests were cleaned."""
        old = VerificationRequest.objects.documents_older_than(timezone.now() - self.RETENTION)
        count = 0
        for request in old:
            request.delete_documents()
            count += 1
        return count

    def run_daily(self):
        """run() at most once a day (no cron job needed)."""
        if cache.add(self.CACHE_KEY, True, timeout=24 * 60 * 60):
            try:
                self.run()
            except Exception:
                logger.exception("Purging old verification documents failed")
