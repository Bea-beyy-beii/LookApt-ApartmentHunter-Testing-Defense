# core_maps/maps/geo.py
# Pure distance / travel-time classes. No Django imports so they are easy to test.
import math


# Davao City
DEFAULT_CENTER = (7.0731, 125.6128)


class GeoPoint:
    """A latitude / longitude pair that knows how far other points are."""

    EARTH_RADIUS_M = 6_371_000

    def __init__(self, lat, lng):
        self.lat = float(lat)
        self.lng = float(lng)

    def __iter__(self):
        return iter((self.lat, self.lng))

    def distance_to(self, lat, lng):
        """Great-circle (haversine) distance in metres to another point."""
        lat1, lng1, lat2, lng2 = map(math.radians, (self.lat, self.lng, float(lat), float(lng)))
        dlat = lat2 - lat1
        dlng = lng2 - lng1
        a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
        return 2 * self.EARTH_RADIUS_M * math.asin(math.sqrt(a))

    def bounding_box(self, radius_km):
        """(min_lat, max_lat, min_lng, max_lng) square that contains the circle.
        Used as a cheap DB pre-filter before the exact distance check."""
        dlat = math.degrees(radius_km * 1000 / self.EARTH_RADIUS_M)
        dlng = math.degrees(radius_km * 1000 / (self.EARTH_RADIUS_M * math.cos(math.radians(self.lat))))
        return self.lat - dlat, self.lat + dlat, self.lng - dlng, self.lng + dlng


class TravelMode:
    """One way of getting around (walk, commute, drive) and its average speed."""

    # Straight-line distance is shorter than the real road distance.
    # Multiply by this to get a rough road distance.
    ROAD_DETOUR_FACTOR = 1.3
    DEFAULT_KEY = "walking"
    _all = {}

    def __init__(self, key, label, speed_kmh, icon):
        self.key = key
        self.label = label
        self.speed_kmh = speed_kmh      # average door-to-door speed inside a Philippine city
        self.icon = icon
        TravelMode._all[key] = self

    def __str__(self):
        return self.key

    @classmethod
    def get(cls, key):
        """The mode with this key, or the default one for anything unknown."""
        return cls._all.get(key) or cls._all[cls.DEFAULT_KEY]

    @classmethod
    def all(cls):
        return list(cls._all.values())

    @classmethod
    def keys(cls):
        return list(cls._all)

    def minutes_for(self, distance_m):
        """Estimated travel time (whole minutes, min 1) for a straight-line distance."""
        road_km = distance_m * self.ROAD_DETOUR_FACTOR / 1000
        return max(1, round(road_km / self.speed_kmh * 60))

    def radius_for(self, minutes):
        """Inverse of minutes_for: how far (straight-line km) you get in N minutes."""
        return SearchRadius.clamp(self.speed_kmh * (float(minutes) / 60) / self.ROAD_DETOUR_FACTOR)


TravelMode("walking", "Walk", 4.8, "walk")
TravelMode("commute", "Commute", 15, "jeep")       # jeepney / tricycle
TravelMode("driving", "Drive", 25, "car")


class SearchRadius:
    """How far around a pin to look (the map only asks for MIN_KM to MAX_KM)."""

    PRESETS_KM = [1, 3, 5, 10]
    DEFAULT_KM = 3
    MIN_KM = 0.2
    MAX_KM = 20

    def __init__(self, km):
        self.km = km

    @classmethod
    def clamp(cls, km):
        return max(cls.MIN_KM, min(cls.MAX_KM, float(km)))

    @classmethod
    def clamped(cls, km):
        """A radius sent by the map, kept between MIN_KM and MAX_KM."""
        return cls(cls.clamp(km))

    @classmethod
    def for_minutes(cls, minutes, mode):
        """A radius given as a travel time (already clamped), rounded to 0.1 km."""
        return cls(round(mode.radius_for(minutes), 1))

    @property
    def metres(self):
        return self.km * 1000

    @property
    def rings_km(self):
        """Every smaller preset circle plus this one: 5 km -> [1, 3, 5]."""
        return [km for km in self.PRESETS_KM if km < self.km] + [self.km]

    @classmethod
    def presets(cls):
        """Radius chips with time hints, e.g. 1 km -> walk 16 min, commute 5 min, drive 3 min."""
        return [
            {
                "km": km,
                "label": "< 1 km" if km == 1 else f"{km} km",
                "minutes": {mode.key: mode.minutes_for(km * 1000) for mode in TravelMode.all()},
            }
            for km in cls.PRESETS_KM
        ]


class TravelEstimate:
    """Distance from the pin to a place, and how long the trip takes."""

    def __init__(self, distance_m, mode):
        self.distance_m = distance_m
        self.mode = mode

    @property
    def label(self):
        # "350 m" under 1 km, "2.3 km" otherwise
        if self.distance_m < 1000:
            return f"{max(10, round(self.distance_m / 10) * 10)} m"
        return f"{self.distance_m / 1000:.1f} km"

    def as_dict(self):
        return {
            "distance_m": round(self.distance_m),
            "distance_km": round(self.distance_m / 1000, 1),
            "distance_label": self.label,
            "minutes": self.mode.minutes_for(self.distance_m),
            "minutes_by_mode": {mode.key: mode.minutes_for(self.distance_m) for mode in TravelMode.all()},
        }
