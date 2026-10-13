# core_listings/detail_services.py
# Data for the renter's listing pages:
#   - complex page (photos, units, amenities, location, landlord)
#   - unit page    (photos/videos, payment, amenities, similar units)
from abc import ABC, abstractmethod
from collections import Counter
from decimal import Decimal

from django.db.models import Prefetch
from django.shortcuts import get_object_or_404

from core.core_inquiries.models import Application
from core.core_inquiries.services import LeaseSchedule
from core.core_maps.maps.services import ComplexLandmarks

from .models import BedroomType, Complex, ListingView, SavedListing, Unit


class LandlordSummary:
    """The landlord box on a listing page."""

    def __init__(self, landlord):
        self.landlord = landlord
        self.user = landlord.user

    def as_dict(self):
        from core.core_reviews.models import Review    # core_reviews imports core_rentals -> core_listings
        user = self.user
        return {
            "rating": Review.objects.for_landlord(self.landlord).summary("landlord"),   # stars beside the name
            "name": user.display_name,
            "initials": user.initials,
            "avatar_url": user.avatar_url,
            # Only what the landlord chose to show (Settings > Contact sharing)
            "email": user.email if user.share_email else "",
            "phone": user.phone_number if user.share_phone else "",
            "is_verified": user.is_verified,
            "listings": Complex.objects.renter_visible().filter(landlord=self.landlord).count(),
            "member_since": user.date_joined,
        }


class ListingPage(ABC):
    """A renter's listing page (abstraction + polymorphism): ComplexPage and
    UnitPage share the unit cards and the landlord box; each one loads its own
    listing and builds its own context()."""

    unit = None     # set by UnitPage

    def __init__(self, complex_obj, user):
        self.complex = complex_obj
        self.user = user

    @classmethod
    def open(cls, pk, user):
        """The page of a listing renters may see (404 otherwise)."""
        return cls(get_object_or_404(cls._queryset(), pk=pk), user)

    @classmethod
    @abstractmethod
    def _queryset(cls):
        """What renters may open, with what the page needs prefetched."""

    @abstractmethod
    def context(self):
        """The template variables of the page."""

    def record_view(self):
        """Count the visit for the landlord's "Views"."""
        ListingView.record(self.user, self.complex, self.unit)

    # ---------- shared helpers ----------

    @staticmethod
    def _cover(pictures):
        """The cover photo, or the first one (pictures are already prefetched)."""
        pictures = list(pictures)
        return next((p for p in pictures if p.is_cover), None) or (pictures[0] if pictures else None)

    def _decorate_unit(self, unit):
        """Values every unit row / card shows."""
        cover = self._cover(unit.pictures.all())
        unit.cover_url = cover.image.url if cover else ""
        unit.is_available = unit.availability == Unit.Availability.AVAILABLE
        return unit

    def _attach_inquiry_info(self, units):
        """What the Apply / Waitlist buttons and the demand box need, per unit."""
        pending = Application.objects.filter(unit__in=units, status__in=Application.OPEN_STATUSES)
        demand = Counter(pending.values_list("unit_id", flat=True))
        mine = set(pending.filter(renter__user=self.user).values_list("unit_id", flat=True))

        for unit in units:
            unit.demand = demand[unit.pk]               # renters interested / on the waitlist
            unit.has_pending = unit.pk in mine          # this renter already applied
            lease = LeaseSchedule(unit)
            unit.earliest_move_in = lease.earliest_move_in
            unit.lease_end = lease.current_end          # None when the landlord hasn't set it
        return units

    def _landlord(self):
        return LandlordSummary(self.complex.landlord).as_dict()


# =========================================================
# COMPLEX PAGE
# =========================================================

