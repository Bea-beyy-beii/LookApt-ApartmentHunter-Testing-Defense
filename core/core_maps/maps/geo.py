# core_maps/maps/geo.py
# Pure distance / travel-time helpers. No Django imports so they are easy to test.
import math


EARTH_RADIUS_M = 6_371_000

# Straight-line distance is shorter than the real road distance.
# Multiply by this to get a rough road distance.
ROAD_DETOUR_FACTOR = 1.3

# Average door-to-door speeds inside a Philippine city (km/h)
TRAVEL_MODES = {
    "walking": {"label": "Walk", "speed_kmh": 4.8, "icon": "walk"},
    "commute": {"label": "Commute", "speed_kmh": 15, "icon": "jeep"},   # jeepney / tricycle
    "driving": {"label": "Drive", "speed_kmh": 25, "icon": "car"},
}
DEFAULT_MODE = "walking"

RADIUS_PRESETS_KM = [1, 3, 5, 10]
DEFAULT_RADIUS_KM = 3
MIN_RADIUS_KM = 0.2
MAX_RADIUS_KM = 20

# Davao City
DEFAULT_CENTER = (7.0731, 125.6128)


def normalize_mode(mode):
    return mode if mode in TRAVEL_MODES else DEFAULT_MODE


def clamp_radius(radius_km):
    return max(MIN_RADIUS_KM, min(MAX_RADIUS_KM, float(radius_km)))


def haversine_m(lat1, lng1, lat2, lng2):
    """Great-circle distance in metres between two points."""
    lat1, lng1, lat2, lng2 = map(math.radians, (float(lat1), float(lng1), float(lat2), float(lng2)))
    dlat = lat2 - lat1
    dlng = lng2 - lng1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def bounding_box(lat, lng, radius_km):
    """(min_lat, max_lat, min_lng, max_lng) square that contains the circle.
    Used as a cheap DB pre-filter before the exact haversine check."""
    lat = float(lat)
    lng = float(lng)
    dlat = math.degrees(radius_km * 1000 / EARTH_RADIUS_M)
    dlng = math.degrees(radius_km * 1000 / (EARTH_RADIUS_M * math.cos(math.radians(lat))))
    return lat - dlat, lat + dlat, lng - dlng, lng + dlng


def estimate_minutes(distance_m, mode):
    """Estimated travel time (whole minutes, min 1) for a straight-line distance."""
    speed_kmh = TRAVEL_MODES[normalize_mode(mode)]["speed_kmh"]
    road_km = distance_m * ROAD_DETOUR_FACTOR / 1000
    return max(1, round(road_km / speed_kmh * 60))


def radius_for_minutes(minutes, mode):
    """Inverse of estimate_minutes: how far (straight-line km) you get in N minutes."""
    speed_kmh = TRAVEL_MODES[normalize_mode(mode)]["speed_kmh"]
    return clamp_radius(speed_kmh * (float(minutes) / 60) / ROAD_DETOUR_FACTOR)


def radius_presets():
    """Radius chips with time hints, e.g. 1 km -> walk 16 min, commute 5 min, drive 3 min."""
    presets = []
    for km in RADIUS_PRESETS_KM:
        presets.append({
            "km": km,
            "label": "< 1 km" if km == 1 else f"{km} km",
            "minutes": {mode: estimate_minutes(km * 1000, mode) for mode in TRAVEL_MODES},
        })
    return presets
