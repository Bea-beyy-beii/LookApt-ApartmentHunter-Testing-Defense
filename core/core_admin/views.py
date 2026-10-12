# core_admin/views.py: the admin panel (/admin-panel/). Admin accounts only.
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import JsonResponse, QueryDict
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from core.core_accounts.decorators import role_required
from core.core_reports.models import ALL_CATEGORIES, Report
from core.core_verification.models import VerificationRequest
from core.models import User

from . import services
from .forms import UserEditForm

admin_only = role_required("admin")


def _render(request, template, section, context=None):
    return render(request, template, {"section": section, "badges": services.badge_counts(), **(context or {})})


def _list_results(request, tab, results, context):
    """The live filters (admin_panel.js) get only the results table; anyone else
    opening the list's address lands on that tab of the dashboard, filters kept."""
    if request.headers.get("X-Requested-With") == "ap-live":
        return render(request, results, context)
    params = request.GET.copy()
    params["tab"] = tab
    return redirect(f"{reverse('core_admin:overview')}?{params.urlencode()}")


# ---------------------------------------------------------------- what each tab shows

def _verification_tab(params):
    status = params.get("status") or VerificationRequest.Status.REVIEW
    query = params.get("q", "").strip()
    return {"status": status, "query": query, "params": params, "list_url": reverse("core_admin:verification_list"),
            **services.verification_queue(status, query, params.get("page"))}


def _users_tab(params):
    filters = {k: params.get(k, "") for k in ("role", "verified", "status", "joined", "joined_from", "joined_to")}
    query = params.get("q", "").strip()
    return {
        "filters": filters, "query": query, "joined_options": services.JOINED_OPTIONS,
        "params": params, "list_url": reverse("core_admin:user_list"),
        "page": services.user_list(filters["role"], filters["verified"], filters["status"], query, params.get("page"),
                                   filters["joined"], filters["joined_from"], filters["joined_to"]),
    }


def _reports_tab(params):
    status = params.get("status") or Report.Status.WAITING
    category = params.get("category", "")
    query = params.get("q", "").strip()
    return {"status": status, "category": category, "query": query, "categories": ALL_CATEGORIES,
            "params": params, "list_url": reverse("core_admin:report_list"),
            **services.report_list(status, category, query, params.get("page"))}


def _error(request, error):
    messages.error(request, " ".join(error.messages))


# ---------------------------------------------------------------- overview

TABS = ("overview", "verification", "users", "reports")


@admin_only
def overview(request):
    """The admin dashboard: all four tabs in one page, switched in the browser like
    the landlord / renter dashboards. ?tab= picks the first one shown, and only
    that tab reads the filters in the address (the others start unfiltered)."""
    tab = request.GET.get("tab") if request.GET.get("tab") in TABS else "overview"
    params = request.GET.copy()
    params.pop("tab", None)
    filters_for = lambda name: params if name == tab else QueryDict()
    return _render(request, "core_admin/dashboard.html", tab, {
        "tab": tab,
        **services.overview_context(),
        "verification": _verification_tab(filters_for("verification")),
        "users": _users_tab(filters_for("users")),
        "reports": _reports_tab(filters_for("reports")),
    })


@admin_only
@require_GET
def activity_data(request):
    """The Overview chart, for ?days=7|30|90."""
    try:
        days = int(request.GET.get("days", 30))
    except ValueError:
        days = 30
    if days not in services.CHART_PERIODS:
        days = 30
    return JsonResponse(services.activity_series(days))


# ---------------------------------------------------------------- verification

@admin_only
def verification_list(request):
    return _list_results(request, "verification", "core_admin/partials/verification_results.html",
                         _verification_tab(request.GET))


