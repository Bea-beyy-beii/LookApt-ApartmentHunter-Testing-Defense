# core_admin/views.py: the admin panel (/admin-panel/). Admin accounts only.
from abc import ABC, abstractmethod

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import JsonResponse, QueryDict
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views import View

from core.core_accounts.mixins import AdminRequiredMixin
from core.core_reports.models import Report
from core.core_verification.models import VerificationRequest
from core.core_verification.services import AIVerdict, DocumentPurge
from core.models import User

from .forms import UserEditForm
from .services import (ActivityChart, Overview, ReportModeration, SidebarBadges, UserModeration,
                       VerificationDecision)
from .tabs import FeedbackTab, ReportsTab, UsersTab, VerificationTab


class AdminPanelView(AdminRequiredMixin, View):
    """Base view: admins only; every page gets the sidebar (section + badges)."""

    section = ""

    def render_page(self, template, context, section=None):
        return render(self.request, template, {"section": section or self.section,
                                               "badges": SidebarBadges().counts, **context})


# ---------------------------------------------------------------- overview

class OverviewView(AdminPanelView):
    """The admin dashboard: all five tabs in one page, switched in the browser like
    the landlord / renter dashboards. ?tab= picks the first one shown, and only
    that tab reads the filters in the address (the others start unfiltered)."""

    LIST_TABS = (VerificationTab, UsersTab, ReportsTab, FeedbackTab)
    TABS = ("overview",) + tuple(tab.name for tab in LIST_TABS)

    def get(self, request):
        tab = request.GET.get("tab") if request.GET.get("tab") in self.TABS else "overview"
        params = request.GET.copy()
        params.pop("tab", None)
        context = {"tab": tab, **Overview(SidebarBadges().counts).context()}
        for tab_class in self.LIST_TABS:
            context[tab_class.name] = tab_class(params if tab_class.name == tab else QueryDict()).context()
        return self.render_page("core_admin/dashboard.html", context, section=tab)


class ActivityDataView(AdminRequiredMixin, View):
    """The Overview chart, for ?days=7|30|90."""

    def get(self, request):
        return JsonResponse(ActivityChart.from_param(request.GET.get("days")).data())


class ListResultsView(AdminRequiredMixin, View):
    """The live filters (admin_panel.js) get only the results table; anyone else
    opening the list's address lands on that tab of the dashboard, filters kept."""

    tab_class = None

    def get(self, request):
        if request.headers.get("X-Requested-With") == "ap-live":
            return render(request, self.tab_class.results_template, self.tab_class(request.GET).context())
        params = request.GET.copy()
        params["tab"] = self.tab_class.name
        return redirect(f"{reverse('core_admin:overview')}?{params.urlencode()}")


class VerificationListView(ListResultsView):
    tab_class = VerificationTab


class UserListView(ListResultsView):
    tab_class = UsersTab


class ReportListView(ListResultsView):
    tab_class = ReportsTab


class FeedbackListView(ListResultsView):
    tab_class = FeedbackTab


# ---------------------------------------------------------------- detail pages

class AdminDetailView(AdminPanelView, ABC):
    """One item's page. GET shows it; POST runs the form's `action`, shows an
    error message if it was refused, then comes back to the page.
    Template method: subclasses fill in get_object(), show() and act()."""

    url_name = ""

    @abstractmethod
    def get_object(self):
        """The item (or 404)."""

    def get(self, request, pk):
        self.object = self.get_object()
        return self.show()

    def post(self, request, pk):
        self.object = self.get_object()
        try:
            response = self.act(request.POST.get("action"))
        except ValidationError as error:
            messages.error(request, " ".join(error.messages))
            response = None
        return response or redirect(self.url_name, pk=pk)

    @abstractmethod
    def show(self):
        """The page itself."""

    @abstractmethod
    def act(self, action):
        """Do what the admin asked; return a response, or None to come back to the page."""


class VerificationDetailView(AdminDetailView):
    section = "verification"
    url_name = "core_admin:verification_detail"

    def get_object(self):
        return get_object_or_404(VerificationRequest.objects.select_related("landlord__user", "reviewed_by"),
                                 pk=self.kwargs["pk"])

    def act(self, action):
        item = self.object
        VerificationDecision(item, self.request.user).make(action, self.request.POST.get("reason"))
        messages.success(self.request, f"Saved. {item.landlord.user.display_name} was notified.")

    def show(self):
        item = self.object
        return self.render_page("core_admin/verification_detail.html", {
            "item": item, "account": item.landlord.user,
            "checks": AIVerdict(item.ai_result).rows,
            "history": item.landlord.verification_requests.exclude(pk=item.pk),
            "resubmit_reasons": VerificationDecision.RESUBMIT_REASONS,
            "reject_reasons": VerificationDecision.REJECT_REASONS,
            "is_pdf": item.is_pdf,
            "retention_days": DocumentPurge.RETENTION.days,
        })


