# core_maps/maps/services.py
# Business logic for the map feature:
#   - landlords: pin a point -> nearby landmarks (with distance + travel time)
#   - renters:   pin a point -> complexes within the radius
import json
import logging

from django.db import transaction
from django.urls import reverse

from core.core_listings.models import Area, Complex, ComplexLandmark, Landmark

from .categories import CategoryStyle
from .geo import GeoPoint, TravelEstimate, TravelMode
from .providers import LocalProvider, NominatimGeocoder, OverpassProvider, PhotonGeocoder, ProviderError

logger = logging.getLogger(__name__)


# =========================================================
# LANDMARKS (landlord side)
# =========================================================

class LandmarkFinder:
    """Landmarks around a pin, nearest first, at most `per_category` per category."""

    def __init__(self, point, radius, mode, per_category=3, limit=40):
        self.point = point
        self.radius = radius
        self.mode = TravelMode.get(mode)
        self.per_category = per_category
        self.limit = limit
        self.source = None      # "live" (OpenStreetMap) or "offline" (only our own table)

    def find(self):
        """Returns (landmarks, source); source is "offline" when Overpass was unreachable."""
        candidates = LocalProvider().fetch(self.point, self.radius.metres) + self._overpass_rings()
        results = self._limit_per_category(self._nearest_copies(candidates))
        if self.source == "live":
            try:
                self._remember(results)
            except Exception as error:      # never let bookkeeping break the map
                logger.warning("Couldn't remember landmarks: %s", error)
        return results, self.source

    def _overpass_rings(self):
        """OSM landmarks fetched in growing circles (1 km, 3 km, ... up to the radius).

        Overpass caps how many places it returns and does NOT return the nearest
        first, so one big circle could drop a landmark that the small circle
        showed. Asking for every smaller preset circle too means a landmark seen
        at "< 1 km" is still there at 3/5/10 km. All the circles go in ONE
        request and the answer is cached, so switching back to a radius doesn't ask again.
        """
        try:
            results = OverpassProvider().fetch_rings(self.point, [km * 1000 for km in self.radius.rings_km])
            self.source = "live"
            return results
        except ProviderError as error:
            logger.warning("Overpass failed, using saved landmarks only: %s", error)
            self.source = "offline"
            return []

    def _nearest_copies(self, candidates):
        """Keep the nearest copy of each (name, category), sorted by distance."""
        best = {}
        for item in candidates:
            distance_m = self.point.distance_to(item["lat"], item["lng"])
            if distance_m > self.radius.metres:
                continue
            key = (item["name"].lower(), item["category"])
            if key not in best or distance_m < best[key]["distance_m"]:
                best[key] = {**item, **CategoryStyle(item["category"]).as_dict(),
                             **TravelEstimate(distance_m, self.mode).as_dict()}
        return sorted(best.values(), key=lambda item: item["distance_m"])

    def _limit_per_category(self, ordered):
        per_category_count = {}
        results = []
        for item in ordered:
            count = per_category_count.get(item["category"], 0)
            if count >= self.per_category:
                continue
            per_category_count[item["category"]] = count + 1
            results.append(item)
            if len(results) >= self.limit:
                break
        return results

    @staticmethod
    def _remember(landmarks):
        """Keep the OSM landmarks we showed in our own Landmark table, so place
        search finds them right away and they still show when Overpass is down."""
        fresh = [item for item in landmarks if item.get("source") == "osm"]
        if not fresh:
            return
        key = lambda name, category, lat, lng: (name.casefold(), str(category), round(float(lat), 5), round(float(lng), 5))
        known = {
            key(*row) for row in Landmark.objects.filter(name__in={item["name"] for item in fresh})
            .values_list("name", "category", "latitude", "longitude")
        }
        new = {}
        for item in fresh:
            k = key(item["name"], item["category"], item["lat"], item["lng"])
            if k not in known:
                new[k] = Landmark(name=item["name"][:200], category=item["category"],
                                  latitude=round(item["lat"], 6), longitude=round(item["lng"], 6))
        Landmark.objects.bulk_create(new.values())


