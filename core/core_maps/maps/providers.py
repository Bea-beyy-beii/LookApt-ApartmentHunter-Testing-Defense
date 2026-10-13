# core_maps/maps/providers.py
# Where landmark / place data comes from.
#
#   LandmarkSource (abstract) -> fetch(point, radius_m): landmarks around a point
#       OverpassProvider      -> OpenStreetMap points of interest (free, no API key)
#       LocalProvider         -> our own Landmark table (seeded, saved and previously seen landmarks)
#   Geocoder (abstract)       -> search(query, limit): places matching a text
#       LocalProvider         -> landmark names in our own table (works offline)
#       PhotonGeocoder        -> place search made for search-as-you-type (partial words, typos)
#       NominatimGeocoder     -> OpenStreetMap place search (fallback) + reverse geocoding (address of a pin)
#
# The OpenStreetMap servers are free public servers with usage policies:
#   - always send a descriptive User-Agent
#   - Nominatim: max 1 request / second, and no search-as-you-type (Photon handles that)
#   - cache results instead of asking again
import hashlib
import logging
import threading
import time
import unicodedata
from abc import ABC, abstractmethod
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

import requests
from django.core.cache import cache

from core.core_listings.models import Landmark

from .geo import DEFAULT_CENTER, GeoPoint

logger = logging.getLogger(__name__)

Types = Landmark.LandmarkTypes


class ProviderError(Exception):
    pass


# =========================================================
# THE TWO KINDS OF PROVIDER
# =========================================================

class LandmarkSource(ABC):
    """Abstraction: anything that lists the landmarks around a point."""

    @abstractmethod
    def fetch(self, point, radius_m):
        """[{name, category, lat, lng, source, ...}, ...] within radius_m of the GeoPoint."""


class Geocoder(ABC):
    """Abstraction: anything that turns a text ("Mapua") into places on the map."""

    @abstractmethod
    def search(self, query, limit=5):
        """[{name, address, lat, lng, source, ...}, ...]; raises ProviderError when unreachable."""


# =========================================================
# SHARED BY EVERY OPENSTREETMAP SERVER
# =========================================================

class OpenStreetMapClient:
    """User-Agent, timeouts, caching and OSM tag -> category, shared by the OSM providers."""

    USER_AGENT = "LookApt/1.0 (apartment finder, Davao City)"
    HTTP_TIMEOUT = 12
    CACHE_SECONDS = 60 * 60 * 24

    TAG_CATEGORIES = {
        ("amenity", "school"): Types.SCHOOL,
        ("amenity", "college"): Types.SCHOOL,
        ("amenity", "university"): Types.SCHOOL,
        ("amenity", "hospital"): Types.HEALTHCENTER,
        ("amenity", "clinic"): Types.HEALTHCENTER,
        ("amenity", "pharmacy"): Types.PHARMACY,
        ("shop", "chemist"): Types.PHARMACY,
        ("amenity", "bank"): Types.BANK,
        ("amenity", "marketplace"): Types.MARKET,
        ("shop", "supermarket"): Types.MARKET,
        ("amenity", "restaurant"): Types.RESTAURANT,
        ("amenity", "fast_food"): Types.RESTAURANT,
        ("amenity", "bus_station"): Types.TERMINAL,
        ("amenity", "ferry_terminal"): Types.TERMINAL,
        ("aeroway", "aerodrome"): Types.AIRPORT,
        ("amenity", "place_of_worship"): Types.CHURCH,
        ("amenity", "townhall"): Types.GOVERNMENT,
        ("office", "government"): Types.GOVERNMENT,
        ("shop", "mall"): Types.MALL,
        ("shop", "department_store"): Types.MALL,
        ("leisure", "park"): Types.PARK,
        ("leisure", "fitness_centre"): Types.GYM,
    }

    def category_for(self, tags):
        for (key, value), category in self.TAG_CATEGORIES.items():
            if tags.get(key) == value:
                return category
        return None

    def _cache_key(self, prefix, *parts):
        raw = "|".join(str(p) for p in parts)
        return f"core_maps:{prefix}:{hashlib.md5(raw.encode()).hexdigest()}"

    def _headers(self, **extra):
        return {"User-Agent": self.USER_AGENT, **extra}


