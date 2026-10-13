# core_inquiries/views.py
# JSON endpoints used by the listing pages' pop-ups and the Inquiries tab.
import json
from datetime import date, time

from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.views import View

from core.core_accounts.mixins import LandlordRequiredMixin, RenterRequiredMixin
from core.core_listings.models import Complex, Unit
from core.models import Renter

from . import workflow
from .models import Application, Conversation
from .services import ApplicationRequest, ChatJSON, Inbox, LandlordMessage, RenterInquiry, ThreadReply


class JsonViewMixin:
    """Reading the posted JSON and answering with JSON errors (shared by every endpoint here
    and by core_calendar)."""

    def payload(self):
        try:
            return json.loads(self.request.body or "{}")
        except ValueError:
            return {}

    @staticmethod
    def parse_date(value):
        try:
            return date.fromisoformat(value) if value else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def parse_time(value):
        try:
            return time.fromisoformat(value) if value else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def errors(error):
        """ValidationError -> {"errors": {field: message}} with status 400."""
        messages = {field: " ".join(errs) for field, errs in error.message_dict.items()}
        return JsonResponse({"errors": messages}, status=400)

    @staticmethod
    def forbidden(error):
        return JsonResponse({"errors": {"__all__": str(error)}}, status=403)


class InquiryViewMixin(JsonViewMixin):
    """Helpers for the renter's Apply / Inquire pop-ups and every chat box."""

    @staticmethod
    def renter_units():
        """Units a renter may apply to or ask about (published, in a visible complex)."""
        return (
            Unit.objects
            .exclude(availability=Unit.Availability.UNPUBLISHED)
            .filter(complex__in=Complex.objects.renter_visible())
            .select_related("complex__landlord__user")
        )

    def application_fields(self, data):
        """The Apply / Edit Application form's values."""
        return {
            "occupants": data.get("occupants"),
            "move_in_date": self.parse_date(data.get("move_in_date")),
            "site_visit_date": self.parse_date(data.get("site_visit_date")),
            "site_visit_time": self.parse_time(data.get("site_visit_time")),
        }

    def message_input(self):
        """Body + optional file. The pop-ups send multipart (FormData) when a file
        is attached, JSON otherwise."""
        request = self.request
        if request.content_type.startswith("multipart/"):
            return request.POST, request.POST.get("body", ""), request.FILES.get("attachment")
        data = self.payload()
        return data, data.get("body", ""), None

    def inquiry_target(self, params):
        """The unit or complex a renter is asking about (unit=… or complex=…)."""
        if params.get("unit"):
            return get_object_or_404(self.renter_units(), pk=params["unit"]), None
        if params.get("complex"):
            return None, get_object_or_404(Complex.objects.renter_visible(), pk=params["complex"])
        raise ValidationError({"__all__": "Pick a unit or a property."})

    def chat(self):
        return ChatJSON(self.request.user)


# =========================================================
# APPLY / JOIN WAITLIST
# =========================================================

class SubmitApplicationView(RenterRequiredMixin, InquiryViewMixin, View):

    def post(self, request, unit_pk):
        unit = get_object_or_404(self.renter_units(), pk=unit_pk)
        data = self.payload()

        request_class = ApplicationRequest.class_for(data.get("kind"))
        if request_class is None:
            return JsonResponse({"errors": {"__all__": "Unknown application type."}}, status=400)

        try:
            application = request_class(request.user, unit, **self.application_fields(data)).submit()
        except ValidationError as error:
            return self.errors(error)

        return JsonResponse({
            "id": str(application.pk),
            "message": f"Your {request_class.noun} for {unit.unit_name} was sent to the landlord.",
        }, status=201)


# =========================================================
# MESSAGES
# =========================================================

class InquiryThreadView(RenterRequiredMixin, InquiryViewMixin, View):
    """Renter opens the "Inquire" pop-up: their thread with this listing's landlord (if any)."""

    def get(self, request):
        try:
            unit, complex_obj = self.inquiry_target(request.GET)
        except ValidationError as error:
            return self.errors(error)

        landlord = (unit.complex if unit else complex_obj).landlord
        conversation = RenterInquiry.thread_with(request.user, landlord)
        if conversation is None:
            return JsonResponse({"conversation": None})

        conversation.mark_read(request.user)
        return JsonResponse({"conversation": self.chat().conversation(conversation)})


class SendInquiryView(RenterRequiredMixin, InquiryViewMixin, View):
    """Renter sends a message from the pop-up (creates the thread on the first message)."""

    def post(self, request):
        params, body, attachment = self.message_input()
        try:
            unit, complex_obj = self.inquiry_target(params)
            message = RenterInquiry(request.user, unit=unit, complex_obj=complex_obj).send(body, attachment)
        except ValidationError as error:
            return self.errors(error)

        conversation = message.conversation
        return JsonResponse({
            "conversation_id": str(conversation.pk),
            "detail_url": reverse("core_inquiries:conversation_detail", args=[conversation.pk]),
            "reply_url": reverse("core_inquiries:conversation_reply", args=[conversation.pk]),
            "message": self.chat().message(message),
        }, status=201)