class ComplexLandmarks:
    """The landmarks saved for one complex."""

    MAX_SAVED = 30

    def __init__(self, complex_obj):
        self.complex = complex_obj

    def as_list(self):
        """Saved landmarks, formatted like LandmarkFinder.find()."""
        if not self.complex:
            return []
        links = (
            ComplexLandmark.objects
            .filter(complex=self.complex)
            .select_related("landmark")
            .order_by("distance_m")
        )
        return [
            {
                "name": link.landmark.name,
                "lat": float(link.landmark.latitude),
                "lng": float(link.landmark.longitude),
                "travel_mode": link.travel_mode,
                "manual": link.is_manual,
                **CategoryStyle(link.landmark.category).as_dict(),
                **TravelEstimate(link.distance_m, TravelMode.get(link.travel_mode)).as_dict(),
            }
            for link in links
        ]

    @transaction.atomic
    def replace(self, landmarks, mode):
        """Replace the complex's landmarks with the ones the landlord kept.

        `landmarks` is the list sent by the wizard: [{name, category, lat, lng, manual}, ...]
        ("manual": added by the landlord, kept when the landmarks are generated again).
        Distances/times are recomputed here from the saved complex coordinates,
        the browser values are never trusted.
        """
        mode = TravelMode.get(mode)
        ComplexLandmark.objects.filter(complex=self.complex).delete()

        if self.complex.latitude is None or self.complex.longitude is None:
            return []

        point = self.complex_point
        saved = []
        for item in landmarks[:self.MAX_SAVED]:
            cleaned = self._clean(item)
            if cleaned is None:
                continue
            name, category, lat, lng = cleaned

            landmark, _ = Landmark.objects.get_or_create(
                name=name, category=category, latitude=lat, longitude=lng,
            )

            distance_m = point.distance_to(lat, lng)
            link, _ = ComplexLandmark.objects.update_or_create(
                complex=self.complex,
                landmark=landmark,
                travel_mode=mode.key,
                defaults={
                    "distance_m": round(distance_m),
                    "travel_minutes": mode.minutes_for(distance_m),
                    "is_manual": bool(item.get("manual")),
                },
            )
            saved.append(link)

        return saved

    @property
    def complex_point(self):
        return GeoPoint(self.complex.latitude, self.complex.longitude)

    @staticmethod
    def _clean(item):
        """(name, category, lat, lng) of one landmark from the browser, or None if it isn't valid."""
        try:
            name = str(item["name"]).strip()[:200]
            category = item.get("category")
            lat = round(float(item["lat"]), 6)
            lng = round(float(item["lng"]), 6)
        except (KeyError, TypeError, ValueError):
            return None

        if not name or category not in Landmark.LandmarkTypes.values or not (-90 <= lat <= 90 and -180 <= lng <= 180):
            return None
        return name, category, lat, lng


class ManualPins:
    """Landmarks the landlord added by hand (not saved yet), drawn on the map too.
    ?pins=[{"name", "category", "lat", "lng"}, ...]"""

    LIMIT = 15

    def __init__(self, raw, point, mode):
        self.raw = raw
        self.point = point
        self.mode = TravelMode.get(mode)

    def _pins(self):
        try:
            pins = json.loads(self.raw or "[]")
        except ValueError:
            return []
        return pins[:self.LIMIT] if isinstance(pins, list) else []

    def as_list(self):
        items = []
        for pin in self._pins():
            try:
                name, lat, lng = str(pin["name"])[:120], float(pin["lat"]), float(pin["lng"])
            except (KeyError, TypeError, ValueError):
                continue
            distance_m = self.point.distance_to(lat, lng)
            items.append({"name": name, "lat": lat, "lng": lng, **CategoryStyle(pin.get("category")).as_dict(),
                          **TravelEstimate(distance_m, self.mode).as_dict()})
        return items


# =========================================================
# COMPLEXES (renter side)
# =========================================================