# =========================================================
# OVERPASS (OpenStreetMap points of interest)
# =========================================================

class OverpassProvider(OpenStreetMapClient, LandmarkSource):
    ENDPOINTS = [
        "https://overpass-api.de/api/interpreter",
        "https://overpass.kumi.systems/api/interpreter",
        "https://overpass.private.coffee/api/interpreter",
    ]
    HTTP_TIMEOUT = 25
    # A slow server is asked again on the next one after this many seconds
    # (the first answer wins), instead of waiting out the full timeout
    HEDGE_SECONDS = 6
    # Overpass returns places in ID order, not nearest first, so a low cap
    # silently drops close landmarks in busy areas (see LandmarkFinder)
    MAX_RESULTS = 1500

    # Restaurants are everywhere: only look for them close by so they
    # don't crowd out schools, hospitals, etc. in big radii.
    SMALL_CATEGORY_RADIUS_M = 1500
    SMALL_CATEGORY_TAGS = {("amenity", "restaurant"), ("amenity", "fast_food")}

    def _union(self, lat, lng, radius_m):
        grouped = {}
        for key, value in self.TAG_CATEGORIES:
            small = (key, value) in self.SMALL_CATEGORY_TAGS
            grouped.setdefault((key, small), []).append(value)

        lines = []
        for (key, small), values in grouped.items():
            radius = min(radius_m, self.SMALL_CATEGORY_RADIUS_M) if small else radius_m
            pattern = "|".join(sorted(values))
            lines.append(f'  nwr(around:{int(radius)},{lat:.6f},{lng:.6f})["{key}"~"^({pattern})$"]["name"];')
        return "(\n" + "\n".join(lines) + "\n)"

    def build_query(self, lat, lng, radius_m):
        return f"[out:json][timeout:25];\n{self._union(lat, lng, radius_m)};\nout center {self.MAX_RESULTS};"

    def build_rings_query(self, lat, lng, radii_m):
        """Every circle in ONE request: each gets its own capped output, so a
        busy big circle can't push out the places of the small one."""
        parts = [f"{self._union(lat, lng, radius)}->.r{i};\n.r{i} out center {self.MAX_RESULTS};"
                 for i, radius in enumerate(radii_m)]
        return "[out:json][timeout:25];\n" + "\n".join(parts)

    def parse(self, payload):
        results = []
        for element in payload.get("elements", []):
            tags = element.get("tags", {})
            name = (tags.get("name:en") or tags.get("name") or "").strip()
            category = self.category_for(tags)
            if not name or not category:
                continue

            # nodes have lat/lon; ways/relations have a "center"
            point = element if "lat" in element else element.get("center")
            if not point:
                continue

            results.append({
                "name": name,
                "category": str(category),
                "lat": round(float(point["lat"]), 6),
                "lng": round(float(point["lon"]), 6),
                "source": "osm",
                "osm_id": f'{element.get("type")}/{element.get("id")}',
            })
        return results

    def _post(self, endpoint, query):
        response = requests.post(endpoint, data={"data": query}, headers=self._headers(), timeout=self.HTTP_TIMEOUT)
        response.raise_for_status()
        return self.parse(response.json())

    def _ask(self, query):
        """Ask the first server; if it hasn't answered after HEDGE_SECONDS
        (or it failed), ask the next one too. The first good answer wins."""
        errors = []
        pending = {}
        pool = ThreadPoolExecutor(max_workers=len(self.ENDPOINTS))
        try:
            for endpoint in self.ENDPOINTS:
                pending[pool.submit(self._post, endpoint, query)] = endpoint
                done, _ = wait(pending, timeout=self.HEDGE_SECONDS, return_when=FIRST_COMPLETED)
                result = self._first_success(done, pending, errors)
                if result is not None:
                    return result
            # Every server has been asked: wait for whichever answers first
            while pending:
                done, _ = wait(pending, timeout=self.HTTP_TIMEOUT, return_when=FIRST_COMPLETED)
                if not done:
                    break
                result = self._first_success(done, pending, errors)
                if result is not None:
                    return result
        finally:
            pool.shutdown(wait=False, cancel_futures=True)   # don't wait for the slower servers
        raise ProviderError(f"All Overpass servers failed: {errors[-1] if errors else 'timed out'}")

    @staticmethod
    def _first_success(done, pending, errors):
        for future in done:
            endpoint = pending.pop(future)
            try:
                return future.result()
            except (requests.RequestException, ValueError) as error:
                errors.append(error)
                logger.warning("Overpass request to %s failed: %s", endpoint, error)
        return None

    def fetch(self, point, radius_m):
        return self.fetch_rings(point, [radius_m])

    def fetch_rings(self, point, radii_m):
        """Landmarks within each of the circles (one request, cached)."""
        lat, lng = point
        radii_m = [int(radius) for radius in radii_m]
        key = self._cache_key("overpass-rings", round(lat, 4), round(lng, 4), *radii_m)
        cached = cache.get(key)
        if cached is not None:
            return cached

        query = self.build_query(lat, lng, radii_m[0]) if len(radii_m) == 1 else self.build_rings_query(lat, lng, radii_m)
        results = self._ask(query)
        cache.set(key, results, self.CACHE_SECONDS)
        return results


