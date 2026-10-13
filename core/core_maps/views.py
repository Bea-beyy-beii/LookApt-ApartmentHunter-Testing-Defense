# core_maps/views.py
from abc import ABC, abstractmethod

from django.contrib.auth.views import redirect_to_login
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.clickjacking import xframe_options_sameorigin

from core.core_listings.models import Complex
from core.core_preview.access import signed_in_or_previewing

from .maps.folium_maps import LocationMap
from .maps.geo import GeoPoint, SearchRadius, TravelMode
from .maps.services import (
    AddressLookup, ComplexLandmarks, ComplexSearch, LandmarkFinder, ManualPins, PlaceSearch,
)


class BadRequest(ValueError):
    pass


class MapParams:
    """The pin, radius and travel mode sent in a map request's query string."""

    def __init__(self, params):
        self.params = params

    def point(self, required=True):
        """GeoPoint of ?lat=&lng= (None when missing and not required)."""
        lat, lng = self.params.get("lat"), self.params.get("lng")
        if not lat or not lng:
            if required:
                raise BadRequest("lat and lng are required.")
            return None
        try:
            lat, lng = float(lat), float(lng)
        except ValueError:
            raise BadRequest("lat and lng must be numbers.")
        if not (-90 <= lat <= 90 and -180 <= lng <= 180):
            raise BadRequest("lat/lng out of range.")
        return GeoPoint(lat, lng)

    @property
    def mode(self):
        return TravelMode.get(self.params.get("mode"))

    @property
    def radius(self):
        """Radius can be given directly (radius_km) or as a travel time (minutes + mode)."""
        try:
            if self.params.get("minutes"):
                return SearchRadius.for_minutes(float(self.params["minutes"]), self.mode)
            return SearchRadius.clamped(self.params.get("radius_km") or SearchRadius.DEFAULT_KM)
        except ValueError:
            raise BadRequest("radius_km / minutes must be numbers.")

    def price(self, key):
        value = self.params.get(key) or None
        if value is None:
            return None
        try:
            return float(value)
        except ValueError:
            raise BadRequest(f"{key} must be a number.")


class LoginOrPreviewMixin:
    """Signed-in users, and visitors trying the renter / landlord preview (core_preview)."""

    def dispatch(self, request, *args, **kwargs):
        if not signed_in_or_previewing(request):
            return redirect_to_login(request.get_full_path())
        return super().dispatch(request, *args, **kwargs)


class MapView(LoginOrPreviewMixin, View):
    """Base of every map view: GET only, query string read through MapParams."""

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        self.map_params = MapParams(request.GET)


# =========================================================
# JSON API
# =========================================================

class JsonApiView(MapView, ABC):
    """Template method: get() wraps payload() in a JsonResponse (400 on a BadRequest)."""

    def get(self, request, *args, **kwargs):
        try:
            return JsonResponse(self.payload())
        except BadRequest as error:
            return JsonResponse({"error": str(error)}, status=400)

    @abstractmethod
    def payload(self):
        """The dict sent back as JSON."""


class LandmarksApiView(JsonApiView):

    def payload(self):
        point = self.map_params.point()
        radius, mode = self.map_params.radius, self.map_params.mode
        landmarks, source = LandmarkFinder(point, radius, mode).find()
        return {"landmarks": landmarks, "source": source, "radius_km": radius.km, "mode": mode.key}


class ComplexesApiView(JsonApiView):

    def payload(self):
        point = self.map_params.point()
        radius, mode = self.map_params.radius, self.map_params.mode
        filters = {
            "min_price": self.map_params.price("min_price"),
            "max_price": self.map_params.price("max_price"),
            "sex_restriction": self.request.GET.get("sex_restriction") or None,
            "pet_friendly": self.request.GET.get("pet_friendly") == "1",
        }
        complexes = ComplexSearch(point, radius, mode, filters).results()
        return {"complexes": complexes, "radius_km": radius.km, "mode": mode.key}


class SearchApiView(JsonApiView):

    def payload(self):
        return {"results": PlaceSearch(self.request.GET.get("q", "")).results()}


class ReverseApiView(JsonApiView):

    def payload(self):
        return AddressLookup(self.map_params.point()).result()


# =========================================================
# FOLIUM MAP (shown in an iframe)
# =========================================================

class MapLayers:
    """What a map frame shows around its pin. The base shows a complex's saved
    landmarks (?complex=) and nothing else; each kind of map adds its own."""

    def __init__(self, point, radius, mode, params, complex_obj=None):
        self.point = point
        self.radius = radius
        self.mode = mode
        self.params = params
        self.complex = complex_obj

    def landmarks(self):
        if self.complex:
            return ComplexLandmarks(self.complex).as_list()
        return self._found_landmarks()

    def complexes(self):
        return [] if self.complex else self._found_complexes()

    def _found_landmarks(self):
        return []

    def _found_complexes(self):
        return []


class LandlordMapLayers(MapLayers):
    """Landlord map: landmarks around the pin, plus the ones added by hand."""

    def landmarks(self):
        manual = ManualPins(self.params.get("pins"), self.point, self.mode).as_list()
        return super().landmarks() + manual

    def _found_landmarks(self):
        landmarks, _ = LandmarkFinder(self.point, self.radius, self.mode).find()
        return landmarks


class RenterMapLayers(MapLayers):
    """Renter map: listings around the pin."""

    def _found_complexes(self):
        return ComplexSearch(self.point, self.radius, self.mode).results()


@method_decorator(xframe_options_sameorigin, name="get")
class MapFrameView(MapView):
    # Polymorphism: ?kind= picks the layers class, each fills the map its own way
    LAYERS = {"landlord": LandlordMapLayers, "renter": RenterMapLayers}

    def get(self, request, *args, **kwargs):
        try:
            point = self.map_params.point(required=False)
            radius, mode = self.map_params.radius, self.map_params.mode
        except BadRequest as error:
            return HttpResponse(str(error), status=400)

        show_radius = request.GET.get("show_radius", "1") == "1"
        landmarks, complexes = [], []
        if point is not None:
            layers = self._layers(point, radius, mode)
            landmarks, complexes = layers.landmarks(), layers.complexes()

        lat, lng = point if point is not None else (None, None)
        html = LocationMap(
            lat, lng,
            radius_km=radius.km if show_radius else None,
            landmarks=landmarks,
            complexes=complexes,
            editable=request.GET.get("editable", "1") == "1",
            label=request.GET.get("label", "")[:80] or "Selected Location",
        ).render()
        response = HttpResponse(html)
        response["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response

    def _layers(self, point, radius, mode):
        params = self.request.GET
        complex_obj = get_object_or_404(Complex, pk=params["complex"]) if params.get("complex") else None
        layers_class = self.LAYERS.get(params.get("kind", "landlord"), MapLayers)
        return layers_class(point, radius, mode, params, complex_obj)
