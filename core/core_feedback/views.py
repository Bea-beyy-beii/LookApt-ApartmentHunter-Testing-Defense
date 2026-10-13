from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from django.views import View

from .forms import FeedbackForm


class SubmitFeedbackView(LoginRequiredMixin, View):
    """The Feedback Form pop-up sends its answers here (feedback.js).
    Renters and landlords only; admins read the answers in the admin panel."""

    THANKS = "Your feedback was sent. Thank you!"

    def post(self, request):
        if request.user.profile is None:
            return JsonResponse({"errors": {"__all__": "Only renters and landlords can send feedback."}}, status=403)
        form = FeedbackForm(request.POST)
        if not form.is_valid():
            return JsonResponse({"errors": {name: " ".join(errors) for name, errors in form.errors.items()}}, status=400)
        form.save_for(request.user)
        return JsonResponse({"message": self.THANKS}, status=201)