class ComplexPage(ListingPage):

    @classmethod
    def _queryset(cls):
        return (
            Complex.objects.renter_visible()
            .select_related("landlord__user", "area")
            .prefetch_related("pictures", Prefetch("units", queryset=Unit.objects.for_renters()))
        )

    def context(self):
        from core.core_reviews.models import Review
        from core.core_reviews.services import ComplexReviews

        complex_obj = self.complex
        units = [self._decorate_unit(unit) for unit in complex_obj.units.all()]
        self._attach_inquiry_info(units)
        ratings = Review.objects.unit_summaries(units)
        for unit in units:
            unit.rating = ratings.get(unit.pk)          # stars under the price (None: no reviews yet)
        available = [unit for unit in units if unit.is_available]
        prices = [unit.price for unit in (available or units)]

        return {
            "complex": complex_obj,
            "media": [{"kind": "image", "url": p.image.url} for p in complex_obj.pictures.all()],
            "units": units,
            "unit_types": self._unit_types(units),
            "available_count": len(available),
            "occupied_count": len(units) - len(available),
            "demand": sum(unit.demand for unit in units),
            "lowest_price": min(prices) if prices else None,
            "features": complex_obj.feature_checklist(),
            "unit_amenities": self._unit_amenities(units),
            "landmarks": ComplexLandmarks(complex_obj).as_list(),
            "landlord": self._landlord(),
            "is_saved": SavedListing.is_saved(self.user, complex_obj),
            "other_listings": self._other_listings(),
            "complex_rating": Review.objects.for_complex(complex_obj).summary("complex"),   # stars beside the name
            **ComplexReviews(complex_obj).context(),          # Reviews tab
        }

    @staticmethod
    def _unit_types(units):
        # Unit types in the usual order: Studio, 1BR, 2BR, 3+
        present_types = {unit.bedroom_type for unit in units}
        return [{"key": key, "label": label} for key, label in BedroomType.choices if key in present_types]

    @staticmethod
    def _unit_amenities(units):
        # In-unit amenities found in this complex: "Air Conditioned — 3 of 4 units"
        unit_amenities = []
        for name in Unit.AMENITY_FIELDS:
            count = sum(1 for unit in units if getattr(unit, name))
            if count:
                unit_amenities.append({
                    "key": name,
                    "label": Unit._meta.get_field(name).verbose_name,
                    "count": count,
                })
        return unit_amenities

    def _other_listings(self):
        from core.core_renters.services import ListingCards   # core_renters imports core_listings
        return ListingCards(self.user).other_listings(self.complex)


# =========================================================
# UNIT PAGE
# =========================================================

class UnitPage(ListingPage):

    SIMILAR_LIMIT = 6
    SIMILAR_PRICE_RANGE = Decimal("0.30")   # "similar" = rent within ±30%

    def __init__(self, unit, user):
        super().__init__(unit.complex, user)
        self.unit = unit

    @classmethod
    def _queryset(cls):
        return (
            Unit.objects.for_renters()
            .filter(complex__in=Complex.objects.renter_visible())
            .select_related("complex__landlord__user", "complex__area")
            .prefetch_related("videos")
        )

    def context(self):
        from core.core_reviews.models import Review

        unit = self._decorate_unit(self.unit)
        unit.rating = Review.objects.for_unit(unit).summary("unit")
        self._attach_inquiry_info([unit])
        same_complex, other_complexes = self._similar_units()

        # Photos first, then videos (the gallery shows both)
        media = [{"kind": "image", "url": p.image.url} for p in unit.pictures.all()]
        media += [{"kind": "video", "url": v.video.url} for v in unit.videos.all()]

        return {
            "unit": unit,
            "complex": self.complex,
            "media": media,
            "payment": unit.payment_summary(),
            "unit_amenities": unit.amenity_checklist(),
            "features": self.complex.feature_checklist(),
            "similar_same_complex": same_complex,
            "similar_other_complexes": other_complexes,
            "landlord": self._landlord(),
        }

    def _similar_units(self):
        """Same unit type and a close rent: first in the same complex, then elsewhere."""
        unit = self.unit
        low = unit.price * (1 - self.SIMILAR_PRICE_RANGE)
        high = unit.price * (1 + self.SIMILAR_PRICE_RANGE)

        # Same complex: every other published unit, most similar first
        same_complex = [
            self._decorate_unit(other) for other in Unit.objects.for_renters()
            .filter(complex=unit.complex)
            .exclude(pk=unit.pk)
        ]
        same_complex.sort(key=lambda other: (
            other.bedroom_type != unit.bedroom_type,   # same type first
            not other.is_available,                    # then available
            abs(other.price - unit.price),             # then closest rent
        ))

        other_complexes = [
            self._decorate_unit(other) for other in Unit.objects.for_renters()
            .filter(
                complex__in=Complex.objects.renter_visible().exclude(pk=unit.complex_id),
                bedroom_type=unit.bedroom_type,
                price__gte=low,
                price__lte=high,
            )
            .select_related("complex")
        ]
        other_complexes.sort(key=lambda other: (not other.is_available, abs(other.price - unit.price)))

        return same_complex[:self.SIMILAR_LIMIT], other_complexes[:self.SIMILAR_LIMIT]
