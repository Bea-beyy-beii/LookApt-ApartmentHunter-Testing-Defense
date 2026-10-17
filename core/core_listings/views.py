# core_listings/views.py
from abc import ABC, abstractmethod

from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.utils.functional import cached_property
from django.views import View
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.generic import DetailView, FormView, TemplateView

from core.core_accounts.mixins import LandlordRequiredMixin, RenterRequiredMixin
from core.core_verification.services import LandlordVerification
from core.models import Renter

from .detail_services import ComplexPage, UnitPage
from .forms import BulkUnitForm, ComplexForm, UnitForm
from .models import Complex, ListingChangeRefused, SavedListing, Unit


class MyListingsMixin:
    """Landlord pages that go back to My Listings when they're done."""

    def my_listings_url(self, saved=False):
        # The listings page lives inside the landlord dashboard.
        # saved=1 tells wizard_draft.js the submit went through, so it can drop the draft.
        url = f"{reverse('core_landlords:dashboard')}?tab=myListings"
        return url + "&saved=1" if saved else url


# =========================================================
# LANDLORD PAGES (older stand-alone pages, no role check)
# =========================================================

class ListingsView(TemplateView):
    template_name = "core_listings/landlords/listings.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        properties = Complex.objects.all()
        status = self.request.GET.get("status")
        if status:
            properties = properties.filter(status=status)
        context.update(properties=properties, current_filter=status)
        return context


class PropertyDetailView(DetailView):
    model = Complex
    context_object_name = "property"
    template_name = "core_listings/landlords/property_detail.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["active_tab"] = self.request.GET.get("tab", "overview")
        return context


class UnitDetailView(DetailView):
    model = Unit
    context_object_name = "unit"
    template_name = "core_listings/landlords/unit_detail.html"


# =========================================================
# WIZARDS (Add / Edit Property, Add / Edit Unit)
# =========================================================

class ListingWizardView(LandlordRequiredMixin, MyListingsMixin, FormView):
    """Base of the property and unit wizards (inheritance): show the form, and
    on a valid POST let the form save itself (save_listing), show its message
    and go back to My Listings. Subclasses say which listing is being edited
    (None = a new one) and what else the form and the template need."""

    extra_context = {"active_tab": "myListings"}

    @cached_property
    def listing(self):
        return self.get_listing()

    def get_listing(self):
        return None             # create pages; the edit pages override this

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["instance"] = self.listing
        return kwargs

    def save(self, form):
        return form.save_listing()

    def form_valid(self, form):
        saved = self.save(form)
        messages.success(self.request, form.success_message(saved))
        return redirect(self.my_listings_url(saved=True))


class PropertyWizardView(ListingWizardView):
    form_class = ComplexForm
    template_name = "core_listings/landlords/forms/property_form_page.html"

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["landlord"] = self.request.user.landlord
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(property=self.listing, current_step=1)
        return context

    def save(self, form):
        # Landlords who aren't verified yet can only save it unpublished
        return form.save_listing(may_publish=LandlordVerification(self.request.user).can_publish)

    def form_valid(self, form):
        response = super().form_valid(form)
        if form.publish_refused:
            messages.warning(self.request, f"It was saved as unpublished. {Complex.NOT_VERIFIED}")
        return response


class PropertyCreateView(PropertyWizardView):
    pass


class PropertyEditView(PropertyWizardView):

    def get_listing(self):
        return get_object_or_404(Complex.objects.owned_by(self.request.user), pk=self.kwargs["pk"])


class UnitWizardView(ListingWizardView, ABC):
    template_name = "core_listings/landlords/forms/unit_form.html"

    @cached_property
    def complex(self):
        return self.get_complex()

    @abstractmethod
    def get_complex(self):
        """The complex the unit belongs to."""

    @property
    def bulk(self):
        # "Bulk listing" switch (new units only): several units with the same details
        return self.listing is None and self.request.POST.get("bulk") == "1"

    def get_form_class(self):
        return BulkUnitForm if self.bulk else UnitForm

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["complex_obj"] = self.complex
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            complex=self.complex,
            unit=self.listing,
            bulk=self.bulk,
            max_bulk_units=BulkUnitForm.MAX_UNITS,
            next_identifier=self.complex.next_unit_identifier,
        )
        return context


class UnitCreateView(UnitWizardView):

    def get_complex(self):
        return get_object_or_404(Complex.objects.owned_by(self.request.user), pk=self.kwargs["property_pk"])


