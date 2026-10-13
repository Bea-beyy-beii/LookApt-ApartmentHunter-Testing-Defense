# core_renters/search.py
# Search bar + "Filter by" on the renter's Home and Saved Listings tabs.
#
#   ?q=sunrise davao&lease_term=monthly&pets=1&budget_max=8000 ...
#
# Complex-level filters narrow the complexes; unit-level filters narrow the
# units, and a complex only shows when at least one of its units still matches
# (the card's price then comes from those units).
from decimal import Decimal, InvalidOperation

from django.db.models import Q

from core.core_listings.models import BedroomType, Complex, FurnishLevel, LeaseTerm, SexRestriction, Unit


class ListingSearch:
    """One search: ListingSearch(request.GET). Anything invalid in the params is simply ignored.

    `filters` is the cleaned dict the template reads (search.q, search.budget_max ...).
    """

    MAX_QUERY_LENGTH = 100

    # Checkbox name -> model field. Complex features first, then unit amenities.
    COMPLEX_FEATURES = {
        "pets": "pet_friendly",
        "parking": "has_parking_space",
        "gated": "is_gated",
        "laundry": "has_laundry_area",
        "security": "has_security",
        "cctv": "has_cctv",
        "lounge": "has_common_lounge",
        "waste": "has_waste_collection",
    }
    UNIT_AMENITIES = {
        "aircon": "air_conditioned",
        "wifi": "wifi_ready",
        "bathroom": "own_bathroom",
        "kitchen": "has_kitchen_area",
        "meter": "own_electric_meter",
        "heater": "has_water_heater",
    }

    SORTS = {
        "newest": "Newest first",
        "price_low": "Price: low to high",
        "price_high": "Price: high to low",
    }

    def __init__(self, params=None):
        self.filters = self._parse(params or {})

    # ---------- reading the params ----------

    @staticmethod
    def _decimal(value):
        try:
            number = Decimal(str(value).replace(",", "").strip())
        except (InvalidOperation, ValueError):
            return None
        return number if number > 0 else None

    @staticmethod
    def _positive_int(value, limit=20):
        try:
            number = int(value)
        except (TypeError, ValueError):
            return None
        return number if 1 <= number <= limit else None

    @staticmethod
    def _choice(value, choices):
        return value if value in choices else ""

    def _parse(self, params):
        budget_min, budget_max = self._decimal(params.get("budget_min")), self._decimal(params.get("budget_max"))
        if budget_min and budget_max and budget_min > budget_max:
            budget_min, budget_max = budget_max, budget_min

        return {
            "q": (params.get("q") or "").strip()[:self.MAX_QUERY_LENGTH],
            "lease_term": self._choice(params.get("lease_term"), LeaseTerm.values),
            "sex": self._choice(params.get("sex"), SexRestriction.values),
            "unit_type": self._choice(params.get("unit_type"), BedroomType.values),
            "furnishing": self._choice(params.get("furnishing"), FurnishLevel.values),
            "occupants": self._positive_int(params.get("occupants")),
            "budget_min": budget_min,
            "budget_max": budget_max,
            "available": params.get("available") == "1",
            "features": [key for key in self.COMPLEX_FEATURES if params.get(key) == "1"],
            "amenities": [key for key in self.UNIT_AMENITIES if params.get(key) == "1"],
            "sort": self._choice(params.get("sort"), self.SORTS) or "newest",
        }

    # ---------- about this search ----------

    @property
    def sort(self):
        return self.filters["sort"]

    @property
    def filter_count(self):
        """For the badge on the "Filter by" button (search text and sort don't count)."""
        f = self.filters
        count = sum(bool(f[key]) for key in ("lease_term", "sex", "unit_type", "furnishing", "occupants", "available"))
        count += bool(f["budget_min"] or f["budget_max"])
        return count + len(f["features"]) + len(f["amenities"])

    @property
    def is_active(self):
        return bool(self.filters["q"]) or self.filter_count > 0

    # ---------- applying it ----------

    def filter_complexes(self, complexes):
        """Complex name, address, area, nearby landmarks, landlord name + complex-level filters."""
        f = self.filters
        for word in f["q"].split():
            complexes = complexes.filter(
                Q(complex_name__icontains=word)
                | Q(address__icontains=word)
                | Q(area__area_name__icontains=word)
                | Q(landmarks__landmark__name__icontains=word)
                | Q(landlord__user__first_name__icontains=word)
                | Q(landlord__user__last_name__icontains=word)
            )

        if f["lease_term"]:
            complexes = complexes.filter(lease_term=f["lease_term"])
        if f["sex"]:
            complexes = complexes.filter(sex_restriction=f["sex"])
        for key in f["features"]:
            complexes = complexes.filter(**{self.COMPLEX_FEATURES[key]: True})

        return complexes.distinct()     # the landmark join can repeat a complex

    def filter_units(self, units):
        """Unit-level filters: the units a renter could actually take."""
        f = self.filters
        if f["unit_type"]:
            units = units.filter(bedroom_type=f["unit_type"])
        if f["furnishing"]:
            units = units.filter(furnish_level=f["furnishing"])
        if f["occupants"]:
            units = units.filter(max_occupant__gte=f["occupants"])
        if f["budget_min"]:
            units = units.filter(price__gte=f["budget_min"])
        if f["budget_max"]:
            units = units.filter(price__lte=f["budget_max"])
        if f["available"]:
            units = units.filter(availability=Unit.Availability.AVAILABLE)
        for key in f["amenities"]:
            units = units.filter(**{self.UNIT_AMENITIES[key]: True})
        return units

    def order(self, listings):
        if self.sort == "price_low":
            return sorted(listings, key=lambda c: c.card_price)
        if self.sort == "price_high":
            return sorted(listings, key=lambda c: c.card_price, reverse=True)
        return listings        # already newest first

    @classmethod
    def options(cls):
        """Choices for the filter panel (template)."""
        return {
            "lease_terms": LeaseTerm.choices,
            "sex_restrictions": [c for c in SexRestriction.choices if c[0] != SexRestriction.NO_RESTRICTION]
                                + [(SexRestriction.NO_RESTRICTION, "No restriction")],
            "unit_types": BedroomType.choices,
            "furnishings": FurnishLevel.choices,
            "features": [(key, Complex.FEATURE_LABELS[field]) for key, field in cls.COMPLEX_FEATURES.items()],
            "amenities": [(key, Unit._meta.get_field(field).verbose_name) for key, field in cls.UNIT_AMENITIES.items()],
            "sorts": list(cls.SORTS.items()),
        }