# =========================================================
# LOCAL DATABASE (seeded + previously saved landmarks)
# =========================================================

class LocalProvider(LandmarkSource, Geocoder):
    """Our own Landmark table. It is both a LandmarkSource and a Geocoder,
    and needs no internet for either."""

    def fetch(self, point, radius_m):
        min_lat, max_lat, min_lng, max_lng = point.bounding_box(radius_m / 1000)

        landmarks = Landmark.objects.filter(
            latitude__range=(min_lat, max_lat),
            longitude__range=(min_lng, max_lng),
        )

        results = []
        for landmark in landmarks:
            if point.distance_to(landmark.latitude, landmark.longitude) > radius_m:
                continue
            results.append({
                "name": landmark.name,
                "category": landmark.category,
                "lat": float(landmark.latitude),
                "lng": float(landmark.longitude),
                "source": "local",
                "landmark_id": str(landmark.landmark_id),
            })
        return results

    def search(self, query, limit=5):
        return [
            {
                "name": landmark.name,
                "address": landmark.get_category_display(),
                "lat": float(landmark.latitude),
                "lng": float(landmark.longitude),
                "category": landmark.category,
                "source": "local",
            }
            for landmark in self._matches(query, limit)
        ]

    def _matches(self, query, limit):
        """Every word must appear, in any order: "college jose" finds Jose Maria College."""
        words = query.split()
        queryset = Landmark.objects.all()
        for word in words:
            queryset = queryset.filter(name__icontains=word)
        matches = list(queryset[:limit])
        if len(matches) < limit:
            # Accents: "mapua" should find "Mapúa" (only names with accents need this check)
            folded = [self._fold(word) for word in words]
            seen = {m.pk for m in matches}
            accented = Landmark.objects.filter(name__regex=r"[^\x00-\x7F]")
            for landmark in accented.only("landmark_id", "name", "category", "latitude", "longitude").iterator():
                name = self._fold(landmark.name)
                if landmark.pk not in seen and all(word in name for word in folded):
                    matches.append(landmark)
                    if len(matches) >= limit:
                        break
        return matches

    @staticmethod
    def _fold(text):
        """Lowercase and strip accents so "mapua" matches "Mapúa"."""
        return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c)).casefold()


# =========================================================
# PHOTON + NOMINATIM (place search + reverse geocoding)
# =========================================================

