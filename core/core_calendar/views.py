# core_calendar/views.py
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.views import View
from django.views.generic import TemplateView

from core.core_accounts.mixins import LandlordRequiredMixin
from core.core_inquiries.views import JsonViewMixin
from core.core_verification.services import NOT_VERIFIED_TO_POST, LandlordVerification

from .services import Bulletin, Calendar


class CalendarPageView(TemplateView):
    template_name = "core_calendar/calendar.html"


class EventsApiView(LoginRequiredMixin, JsonViewMixin, View):
    """Calendar items between ?start= and ?end= (YYYY-MM-DD), for the logged-in user."""

    def get(self, request):
        start, end = self.parse_date(request.GET.get("start")), self.parse_date(request.GET.get("end"))
        if not start or not end or end < start:
            return JsonResponse({"errors": {"__all__": "Give a start and end date."}}, status=400)
        return JsonResponse({"items": Calendar.for_user(request.user, start, end).items()})


class PostBulletinView(LandlordRequiredMixin, JsonViewMixin, View):

    def post(self, request):
        if LandlordVerification(request.user).must_verify:
            return JsonResponse({"errors": {"__all__": NOT_VERIFIED_TO_POST}}, status=403)
        data = self.payload()

        complex_ids = None if data.get("audience") != "some" else [str(pk) for pk in data.get("complexes") or []]
        bulletin = Bulletin(
            request.user,
            message=data.get("message"),
            complex_ids=complex_ids,
            event_date=self.parse_date(data.get("event_date")),
            start_time=self.parse_time(data.get("start_time")),
            end_time=self.parse_time(data.get("end_time")),
            event_title=data.get("event_title", ""),
            event_type=data.get("event_type") or "announcement",
            whole_week=bool(data.get("whole_week")),
        )
        try:
            bulletin.post()
        except ValidationError as error:
            return self.errors(error)
        return JsonResponse({"message": bulletin.summary}, status=201)
