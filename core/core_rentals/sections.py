"""Manage Rentals (landlord) and Rental History (renter) (DashboardSections, see core/sections.py)."""
import json

from django.db.models import Prefetch

from core.core_inquiries.models import Application
from core.core_inquiries.services import today
from core.core_listings.models import Complex, Unit
from core.core_reviews.services import ReviewSubmission
from core.sections import DashboardSection

from .models import Tenancy


class TenancySection(DashboardSection):
    """Shared by both rental tabs: adds what the tenancy rows show on today's date.

    Inheritance: RentalsSection and RenterRentalsSection only add their own data.
    """

    def __init__(self, user, request=None, shared=None):
        super().__init__(user, request, shared)
        self.on = today()

    @staticmethod
    def _cover_url(pictures):
        pictures = list(pictures)
        cover = next((p for p in pictures if p.is_cover), None) or (pictures[0] if pictures else None)
        return cover.image.url if cover else ""

    def _decorate(self, tenancy):
        on = self.on
        # The term running now (leases renew until completed/terminated)
        tenancy.term_start, tenancy.term_end = tenancy.current_term(on)
        tenancy.renewed = tenancy.term_end > tenancy.first_term_end
        tenancy.days_left = (tenancy.term_end - on).days
        # "Ending soon" only makes sense for leases longer than a month
        tenancy.ending_soon = (
            tenancy.is_active and tenancy.lease_months > 1 and 0 <= tenancy.days_left <= Tenancy.ENDING_SOON_DAYS
        )
        if tenancy.is_active:
            tenancy.pay = tenancy.payment_status(on)
            tenancy.payable = tenancy.payable_months(on)
            tenancy.payable_json = json.dumps(tenancy.payable)
            tenancy.renew_to = tenancy.renewal_end(on)
        return tenancy


class RentalsSection(TenancySection):
    """Manage Rentals: the landlord's published complexes, their units and tenants, and the Archive."""

    def context(self):
        self._candidates = self._candidates_by_unit()
        groups = [self._group(complex_obj) for complex_obj in self._complexes()]
        archive = self._archive()
        return {
            "rental_groups": groups,
            "rental_archive": archive,
            "rental_counts": {"archive": len(archive)},
            "bulletin_complexes": [g for g in groups],
            "today_iso": self.on.isoformat(),
        }

    def _complexes(self):
        active = Prefetch(
            "tenancies",
            queryset=Tenancy.objects.active().select_related("renter__user").prefetch_related("payments"),
            to_attr="active_tenancies",
        )
        units = (
            Unit.objects.exclude(availability=Unit.Availability.UNPUBLISHED)
            .prefetch_related("pictures", active)
            .order_by("identifier")
        )
        # Only published complexes; an unpublished one (and its units) stays out of Manage Rentals
        return (
            Complex.objects.filter(landlord__user=self.user, status=Complex.ComplexStatus.ACTIVE)
            .prefetch_related("pictures", Prefetch("units", queryset=units))
            .order_by("complex_name")
        )

    def _candidates_by_unit(self):
        """Open requests (pending or waitlisted) per unit, for the "Assign a Renter" pop-up."""
        pending = (
            Application.objects.filter(unit__complex__landlord__user=self.user, status__in=Application.OPEN_STATUSES)
            .select_related("renter__user").order_by("created_at")
        )
        by_unit = {}
        for application in pending:
            by_unit.setdefault(application.unit_id, []).append(application)
        return by_unit

    @staticmethod
    def _candidate_json(application):
        move_in = application.move_in_date
        return {
            "id": str(application.pk),
            "name": application.renter.user.display_name,
            "kind": "On the waitlist" if application.status == Application.Status.WAITLISTED
                    else application.get_kind_display(),
            "occupants": len(application.occupants) or 1,
            "move_in": move_in.isoformat(),
            "move_in_label": f"{move_in:%b} {move_in.day}, {move_in.year}",
        }

    def _unit_row(self, unit):
        tenancy = unit.active_tenancies[0] if unit.active_tenancies else None
        if tenancy:
            self._decorate(tenancy)
        unit.tenancy = tenancy
        unit.cover_url = self._cover_url(unit.pictures.all())
        unit.candidates = self._candidates.get(unit.pk, [])
        # For the "Assign a Renter" pop-up (read from a data-* attribute)
        unit.candidates_json = json.dumps([self._candidate_json(a) for a in unit.candidates])
        # "Occupied" without a tenancy record = landlord set it by hand (before this feature)
        unit.state = "occupied" if tenancy or unit.availability == Unit.Availability.OCCUPIED else "vacant"
        unit.ending_soon = bool(tenancy and tenancy.ending_soon)
        return unit

    def _group(self, complex_obj):
        rows = [self._unit_row(unit) for unit in complex_obj.units.all()]
        stats = {
            "total": len(rows),
            "occupied": sum(1 for u in rows if u.state == "occupied"),
            "vacant": sum(1 for u in rows if u.state == "vacant"),
            "ending_soon": sum(1 for u in rows if u.ending_soon),
        }
        return {"complex": complex_obj, "cover_url": self._cover_url(complex_obj.pictures.all()), "units": rows,
                "stats": stats}

    def _archive(self):
        archive = [
            self._decorate(t) for t in
            Tenancy.objects.of_landlord(self.user).ended()
            .select_related("unit__complex", "renter__user")
            .prefetch_related("unit__pictures")
            .order_by("-ended_on", "-start_date")
        ]
        for tenancy in archive:
            tenancy.unit.cover_url = self._cover_url(tenancy.unit.pictures.all())
        return archive


class RenterRentalsSection(TenancySection):
    """Rental History (renter): current rentals (incl. approved ones that start later) + past ones."""

    def context(self):
        tenancies = (
            Tenancy.objects.of_renter(self.user)
            .select_related("unit__complex__landlord__user", "review")
            .prefetch_related("payments", "unit__pictures", "unit__complex__pictures", "review__photos")
        )
        current, past = [], []
        for tenancy in tenancies:
            self._decorate(tenancy)
            (current if tenancy.is_active else past).append(tenancy)
        past.sort(key=lambda t: t.ended_on or t.end_date, reverse=True)
        return {"current_rentals": current, "past_rentals": past, **ReviewSubmission.form_context()}

    def _decorate(self, tenancy):
        super()._decorate(tenancy)
        on = self.on
        unit = tenancy.unit
        tenancy.cover_url = self._cover_url(unit.pictures.all()) or self._cover_url(unit.complex.pictures.all())
        landlord = unit.complex.landlord.user
        tenancy.landlord_name = landlord.display_name
        tenancy.landlord_initials = landlord.initials
        tenancy.landlord_avatar = landlord.avatar_url
        tenancy.landlord_contact = landlord.shared_contact      # only what they chose to show (Settings)
        tenancy.upcoming = tenancy.start_date > on
        tenancy.days_to_start = (tenancy.start_date - on).days
        # "Leave a Review" once the rental has started; "Edit Review" after that
        tenancy.my_review = getattr(tenancy, "review", None)
        tenancy.review_data = tenancy.my_review.to_json() if tenancy.my_review else ""
        return tenancy