class ComplexSearch:
    """Listings renters may see within the radius of a pin, nearest first."""

    def __init__(self, point, radius, mode, filters=None):
        self.point = point
        self.radius = radius
        self.mode = TravelMode.get(mode)
        self.filters = filters or {}

    @staticmethod
    def searchable():
        """Only listings renters are allowed to see (and that have a map pin)."""
        return Complex.objects.renter_visible().filter(latitude__isnull=False, longitude__isnull=False)

    def _queryset(self):
        min_lat, max_lat, min_lng, max_lng = self.point.bounding_box(self.radius.km)
        queryset = (
            self.searchable()
            .filter(latitude__range=(min_lat, max_lat), longitude__range=(min_lng, max_lng))
            .select_related("area")
            .prefetch_related("pictures")
        )
        filters = self.filters
        if filters.get("max_price"):
            queryset = queryset.filter(min_price__lte=filters["max_price"])
        if filters.get("min_price"):
            queryset = queryset.filter(max_price__gte=filters["min_price"])
        if filters.get("sex_restriction"):
            queryset = queryset.filter(sex_restriction__in=[filters["sex_restriction"], "any"])
        if filters.get("pet_friendly"):
            queryset = queryset.filter(pet_friendly=True)
        return queryset

    def results(self):
        results = []
        for complex_obj in self._queryset():
            distance_m = self.point.distance_to(complex_obj.latitude, complex_obj.longitude)
            if distance_m <= self.radius.metres:
                results.append(self._as_dict(complex_obj, distance_m))
        results.sort(key=lambda item: item["distance_m"])
        return results

    def _as_dict(self, complex_obj, distance_m):
        pictures = complex_obj.pictures.all()
        cover = next((p for p in pictures if p.is_cover), None) or next(iter(pictures), None)
        return {
            "id": str(complex_obj.complex_id),
            "name": complex_obj.complex_name,
            "address": complex_obj.address,
            "area": complex_obj.area.area_name,
            "lat": float(complex_obj.latitude),
            "lng": float(complex_obj.longitude),
            "min_price": float(complex_obj.min_price),
            "max_price": float(complex_obj.max_price),
            "pet_friendly": complex_obj.pet_friendly,
            "sex_restriction": complex_obj.get_sex_restriction_display(),
            "lease_term": complex_obj.get_lease_term_display(),
            "image": cover.image.url if cover else "",
            "url": reverse("core_listings:renter_complex_detail", args=[complex_obj.pk]) + "?from=findNear",
            **TravelEstimate(distance_m, self.mode).as_dict(),
        }


# =========================================================
# PLACES / ADDRESSES
# =========================================================

class PlaceSearch:
    """Text search for a point, e.g. "Mapua" -> Mapúa Malayan Colleges Mindanao.
    Our own Landmark table first (fast, works offline), then OpenStreetMap."""

    # Photon understands half-typed words; Nominatim only whole ones (and asks
    # not to be used while typing), so it's only asked when Photon is down.
    ONLINE_GEOCODERS = (PhotonGeocoder, NominatimGeocoder)

    def __init__(self, query, limit=6):
        self.query = (query or "").strip()
        self.limit = limit

    def results(self):
        if len(self.query) < 2:
            return []

        results = LocalProvider().search(self.query, self.limit)
        if len(results) < self.limit:
            results += self._ask_online(self.limit - len(results))
        return self._unique(results)[:self.limit]

    def _ask_online(self, limit):
        """Polymorphism: every Geocoder answers search() the same way; the first that works wins."""
        for geocoder_class in self.ONLINE_GEOCODERS:
            try:
                return geocoder_class().search(self.query, limit=limit)
            except ProviderError as error:
                logger.warning("Place search: %s", error)
        return []

    @staticmethod
    def _unique(results):
        seen = set()
        unique = []
        for item in results:
            key = (item["name"].lower(), round(item["lat"], 3), round(item["lng"], 3))
            if key not in seen:
                seen.add(key)
                unique.append(item)
        return unique


class AddressLookup:
    """The address of a pin (empty strings when Nominatim is unreachable)."""

    EMPTY = {"address": "", "full_address": "", "area": ""}

    def __init__(self, point):
        self.point = point

    def result(self):
        try:
            return NominatimGeocoder().reverse(self.point)
        except ProviderError as error:
            logger.warning("Reverse geocoding failed: %s", error)
            return dict(self.EMPTY)


class AreaName:
    """The area a landlord typed (or the map filled in), as an Area row."""

    DEFAULT = "Davao City"

    def __init__(self, raw):
        self.name = (raw or "").strip() or self.DEFAULT

    def resolve(self):
        area, _ = Area.objects.get_or_create(area_name=self.name)
        return area
