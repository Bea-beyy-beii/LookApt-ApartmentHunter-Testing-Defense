"""
Landlord verification.

    1. The landlord uploads an ID, a selfie holding it, and a business permit or
       proof of ownership (dashboard pop-up -> views.submit).
    2. Claude reads them in the background (extractors/ai_reader.py).
    3. decide(): every check clear -> approved right away; a bad photo or the
       wrong document -> the landlord uploads again; anything else -> an admin
       decides in Django admin (/lookapt-manage/, "Verification requests").

Approved landlords get User.is_verified (the "verified" badge renters see) and
can publish listings.
"""
import logging
import threading
from datetime import timedelta

from django.db import close_old_connections, transaction
from django.utils import timezone

from .extractors import ai_reader
from .forms import MAX_FILE_MB, VerificationForm
from .models import VerificationRequest

logger = logging.getLogger(__name__)

Status = VerificationRequest.Status

# A check still "running" after this long was lost (e.g. the server restarted): an admin takes over
STALE_CHECK = timedelta(minutes=10)

RESUBMIT_DEFAULT = "We couldn't read one of your documents. Please upload clear photos with all four corners showing."


# ------------------------------------------------------------------ state

def latest_request(landlord):
    return landlord.verification_requests.first()


def state_for(user):
    """none | checking | review | resubmit | rejected | approved"""
    if user.is_verified:
        return "approved"
    latest = latest_request(user.landlord)
    if latest is None or latest.status == Status.APPROVED:     # approval taken back by an admin
        return "none"
    if latest.status == Status.CHECKING and latest.created_at < timezone.now() - STALE_CHECK:
        latest.status = Status.REVIEW
        latest.ai_summary = "The automatic check didn't finish. Please review by hand."
        latest.save(update_fields=["status", "ai_summary"])
    return latest.status


def can_submit(user):
    return state_for(user) in ("none", Status.RESUBMIT)


def can_publish(user):
    """Only verified landlords can make listings visible to renters."""
    return user.is_verified


def verification_context(user):
    """For the landlord dashboard: the pop-up, the banner and the welcome message."""
    state = state_for(user)
    latest = latest_request(user.landlord)
    return {
        "verification": {
            "state": state,
            "request": latest,
            "can_submit": state in ("none", Status.RESUBMIT),
            "show_welcome": state == "approved" and latest is not None
                            and latest.status == Status.APPROVED and not latest.welcome_seen,
        },
        "verification_form": VerificationForm(),
        "verification_max_mb": MAX_FILE_MB,
    }


# ------------------------------------------------------------------ submitting

def submit(landlord, form):
    """Save the documents and start Claude's check once the save is committed."""
    request = form.save(commit=False)
    request.landlord = landlord
    request.save()
    transaction.on_commit(lambda: start_check(request.pk))
    return request


def start_check(request_pk):
    # In the background: reading three documents takes longer than a page load should
    threading.Thread(target=_run_in_thread, args=(request_pk,), daemon=True).start()


def _run_in_thread(request_pk):
    close_old_connections()
    try:
        run_check(request_pk)
    finally:
        close_old_connections()       # this thread's own database connection


def run_check(request_pk):
    try:
        request = VerificationRequest.objects.select_related("landlord__user").get(pk=request_pk)
        if request.status != Status.CHECKING:
            return
        try:
            result = ai_reader.read_documents(request)
        except ai_reader.AIReadError as e:
            logger.warning("Verification %s goes to admin review: %s", request_pk, e)
            request.status = Status.REVIEW
            request.ai_summary = f"No automatic check: {e}"
            request.save(update_fields=["status", "ai_summary"])
            return
        apply_result(request, result)
    except Exception:
        logger.exception("Verification check %s failed", request_pk)
        VerificationRequest.objects.filter(pk=request_pk, status=Status.CHECKING).update(
            status=Status.REVIEW, ai_summary="The automatic check failed. Please review by hand.")


def decide(result):
    """Claude's reading -> (status, message for the landlord).
    Auto-approve only when Claude says "pass" AND every single check agrees."""
    if result.get("verdict") == "resubmit":
        return Status.RESUBMIT, result.get("message_for_landlord") or RESUBMIT_DEFAULT

    gov_id = result.get("government_id") or {}
    selfie = result.get("selfie") or {}
    ownership = result.get("ownership_document") or {}
    all_clear = (
        result.get("verdict") == "pass"
        and gov_id.get("readable") is True and gov_id.get("is_government_id") is True
        and gov_id.get("name_matches_account") is True
        and gov_id.get("is_expired") is False and gov_id.get("signs_of_editing") is False
        and selfie.get("readable") is True and selfie.get("shows_person_holding_id") is True
        and ownership.get("readable") is True and ownership.get("matches_claimed_type") is True
        and ownership.get("name_matches_account") is True and ownership.get("signs_of_editing") is False
    )
    return (Status.APPROVED if all_clear else Status.REVIEW), ""


@transaction.atomic
def apply_result(request, result):
    status, message = decide(result)
    request.ai_result = result
    request.ai_summary = result.get("summary", "")
    if status == Status.APPROVED:
        _decide(request, Status.APPROVED, reviewer=None)
    else:
        request.status = status
        request.message = message
        request.save(update_fields=["status", "message", "ai_result", "ai_summary"])


# ------------------------------------------------------------------ admin decisions

def _decide(request, status, reviewer, message=""):
    request.status = status
    request.message = message
    request.reviewed_by = reviewer
    request.decided_at = timezone.now()
    request.save()
    user = request.landlord.user
    user.is_verified = status == Status.APPROVED
    user.save(update_fields=["is_verified"])


@transaction.atomic
def approve(request, reviewer):
    _decide(request, Status.APPROVED, reviewer)


@transaction.atomic
def ask_resubmit(request, reviewer, message):
    _decide(request, Status.RESUBMIT, reviewer, message or RESUBMIT_DEFAULT)


@transaction.atomic
def reject(request, reviewer, message):
    _decide(request, Status.REJECTED, reviewer, message)


def mark_welcome_seen(user):
    latest = latest_request(user.landlord)
    if latest and latest.status == Status.APPROVED:
        latest.welcome_seen = True
        latest.save(update_fields=["welcome_seen"])
