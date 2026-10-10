from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_POST

from core.core_accounts.decorators import role_required

from . import services
from .forms import VerificationForm


@role_required("landlord")
@require_POST
def submit(request):
    """The verification pop-up's Submit. {"ok": true} or {"ok": false, "errors": {field: message}}."""
    if not services.can_submit(request.user):
        return JsonResponse({"ok": False, "errors": {"__all__": "Your documents were already submitted."}}, status=400)
    form = VerificationForm(request.POST, request.FILES)
    if not form.is_valid():
        errors = {field: messages[0] for field, messages in form.errors.items()}
        return JsonResponse({"ok": False, "errors": errors}, status=400)
    services.submit(request.user.landlord, form)
    return JsonResponse({"ok": True, "state": "checking"})


@role_required("landlord")
@require_GET
def status(request):
    """The banner asks every few seconds while the documents are being checked."""
    return JsonResponse({"state": services.state_for(request.user)})


@role_required("landlord")
@require_POST
def welcome_seen(request):
    services.mark_welcome_seen(request.user)
    return JsonResponse({"ok": True})