class UnitEditView(UnitWizardView):

    def get_listing(self):
        return get_object_or_404(Unit.objects.owned_by(self.request.user), pk=self.kwargs["pk"])

    def get_complex(self):
        return self.listing.complex


# ---------------------------------------------------------
# ⋮ MENU ACTIONS (called with fetch() from listings_cards.js)
# ---------------------------------------------------------

class ListingMenuView(LandlordRequiredMixin, MyListingsMixin, View, ABC):
    """Base of the menu actions (POST only): find the landlord's own complex or
    unit (`model`), act on it, answer JSON to fetch() or redirect otherwise."""

    model = None

    def get_listing(self):
        # owned_by(): a landlord can only touch their own listings
        return get_object_or_404(self.model.objects.owned_by(self.request.user), pk=self.kwargs["pk"])

    @property
    def wants_json(self):
        return "application/json" in self.request.headers.get("Accept", "")

    def refused(self, refusal):
        if self.wants_json:
            return JsonResponse({"error": refusal.error}, status=refusal.status)
        if refusal.flash:
            messages.error(self.request, refusal.error)
        return redirect(self.my_listings_url())

    def post(self, request, *args, **kwargs):
        listing = self.get_listing()
        try:
            payload = self.act(listing)
        except ListingChangeRefused as refusal:
            return self.refused(refusal)
        if self.wants_json:
            return JsonResponse(payload)
        self.after_redirect_action(payload)
        return redirect(self.my_listings_url())

    @abstractmethod
    def act(self, listing):
        """Do the action; returns the JSON payload."""

    def after_redirect_action(self, payload):
        """Extra step when the answer is a redirect (not JSON)."""


class ListingDeleteView(ListingMenuView):
    """Delete a complex or a unit and its files."""

    def act(self, listing):
        name = listing.listing_name
        listing.delete_with_media()
        return {"deleted": True, "name": name}


class PropertyDeleteView(ListingDeleteView):
    model = Complex


class UnitDeleteView(ListingDeleteView):
    model = Unit

    def after_redirect_action(self, payload):
        messages.success(self.request, f"{payload['name']} was deleted.")


class ListingStatusView(ListingMenuView):
    """Publish / unpublish a complex or a unit; `field` is the posted value's name."""

    field = None

    def may_publish(self):
        return True

    def act(self, listing):
        listing.set_status(self.request.POST.get(self.field), may_publish=self.may_publish())
        return listing.status_payload()


class PropertyVisibilityView(ListingStatusView):
    model = Complex
    field = "visibility"

    def may_publish(self):
        return LandlordVerification(self.request.user).can_publish


class UnitAvailabilityView(ListingStatusView):
    model = Unit
    field = "availability"


# =========================================================
# RENTERS — save / unsave a listing (the ribbon on the card)
# =========================================================

class ToggleSavedListingView(RenterRequiredMixin, View):

    def post(self, request, pk):
        complex_obj = get_object_or_404(Complex.objects.renter_visible(), pk=pk)
        renter, _ = Renter.objects.get_or_create(user=request.user)
        return JsonResponse({"saved": SavedListing.toggle(renter, complex_obj)})


# =========================================================
# RENTERS — listing pages (opened from a card or the map)
# =========================================================

class RenterListingView(RenterRequiredMixin, TemplateView):
    """Base of the renter's complex and unit pages: `page_class` (a ListingPage)
    builds the context; the first breadcrumb shows the dashboard tab the renter came from."""

    page_class = None

    # Which dashboard tab the renter came from (first breadcrumb + highlighted sidebar link)
    ORIGINS = {
        "home": "Home",
        "findNear": "Find Near",
        "saved": "Saved Listings",
    }

    @method_decorator(ensure_csrf_cookie)   # the pop-ups post with fetch(), which needs the CSRF cookie
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    @property
    def origin(self):
        origin = self.request.GET.get("from")
        return origin if origin in self.ORIGINS else "home"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        origin = self.origin
        page = self.page_class.open(self.kwargs["pk"], self.request.user)
        page.record_view()
        context.update(page.context())
        context.update(origin=origin, origin_label=self.ORIGINS[origin])
        return context


class RenterComplexDetailView(RenterListingView):
    page_class = ComplexPage
    template_name = "core_listings/renters/complex_detail.html"


class RenterUnitDetailView(RenterListingView):
    page_class = UnitPage
    template_name = "core_listings/renters/unit_detail.html"