@admin_only
def verification_detail(request, pk):
    item = get_object_or_404(VerificationRequest.objects.select_related("landlord__user", "reviewed_by"), pk=pk)
    if request.method == "POST":
        try:
            services.decide_verification(item, request.user, request.POST.get("action"), request.POST.get("reason"))
        except ValidationError as error:
            _error(request, error)
            return redirect("core_admin:verification_detail", pk=pk)
        messages.success(request, f"Saved. {item.landlord.user.display_name} was notified.")
        return redirect("core_admin:verification_detail", pk=pk)

    user = item.landlord.user
    return _render(request, "core_admin/verification_detail.html", "verification", {
        "item": item, "account": user,
        "checks": services.ai_checks(item.ai_result),
        "history": item.landlord.verification_requests.exclude(pk=item.pk),
        "resubmit_reasons": services.RESUBMIT_REASONS,
        "reject_reasons": services.REJECT_REASONS,
        "is_pdf": item.ownership_document.name.lower().endswith(".pdf"),
    })


# ---------------------------------------------------------------- users

@admin_only
def user_list(request):
    return _list_results(request, "users", "core_admin/partials/user_results.html", _users_tab(request.GET))


@admin_only
def user_detail(request, pk):
    account = get_object_or_404(User.objects.exclude(role="admin"), pk=pk)
    form = UserEditForm(instance=account)

    if request.method == "POST":
        action = request.POST.get("action")
        try:
            if action == "edit":
                form = UserEditForm(request.POST, instance=account)
                if form.is_valid():
                    form.save()
                    messages.success(request, "Details saved.")
                    return redirect("core_admin:user_detail", pk=pk)
                messages.error(request, "Please fix the details below.")
            elif action == "suspend":
                services.suspend(account, request.POST.get("reason"))
                messages.success(request, f"{account.display_name} was suspended and emailed.")
                return redirect("core_admin:user_detail", pk=pk)
            elif action == "reactivate":
                services.reactivate(account)
                messages.success(request, f"{account.display_name} can log in again.")
                return redirect("core_admin:user_detail", pk=pk)
            elif action == "warn":
                services.warn(account, request.POST.get("message"))
                messages.success(request, f"Warning sent to {account.display_name}.")
                return redirect("core_admin:user_detail", pk=pk)
            elif action == "password":
                sent = services.send_password_help(account)
                (messages.success if sent else messages.error)(
                    request, "Password reset steps were emailed." if sent else "The email couldn't be sent.")
                return redirect("core_admin:user_detail", pk=pk)
        except ValidationError as error:
            _error(request, error)
            return redirect("core_admin:user_detail", pk=pk)

    account.refresh_from_db()
    return _render(request, "core_admin/user_detail.html", "users", {
        "account": account, "form": form, **services.user_profile(account),
    })


# ---------------------------------------------------------------- reports

@admin_only
def report_list(request):
    return _list_results(request, "reports", "core_admin/partials/report_results.html", _reports_tab(request.GET))


@admin_only
def report_detail(request, pk):
    report = get_object_or_404(Report.objects.select_related("reporter", "reported_user", "handled_by")
                               .prefetch_related("evidence"), pk=pk)
    reported = report.reported_user

    if request.method == "POST":
        action = request.POST.get("action")
        try:
            if action == "status":
                services.set_report_status(report, request.user, request.POST.get("status"), request.POST.get("note"))
                messages.success(request, f"Report marked as {report.get_status_display().lower()}. "
                                          f"{report.reporter.display_name} was notified.")
            elif action == "warn":
                services.warn(reported, request.POST.get("message"))
                messages.success(request, f"Warning sent to {reported.display_name}.")
            elif action == "suspend":
                services.suspend(reported, request.POST.get("reason"))
                messages.success(request, f"{reported.display_name} was suspended.")
            elif action == "unpublish":
                count = services.unpublish_listings(reported, request.POST.get("reason"))
                messages.success(request, f"{count} listing{'s' if count != 1 else ''} unpublished.")
        except ValidationError as error:
            _error(request, error)
        return redirect("core_admin:report_detail", pk=pk)

    counts = services.repeat_counts([report.reporter_id, reported.pk])
    return _render(request, "core_admin/report_detail.html", "reports", {
        "report": report, "reported": reported,
        "reported_count": counts.get(reported.pk, 0),
        "reporter_count": counts.get(report.reporter_id, 0),
        "other_reports": Report.objects.filter(reported_user=reported).exclude(pk=report.pk)
                         .select_related("reporter")[:10],
        "statuses": services.REPORT_TABS,
    })