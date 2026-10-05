# core_maps/maps/services.py
# Business logic for the map feature:
#   - landlords: pin a point -> nearby landmarks (with distance + travel time)
#   - renters:   pin a point -> complexes within the radius
import logging
import unicodedata

from django.db import transaction

from core.core_listings.models import Area, Complex, ComplexLandmark, Landmark

from .categories import category_style
from .geo import TRAVEL_MODES, bounding_box, estimate_minutes, haversine_m, normalize_mode
from .providers import LocalProvider, NominatimGeocoder, OverpassProvider, ProviderError

from core.core_listings.services import renter_visible_complexes

logger = logging.getLogger(__name__)

DEFAULT_AREA_NAME = "Davao City"
MAX_SAVED_LANDMARKS = 30


def _travel_info(distance_m, mode):
    return {
        "distance_m": round(distance_m),
        "distance_km": round(distance_m / 1000, 1),
        # "350 m" under 1 km, "2.3 km" otherwise
        "distance_label": f"{max(10, round(distance_m / 10) * 10)} m" if distance_m < 1000 else f"{distance_m / 1000:.1f} km",
        "minutes": estimate_minutes(distance_m, mode),
        "minutes_by_mode": {m: estimate_minutes(distance_m, m) for m in TRAVEL_MODES},
    }


# =========================================================
# LANDMARKS (landlord side)
# =========================================================

def nearby_landmarks(lat, lng, radius_km, mode, per_category=3, limit=40):
    """Landmarks around a point, nearest first, at most `per_category` per category.

    Returns (landmarks, source) where source is "live" (OpenStreetMap) or
    "offline" (only our own Landmark table, because Overpass was unreachable).
    """
    mode = normalize_mode(mode)
    radius_m = radius_km * 1000

    candidates = LocalProvider().fetch(lat, lng, radius_m)
    source = "live"
    try:
        candidates += OverpassProvider().fetch(lat, lng, radius_m)
    except ProviderError as error:
        logger.warning("Falling back to local landmarks: %s", error)
        source = "offline"

    # Keep the nearest copy of each (name, category)
    best = {}
    for item in candidates:
        distance_m = haversine_m(lat, lng, item["lat"], item["lng"])
        if distance_m > radius_m:
            continue
        key = (item["name"].lower(), item["category"])
        if key not in best or distance_m < best[key]["distance_m"]:
            best[key] = {**item, **category_style(item["category"]), **_travel_info(distance_m, mode)}

    ordered = sorted(best.values(), key=lambda item: item["distance_m"])

    per_category_count = {}
    results = []
    for item in ordered:
        count = per_category_count.get(item["category"], 0)
        if count >= per_category:
            continue
        per_category_count[item["category"]] = count + 1
        results.append(item)
        if len(results) >= limit:
            break

    return results, source


@transaction.atomic
def save_complex_landmarks(complex_obj, landmarks, mode):
    """Replace a complex's landmarks with the ones the landlord kept.

    `landmarks` is the list sent by the wizard: [{name, category, lat, lng}, ...]
    Distances/times are recomputed here from the saved complex coordinates,
    the browser values are never trusted.
    """
    mode = normalize_mode(mode)
    ComplexLandmark.objects.filter(complex=complex_obj).delete()

    if complex_obj.latitude is None or complex_obj.longitude is None:
        return []

    valid_categories = set(Landmark.LandmarkTypes.values)
    saved = []

    for item in landmarks[:MAX_SAVED_LANDMARKS]:
        try:
            name = str(item["name"]).strip()[:200]
            category = item.get("category")
            lat = round(float(item["lat"]), 6)
            lng = round(float(item["lng"]), 6)
        except (KeyError, TypeError, ValueError):
            continue

        if not name or category not in valid_categories or not (-90 <= lat <= 90 and -180 <= lng <= 180):
            continue

        landmark, _ = Landmark.objects.get_or_create(
            name=name, category=category, latitude=lat, longitude=lng,
        )

        distance_m = haversine_m(complex_obj.latitude, complex_obj.longitude, lat, lng)
        link, _ = ComplexLandmark.objects.update_or_create(
            complex=complex_obj,
            landmark=landmark,
            travel_mode=mode,
            defaults={
                "distance_m": round(distance_m),
                "travel_minutes": estimate_minutes(distance_m, mode),
            },
        )
        saved.append(link)

    return saved


