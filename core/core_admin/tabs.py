"""
The admin panel's list tabs: Verification, Users and Reports.

Each tab reads its filters from the address (?q=, ?status=, ?page= ...) and
gives the template a page of results. ListTab holds what they share (search,
paging, the live-results address); each subclass only says what it lists and
how it filters (inheritance + polymorphism):

    VerificationTab(request.GET).context()
"""
from abc import ABC, abstractmethod
from datetime import date, timedelta

from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.urls import reverse
from django.utils import timezone

from core.core_reports.models import ALL_CATEGORIES, Report
from core.core_verification.models import VerificationRequest
from core.models import User


class ListTab(ABC):
    """One list tab of the admin dashboard."""

    PAGE_SIZE = 25
    name = ""                 # the dashboard's ?tab= value
    list_url_name = ""        # where the live filters fetch the results
    results_template = ""     # just the results table (admin_panel.js swaps it in)
    search_fields = ()        # what ?q= looks in

    def __init__(self, params):
        self.params = params
        self.query = params.get("q", "").strip()

    def _search(self, queryset):
        if not self.query:
            return queryset
        condition = Q()
        for field in self.search_fields:
            condition |= Q(**{f"{field}__icontains": self.query})
        return queryset.filter(condition)

    def _page(self, queryset):
        return Paginator(queryset, self.PAGE_SIZE).get_page(self.params.get("page"))

    def context(self):
        return {"query": self.query, "params": self.params, "list_url": reverse(self.list_url_name),
                **self._results()}

    @abstractmethod
    def _results(self):
        """The tab's own template variables (its filters and the page of results)."""


class StatusListTab(ListTab):
    """A tab split into status sub-tabs, each with a count."""

    model = None
    status_tabs = ()          # (value, label)
    default_status = ""
    waiting_statuses = ()     # oldest first while waiting, newest first once decided

    def __init__(self, params):
        super().__init__(params)
        self.status = params.get("status") or self.default_status

    def _tabs(self):
        counts = dict(self.model.objects.values_list("status").annotate(n=Count("pk")))
        return [{"value": v, "label": label, "count": counts.get(v, 0)} for v, label in self.status_tabs]

    def _ordered(self, queryset):
        return queryset.order_by("created_at" if self.status in self.waiting_statuses else "-created_at")


class VerificationTab(StatusListTab):
    name = "verification"
    list_url_name = "core_admin:verification_list"
    results_template = "core_admin/partials/verification_results.html"
    search_fields = ("landlord__user__first_name", "landlord__user__last_name", "landlord__user__email",
                     "landlord__user__phone_number")

    model = VerificationRequest
    Status = VerificationRequest.Status
    status_tabs = [
        (Status.REVIEW, "Needs review"), (Status.CHECKING, "Checking"), (Status.RESUBMIT, "Asked to resubmit"),
        (Status.APPROVED, "Approved"), (Status.REJECTED, "Rejected"),
    ]
    default_status = Status.REVIEW
    waiting_statuses = (Status.REVIEW, Status.CHECKING)

    def _results(self):
        requests = VerificationRequest.objects.select_related("landlord__user").filter(status=self.status)
        return {"status": self.status, "tabs": self._tabs(),
                "page": self._page(self._ordered(self._search(requests)))}


class ReportsTab(StatusListTab):
    name = "reports"
    list_url_name = "core_admin:report_list"
    results_template = "core_admin/partials/report_results.html"
    search_fields = ("reporter__first_name", "reporter__last_name", "reported_user__first_name",
                     "reported_user__last_name", "description")

    model = Report
    Status = Report.Status
    status_tabs = [
        (Status.WAITING, "Pending"), (Status.REVIEWING, "Under review"),
        (Status.RESOLVED, "Resolved"), (Status.DISMISSED, "Closed"),
    ]
    default_status = Status.WAITING
    waiting_statuses = Report.OPEN_STATUSES

    def __init__(self, params):
        super().__init__(params)
        self.category = params.get("category", "")

    def _results(self):
        reports = Report.objects.select_related("reporter", "reported_user")
        if self.status in self.Status.values:
            reports = reports.filter(status=self.status)
        if self.category:
            reports = reports.filter(category=self.category)
        page = self._page(self._ordered(self._search(reports)))
        repeats = Report.objects.received_counts([r.reported_user_id for r in page])
        for report in page:
            report.repeat_count = repeats.get(report.reported_user_id, 0)
        return {"status": self.status, "category": self.category, "categories": ALL_CATEGORIES,
                "tabs": self._tabs(), "page": page}


class UsersTab(ListTab):
    name = "users"
    list_url_name = "core_admin:user_list"
    results_template = "core_admin/partials/user_results.html"
    search_fields = ("first_name", "last_name", "email", "phone_number", "username")

    FILTERS = ("role", "status", "joined", "joined_from", "joined_to")
    JOINED_OPTIONS = [
        ("", "Joined any time"), ("today", "Joined today"), ("7", "Last 7 days"), ("30", "Last 30 days"),
        ("90", "Last 90 days"), ("year", "This year"), ("custom", "Custom dates…"),
    ]

    def __init__(self, params):
        super().__init__(params)
        self.filters = {k: params.get(k, "") for k in self.FILTERS}

    @staticmethod
    def _date(value):
        try:
            return date.fromisoformat(value) if value else None
        except ValueError:
            return None

    def _joined(self, users):
        """Date joined: a preset (today / 7 / 30 / 90 days / this year) or custom from–to dates."""
        joined = self.filters["joined"]
        today = timezone.localdate()
        if joined == "today":
            return users.filter(date_joined__date=today)
        if joined in ("7", "30", "90"):
            return users.filter(date_joined__date__gt=today - timedelta(days=int(joined)))
        if joined == "year":
            return users.filter(date_joined__year=today.year)
        if joined == "custom":
            start, end = self._date(self.filters["joined_from"]), self._date(self.filters["joined_to"])
            if start:
                users = users.filter(date_joined__date__gte=start)
            if end:
                users = users.filter(date_joined__date__lte=end)
        return users

    def _results(self):
        users = self._joined(User.objects.exclude(role="admin").order_by("-date_joined"))
        role, status = self.filters["role"], self.filters["status"]
        if role in ("renter", "landlord"):
            users = users.filter(role=role)
        if status == "active":
            users = users.filter(is_active=True)
        elif status == "suspended":
            users = users.filter(is_active=False)
        users = self._search(users).annotate(reports_count=Count("reports_received", distinct=True))
        return {"filters": self.filters, "joined_options": self.JOINED_OPTIONS, "page": self._page(users)}