class ConversationDetailView(LoginRequiredMixin, InquiryViewMixin, View):
    """Open (or refresh) a thread. ?after=<id> returns only newer messages.
    ?seen=0 means the tab is in the background: don't mark messages as seen."""

    def get(self, request, pk):
        conversation = get_object_or_404(
            Conversation.objects.for_user(request.user).select_related("renter__user", "landlord__user", "complex", "unit"),
            pk=pk,
        )
        if request.GET.get("seen") != "0":
            conversation.mark_read(request.user)
        return JsonResponse({"conversation": self.chat().conversation(conversation, after=self.after())})

    def after(self):
        try:
            return int(self.request.GET.get("after") or 0) or None
        except ValueError:
            return None


class ConversationReplyView(LoginRequiredMixin, InquiryViewMixin, View):
    """Reply in a thread. Landlords can only reply after the renter wrote first."""

    def post(self, request, pk):
        conversation = get_object_or_404(Conversation.objects.for_user(request.user), pk=pk)
        _, body, attachment = self.message_input()
        try:
            message = ThreadReply(request.user, conversation).send(body, attachment)
        except PermissionDenied as error:
            return self.forbidden(error)
        except ValidationError as error:
            return self.errors(error)

        return JsonResponse({"message": self.chat().message(message)}, status=201)


class InboxView(LoginRequiredMixin, View):
    """Thread list for the Inquiries tab's live refresh."""

    def get(self, request):
        return JsonResponse(Inbox(request.user).to_json())


# =========================================================
# LANDLORD → TENANT (Manage Rentals "Message" button)
# =========================================================

class RenterThreadView(LandlordRequiredMixin, InquiryViewMixin, View):
    """The landlord's thread with a renter (if any), and whether they may write."""

    def get(self, request):
        renter = get_object_or_404(Renter.objects.select_related("user"), pk=request.GET.get("renter"))
        conversation = LandlordMessage.thread_with(request.user, renter)
        allowed = (Conversation.landlord_can_contact(request.user, renter)
                   or bool(conversation and conversation.can_send(request.user)))
        if conversation is None:
            return JsonResponse({"conversation": None, "can_send": allowed})
        conversation.mark_read(request.user)
        return JsonResponse({"conversation": self.chat().conversation(conversation), "can_send": allowed})


class SendToRenterView(LandlordRequiredMixin, InquiryViewMixin, View):

    def post(self, request):
        params, body, attachment = self.message_input()
        renter = get_object_or_404(Renter, pk=params.get("renter"))
        try:
            conversation = LandlordMessage.thread_with(request.user, renter)
            if conversation is not None:
                message = ThreadReply(request.user, conversation).send(body, attachment)
            else:
                message = LandlordMessage(request.user, renter).send(body, attachment)
        except PermissionDenied as error:
            return self.forbidden(error)
        except ValidationError as error:
            return self.errors(error)

        conversation = message.conversation
        return JsonResponse({
            "conversation_id": str(conversation.pk),
            "detail_url": reverse("core_inquiries:conversation_detail", args=[conversation.pk]),
            "message": self.chat().message(message),
        }, status=201)


# =========================================================
# PENDING REQUESTS / WAITLIST (Inquiries tab)
# "Approve as Tenant" posts to core_rentals:assign_tenant (same as Manage Rentals).
# =========================================================

class RequestActionView(InquiryViewMixin, View):
    """POST one button of a request card. Subclasses name the RequestAction to run
    and which requests the user may touch (their own, or the ones to their units)."""

    action_class = None

    def own_requests(self):
        raise NotImplementedError

    def get_application(self, pk):
        return get_object_or_404(self.own_requests(), pk=pk)

    def post(self, request, pk):
        action = self.action_class(self.get_application(pk), request.user, self.payload())
        try:
            action.run()
        except ValidationError as error:
            return self.errors(error)
        return JsonResponse({"message": action.success_message})


class LandlordRequestView(LandlordRequiredMixin, RequestActionView):

    def own_requests(self):
        return Application.objects.with_parties().for_landlord(self.request.user)


class RenterRequestView(RenterRequiredMixin, RequestActionView):

    def own_requests(self):
        return Application.objects.with_parties().for_renter(self.request.user)


class RejectRequestView(LandlordRequestView):
    action_class = workflow.RejectRequest


class ApproveWaitlistView(LandlordRequestView):
    action_class = workflow.ApproveWaitlist


class NotifyApplicantView(LandlordRequestView):
    action_class = workflow.NotifyApplicant


class SiteVisitDecisionView(LandlordRequestView):
    action_class = workflow.DecideSiteVisit


class CancelRequestView(RenterRequestView):
    action_class = workflow.CancelRequest


class EditRequestView(RenterRequestView):
    """"Edit Application": the same checks as a new application (ApplicationRequest.update)."""

    def post(self, request, pk):
        application = self.get_application(pk)
        form = ApplicationRequest.class_for(application.kind)(
            request.user, application.unit, **self.application_fields(self.payload()),
        )
        try:
            form.update(application)
        except ValidationError as error:
            return self.errors(error)
        return JsonResponse({"message": f"Your application for {application.unit.unit_name} was updated."})