def complex_landmarks(complex_obj):
    """Saved landmarks of a complex, formatted like nearby_landmarks()."""
    links = (
        ComplexLandmark.objects
        .filter(complex=complex_obj)
        .select_related("landmark")
        .order_by("distance_m")
    )
    return [
        {
            "name": link.landmark.name,
            "lat": float(link.landmark.latitude),
            "lng": float(link.landmark.longitude),
            "travel_mode": link.travel_mode,
            **category_style(link.landmark.category),
            **_travel_info(link.distance_m, link.travel_mode),
        }
        for link in links
    ]


# =========================================================
# COMPLEXES (renter side)
# =========================================================

def searchable_complexes():
    """Only listings renters are allowed to see (and that have a map pin)."""
    return renter_visible_complexes().filter(latitude__isnull=False, longitude__isnull=False)


def complexes_near(lat, lng, radius_km, mode, filters=None):
    mode = normalize_mode(mode)
    filters = filters or {}
    radius_m = radius_km * 1000
    min_lat, max_lat, min_lng, max_lng = bounding_box(lat, lng, radius_km)

    queryset = (
        searchable_complexes()
        .filter(latitude__range=(min_lat, max_lat), longitude__range=(min_lng, max_lng))
        .select_related("area")
        .prefetch_related("pictures")
    )

    if filters.get("max_price"):
        queryset = queryset.filter(min_price__lte=filters["max_price"])
    if filters.get("min_price"):
        queryset = queryset.filter(max_price__gte=filters["min_price"])
    if filters.get("sex_restriction"):
        queryset = queryset.filter(sex_restriction__in=[filters["sex_restriction"], "any"])
    if filters.get("pet_friendly"):
        queryset = queryset.filter(pet_friendly=True)

    results = []
    for complex_obj in queryset:
        distance_m = haversine_m(lat, lng, complex_obj.latitude, complex_obj.longitude)
        if distance_m > radius_m:
            continue

        cover = next((p for p in complex_obj.pictures.all() if p.is_cover), None) or next(iter(complex_obj.pictures.all()), None)

        results.append({
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
            **_travel_info(distance_m, mode),
        })

    results.sort(key=lambda item: item["distance_m"])
    return results


# =========================================================
# PLACES / ADDRESSES
# =========================================================

def search_place(query, limit=6):
    """Text search for a point, e.g. "Mapua" -> Mapúa Malayan Colleges Mindanao.
    Our own Landmark table first (fast, works offline), then OpenStreetMap."""
    query = (query or "").strip()
    if len(query) < 2:
        return []

    results = [
        {
            "name": landmark.name,
            "address": landmark.get_category_display(),
            "lat": float(landmark.latitude),
            "lng": float(landmark.longitude),
            "source": "local",
        }
        for landmark in _local_landmark_matches(query, limit)
    ]

    if len(results) < limit:
        try:
            results += NominatimGeocoder().search(query, limit=limit - len(results))
        except ProviderError as error:
            logger.warning("Place search fell back to local results: %s", error)

    seen = set()
    unique = []
    for item in results:
        key = (item["name"].lower(), round(item["lat"], 3), round(item["lng"], 3))
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique[:limit]


def _fold(text):
    """Lowercase and strip accents so "mapua" matches "Mapúa"."""
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c)).casefold()


def _local_landmark_matches(query, limit):
    matches = list(Landmark.objects.filter(name__icontains=query)[:limit])
    if len(matches) < limit:
        folded = _fold(query)
        seen = {m.pk for m in matches}
        for landmark in Landmark.objects.only("landmark_id", "name", "category", "latitude", "longitude").iterator():
            if landmark.pk not in seen and folded in _fold(landmark.name):
                matches.append(landmark)
                if len(matches) >= limit:
                    break
    return matches


def reverse_geocode(lat, lng):
    try:
        return NominatimGeocoder().reverse(lat, lng)
    except ProviderError as error:
        logger.warning("Reverse geocoding failed: %s", error)
        return {"address": "", "full_address": "", "area": ""}


def resolve_area(area_name):
    name = (area_name or "").strip() or DEFAULT_AREA_NAME
    area, _ = Area.objects.get_or_create(area_name=name)
    return area
