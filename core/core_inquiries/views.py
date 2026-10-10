# core_inquiries/views.py
# JSON endpoints used by the listing pages' pop-ups and the Inquiries tab.
import json
from datetime import date, time

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ObjectDoesNotExist, PermissionDenied, ValidationError
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from core.core_accounts.decorators import role_required
from core.core_listings.services import renter_visible_complexes

from core.models import Renter

from . import services, workflow
from .models import Application


def _payload(request):
    try:
        return json.loads(request.body or "{}")
    except ValueError:
        return {}


def _date(value):
    try:
        return date.fromisoformat(value) if value else None
    except (TypeError, ValueError):
        return None


def _time(value):
    try:
        return time.fromisoformat(value) if value else None
    except (TypeError, ValueError):
        return None


def _errors(error):
    """ValidationError -> {"errors": {field: message}} with status 400."""
    messages = {field: " ".join(errs) for field, errs in error.message_dict.items()}
    return JsonResponse({"errors": messages}, status=400)


# =========================================================
# APPLY / JOIN WAITLIST
# =========================================================

@role_required("renter")
@require_POST
def submit_application(request, unit_pk):
    unit = get_object_or_404(services.renter_units(), pk=unit_pk)
    data = _payload(request)

    kind = data.get("kind")
    if kind not in Application.Kind.values:
        return JsonResponse({"errors": {"__all__": "Unknown application type."}}, status=400)

    try:
        application = services.create_application(
            request.user, unit, kind,
            occupants=data.get("occupants"),
            move_in_date=_date(data.get("move_in_date")),
            site_visit_date=_date(data.get("site_visit_date")),
            site_visit_time=_time(data.get("site_visit_time")),
        )
    except ValidationError as error:
        return _errors(error)

    noun = "waitlist application" if kind == Application.Kind.WAITLIST else "application"
    return JsonResponse({
        "id": str(application.pk),
        "message": f"Your {noun} for {unit.unit_name} was sent to the landlord.",
    }, status=201)


# =========================================================
# MESSAGES
# =========================================================

def _message_input(request):
    """Body + optional file. The pop-ups send multipart (FormData) when a file
    is attached, JSON otherwise."""
    if request.content_type.startswith("multipart/"):
        return request.POST, request.POST.get("body", ""), request.FILES.get("attachment")
    data = _payload(request)
    return data, data.get("body", ""), None


def _inquiry_target(params):
    """The unit or complex a renter is asking about (unit=… or complex=…)."""
    if params.get("unit"):
        return get_object_or_404(services.renter_units(), pk=params["unit"]), None
    if params.get("complex"):
        return None, get_object_or_404(renter_visible_complexes(), pk=params["complex"])
    raise ValidationError({"__all__": "Pick a unit or a property."})


def _after(request):
    try:
        return int(request.GET.get("after") or 0) or None
    except ValueError:
        return None


@role_required("renter")
@require_GET
def inquiry_thread(request):
    """Renter opens the "Inquire" pop-up: their thread with this listing's landlord (if any)."""
    try:
        unit, complex_obj = _inquiry_target(request.GET)
    except ValidationError as error:
        return _errors(error)

    landlord = (unit.complex if unit else complex_obj).landlord
    conversation = services.renter_conversation(request.user, landlord)
    if conversation is None:
        return JsonResponse({"conversation": None})

    services.mark_read(request.user, conversation)
    return JsonResponse({"conversation": services.conversation_json(request.user, conversation)})


@role_required("renter")
@require_POST
def send_inquiry(request):
    """Renter sends a message from the pop-up (creates the thread on the first message)."""
    params, body, attachment = _message_input(request)
    try:
        unit, complex_obj = _inquiry_target(params)
        message = services.start_or_continue_inquiry(
            request.user, body, unit=unit, complex_obj=complex_obj, attachment=attachment,
        )
    except ValidationError as error:
        return _errors(error)

    conversation = message.conversation
    return JsonResponse({
        "conversation_id": str(conversation.pk),
        "detail_url": reverse("core_inquiries:conversation_detail", args=[conversation.pk]),
        "reply_url": reverse("core_inquiries:conversation_reply", args=[conversation.pk]),
        "message": services.message_json(request.user, message),
    }, status=201)


@login_required
@require_GET
def conversation_detail(request, pk):
    """Open (or refresh) a thread. ?after=<id> returns only newer messages.
    ?seen=0 means the tab is in the background: don't mark messages as seen."""
    conversation = get_object_or_404(
        services.user_conversations(request.user).select_related("renter__user", "landlord__user", "complex", "unit"),
        pk=pk,
    )
    if request.GET.get("seen") != "0":
        services.mark_read(request.user, conversation)
    return JsonResponse({"conversation": services.conversation_json(request.user, conversation, after=_after(request))})