class PhotonGeocoder(OpenStreetMapClient, Geocoder):
    """komoot's Photon (OpenStreetMap data), made for search-as-you-type:
    partial words and small typos still match ("jose maria col" -> Jose Maria College).
    Results near Davao come first."""
    URL = "https://photon.komoot.io/api/"

    def __init__(self, near=DEFAULT_CENTER):
        self.near = near

    def search(self, query, limit=5):
        key = self._cache_key("photon", query.casefold(), limit, self.near)
        cached = cache.get(key)
        if cached is not None:
            return cached
        try:
            response = requests.get(
                self.URL,
                params={"q": query, "limit": limit * 2, "lat": self.near[0], "lon": self.near[1], "lang": "en"},
                headers=self._headers(),
                timeout=self.HTTP_TIMEOUT,
            )
            response.raise_for_status()
            features = response.json().get("features", [])
        except (requests.RequestException, ValueError, AttributeError) as error:
            raise ProviderError(f"Photon request failed: {error}") from error

        results = []
        for feature in features:
            place = self._place(feature)
            if place:
                results.append(place)
            if len(results) >= limit:
                break

        cache.set(key, results, self.CACHE_SECONDS)
        return results

    def _place(self, feature):
        """One Photon feature as a search result (None: outside the Philippines or unusable)."""
        props = feature.get("properties") or {}
        if props.get("countrycode") not in (None, "PH"):
            return None
        try:
            lng, lat = feature["geometry"]["coordinates"][:2]
        except (KeyError, TypeError, ValueError):
            return None
        street = " ".join(part for part in (props.get("housenumber"), props.get("street")) if part)
        name = props.get("name") or street
        if not name:
            return None
        parts = [street, props.get("district") or props.get("locality"), props.get("city") or props.get("county"),
                 props.get("state")]
        address = ", ".join(dict.fromkeys(part for part in parts if part and part != name))
        category = self.category_for({props.get("osm_key"): props.get("osm_value")})
        return {
            "name": name,
            "address": address,
            "lat": round(float(lat), 6),
            "lng": round(float(lng), 6),
            "category": str(category) if category else "",
            "source": "osm",
        }


class NominatimGeocoder(OpenStreetMapClient, Geocoder):
    BASE_URL = "https://nominatim.openstreetmap.org"
    MIN_INTERVAL = 1.0  # seconds between requests (usage policy)

    # Shared by every instance: the 1 request / second limit is for the whole site
    _lock = threading.Lock()
    _last_request = 0.0

    def _get(self, path, params):
        params = {**params, "format": "jsonv2"}
        key = self._cache_key("nominatim", path, sorted(params.items()))
        cached = cache.get(key)
        if cached is not None:
            return cached

        with NominatimGeocoder._lock:
            wait = self.MIN_INTERVAL - (time.monotonic() - NominatimGeocoder._last_request)
            if wait > 0:
                time.sleep(wait)
            try:
                response = requests.get(
                    f"{self.BASE_URL}/{path}",
                    params=params,
                    headers=self._headers(**{"Accept-Language": "en"}),
                    timeout=self.HTTP_TIMEOUT,
                )
                response.raise_for_status()
                data = response.json()
            except (requests.RequestException, ValueError) as error:
                raise ProviderError(f"Nominatim request failed: {error}") from error
            finally:
                NominatimGeocoder._last_request = time.monotonic()

        cache.set(key, data, self.CACHE_SECONDS)
        return data

    def search(self, query, limit=5):
        data = self._get("search", {"q": query, "countrycodes": "ph", "limit": limit})
        if not isinstance(data, list):
            raise ProviderError("Nominatim sent an unexpected answer")
        return [
            {
                "name": item.get("name") or item.get("display_name", "").split(",")[0],
                "address": item.get("display_name", ""),
                "lat": round(float(item["lat"]), 6),
                "lng": round(float(item["lon"]), 6),
                "source": "osm",
            }
            for item in data
        ]

    def reverse(self, point):
        lat, lng = point
        data = self._get("reverse", {"lat": f"{lat:.6f}", "lon": f"{lng:.6f}", "zoom": 18, "addressdetails": 1})
        address = data.get("address", {}) if isinstance(data, dict) else {}

        # Short, renter-friendly address: "Bajada, Davao City"
        locality = address.get("city") or address.get("town") or address.get("municipality") or ""
        district = address.get("suburb") or address.get("neighbourhood") or address.get("quarter") or address.get("village") or ""
        short = ", ".join(part for part in (district, locality) if part)

        return {
            "address": short or data.get("display_name", ""),
            "full_address": data.get("display_name", ""),
            "area": locality,
        }
