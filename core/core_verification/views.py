"""The landlord's side of verification: the pop-up's Submit, the banner's polling, the welcome pop-up."""
from functools import cached_property

from django.http import JsonResponse
from django.views import View

from core.core_accounts.mixins import LandlordRequiredMixin

from .forms import VerificationForm
from .services import LandlordVerification


class VerificationView(LandlordRequiredMixin, View):
    """Base view: landlords only, with their LandlordVerification at hand."""

    @cached_property
    def verification(self):
        return LandlordVerification(self.request.user)


class SubmitView(VerificationView):
    """The verification pop-up's Submit. {"ok": true} or {"ok": false, "errors": {field: message}}."""

    def post(self, request):
        if not self.verification.can_submit:
            return JsonResponse({"ok": False, "errors": {"__all__": "Your documents were already submitted."}},
                                status=400)
        form = VerificationForm(request.POST, request.FILES)
        if not form.is_valid():
            errors = {field: messages[0] for field, messages in form.errors.items()}
            return JsonResponse({"ok": False, "errors": errors}, status=400)
        self.verification.submit(form)
        return JsonResponse({"ok": True, "state": "checking"})


class StatusView(VerificationView):
    """The banner asks every few seconds while the documents are being checked."""

    def get(self, request):
        return JsonResponse({"state": self.verification.state})


class WelcomeSeenView(VerificationView):

    def post(self, request):
        self.verification.mark_welcome_seen()
        return JsonResponse({"ok": True})