@login_required
@require_POST
def conversation_reply(request, pk):
    """Reply in a thread. Landlords can only reply after the renter wrote first."""
    conversation = get_object_or_404(services.user_conversations(request.user), pk=pk)
    _, body, attachment = _message_input(request)
    try:
        message = services.reply(request.user, conversation, body, attachment)
    except PermissionDenied as error:
        return JsonResponse({"errors": {"__all__": str(error)}}, status=403)
    except ValidationError as error:
        return _errors(error)

    return JsonResponse({"message": services.message_json(request.user, message)}, status=201)


@login_required
@require_GET
def inbox(request):
    """Thread list for the Inquiries tab's live refresh."""
    return JsonResponse(services.inbox_json(request.user))



# =========================================================
# LANDLORD → TENANT (Manage Rentals "Message" button)
# =========================================================

@role_required("landlord")
@require_GET
def renter_thread(request):
    """The landlord's thread with a renter (if any), and whether they may write."""
    renter = get_object_or_404(Renter.objects.select_related("user"), pk=request.GET.get("renter"))
    conversation = services.landlord_conversation(request.user, renter)
    allowed = services.landlord_can_contact(request.user, renter) or bool(conversation and services.can_send(request.user, conversation))
    if conversation is None:
        return JsonResponse({"conversation": None, "can_send": allowed})
    services.mark_read(request.user, conversation)
    return JsonResponse({"conversation": services.conversation_json(request.user, conversation), "can_send": allowed})


@role_required("landlord")
@require_POST
def send_to_renter(request):
    params, body, attachment = _message_input(request)
    renter = get_object_or_404(Renter, pk=params.get("renter"))
    try:
        conversation = services.landlord_conversation(request.user, renter)
        if conversation is not None:
            message = services.reply(request.user, conversation, body, attachment)
        else:
            message = services.start_landlord_message(request.user, renter, body, attachment)
    except PermissionDenied as error:
        return JsonResponse({"errors": {"__all__": str(error)}}, status=403)
    except ValidationError as error:
        return _errors(error)

    conversation = message.conversation
    return JsonResponse({
        "conversation_id": str(conversation.pk),
        "detail_url": reverse("core_inquiries:conversation_detail", args=[conversation.pk]),
        "message": services.message_json(request.user, message),
    }, status=201)



# =========================================================
# PENDING REQUESTS / WAITLIST (Inquiries tab)
# "Approve as Tenant" posts to core_rentals:assign_tenant (same as Manage Rentals).
# =========================================================

def _own(lookup, request, pk):
    try:
        return lookup(request.user, pk)
    except ObjectDoesNotExist:
        raise Http404


def _done(message):
    return JsonResponse({"message": message})


@role_required("landlord")
@require_POST
def reject_request(request, pk):
    application = _own(workflow.landlord_application, request, pk)
    data = _payload(request)
    was_waitlisted = application.status == Application.Status.WAITLISTED
    try:
        workflow.reject(application, data.get("reason"), data.get("reason_note"))
    except ValidationError as error:
        return _errors(error)
    action = "removed from the waitlist" if was_waitlisted else "rejected"
    return _done(f"{application.renter.user.display_name}'s request was {action} and moved to the Archive.")


@role_required("landlord")
@require_POST
def approve_waitlist(request, pk):
    application = _own(workflow.landlord_application, request, pk)
    try:
        workflow.approve_waitlist(application)
    except ValidationError as error:
        return _errors(error)
    return _done(f"{application.renter.user.display_name} is now on the waitlist for {application.unit.unit_name}.")


@role_required("landlord")
@require_POST
def notify_applicant(request, pk):
    application = _own(workflow.landlord_application, request, pk)
    try:
        workflow.notify_applicant(request.user, application)
    except ValidationError as error:
        return _errors(error)
    return _done(f"{application.renter.user.display_name} was notified that {application.unit.unit_name} is available.")


@role_required("landlord")
@require_POST
def site_visit_decision(request, pk):
    application = _own(workflow.landlord_application, request, pk)
    try:
        workflow.decide_site_visit(application, _payload(request).get("decision"))
    except ValidationError as error:
        return _errors(error)
    word = application.get_site_visit_status_display().lower()
    return _done(f"Site visit {word} for {application.renter.user.display_name} ({workflow.visit_label(application)}).")


@role_required("renter")
@require_POST
def cancel_request(request, pk):
    application = _own(workflow.renter_application, request, pk)
    data = _payload(request)
    try:
        workflow.cancel(application, data.get("reason"), data.get("reason_note"))
    except ValidationError as error:
        return _errors(error)
    return _done(f"Your request for {application.unit.unit_name} was cancelled.")


@role_required("renter")
@require_POST
def edit_request(request, pk):
    application = _own(workflow.renter_application, request, pk)
    data = _payload(request)
    try:
        services.edit_application(
            request.user, application,
            occupants=data.get("occupants"),
            move_in_date=_date(data.get("move_in_date")),
            site_visit_date=_date(data.get("site_visit_date")),
            site_visit_time=_time(data.get("site_visit_time")),
        )
    except ValidationError as error:
        return _errors(error)
    return _done(f"Your application for {application.unit.unit_name} was updated.")