class UserDetailView(AdminDetailView):
    section = "users"
    url_name = "core_admin:user_detail"
    ACTIONS = ("edit", "verify", "unverify", "suspend", "reactivate", "warn", "delete", "password")

    def get_object(self):
        return get_object_or_404(User.objects.exclude(role="admin"), pk=self.kwargs["pk"])

    @property
    def moderation(self):
        return UserModeration(self.object)

    def show(self, form=None):
        account = self.object
        form = form or UserEditForm(instance=account)
        account.refresh_from_db()
        return self.render_page("core_admin/user_detail.html", {
            "account": account, "form": form, **self.moderation.profile(),
        })

    def act(self, action):
        if action not in self.ACTIONS:
            return self.show()
        return getattr(self, f"_{action}")()

    def _edit(self):
        form = UserEditForm(self.request.POST, instance=self.object)
        if form.is_valid():
            form.save()
            messages.success(self.request, "Details saved.")
            return None
        messages.error(self.request, "Please fix the details below.")
        return self.show(form)

    def _verify(self):
        self.moderation.verify(self.request.user)
        messages.success(self.request, f"{self.object.display_name} is verified and was notified.")

    def _unverify(self):
        self.moderation.remove_verification(self.request.POST.get("reason"))
        messages.success(self.request, f"{self.object.display_name}'s verification was removed and they were notified.")

    def _suspend(self):
        self.moderation.suspend(self.request.POST.get("reason"))
        messages.success(self.request, f"{self.object.display_name} was suspended and emailed.")

    def _reactivate(self):
        self.moderation.reactivate()
        messages.success(self.request, f"{self.object.display_name} can log in again.")

    def _warn(self):
        self.moderation.warn(self.request.POST.get("message"))
        messages.success(self.request, f"Warning sent to {self.object.display_name}.")

    def _delete(self):
        name = self.moderation.delete_account(self.request.POST.get("confirm"), self.request.POST.get("requested"))
        messages.success(self.request, f"{name}'s account was deleted and they were emailed.")
        return redirect(f"{reverse('core_admin:overview')}?tab=users")

    def _password(self):
        sent = self.moderation.send_password_help()
        (messages.success if sent else messages.error)(
            self.request, "Password reset steps were emailed." if sent else "The email couldn't be sent.")


class ReportDetailView(AdminDetailView):
    section = "reports"
    url_name = "core_admin:report_detail"
    ACTIONS = ("status", "warn", "suspend", "unpublish")

    def get_object(self):
        return get_object_or_404(Report.objects.select_related("reporter", "reported_user", "handled_by")
                                 .prefetch_related("evidence"), pk=self.kwargs["pk"])

    @property
    def reported(self):
        return self.object.reported_user

    def show(self):
        report, reported = self.object, self.reported
        counts = Report.objects.received_counts([report.reporter_id, reported.pk])
        return self.render_page("core_admin/report_detail.html", {
            "report": report, "reported": reported,
            "reported_count": counts.get(reported.pk, 0),
            "reporter_count": counts.get(report.reporter_id, 0),
            "other_reports": Report.objects.filter(reported_user=reported).exclude(pk=report.pk)
                             .select_related("reporter")[:10],
            "statuses": ReportsTab.status_tabs,
        })

    def act(self, action):
        if action in self.ACTIONS:
            getattr(self, f"_{action}")()

    def _status(self):
        report = self.object
        ReportModeration(report, self.request.user).set_status(self.request.POST.get("status"),
                                                                self.request.POST.get("note"))
        messages.success(self.request, f"Report marked as {report.get_status_display().lower()}. "
                                       f"{report.reporter.display_name} was notified.")

    def _warn(self):
        UserModeration(self.reported).warn(self.request.POST.get("message"))
        messages.success(self.request, f"Warning sent to {self.reported.display_name}.")

    def _suspend(self):
        UserModeration(self.reported).suspend(self.request.POST.get("reason"))
        messages.success(self.request, f"{self.reported.display_name} was suspended.")

    def _unpublish(self):
        count = UserModeration(self.reported).unpublish_listings(self.request.POST.get("reason"))
        messages.success(self.request, f"{count} listing{'s' if count != 1 else ''} unpublished.")
