# core_maps/views.py
from functools import wraps
from django.contrib.auth.views import redirect_to_login
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.views.decorators.http import require_GET
from core.core_listings.models import Complex
from core.core_preview.access import signed_in_or_previewing
import json

from .maps import services
from .maps.categories import category_style
from .maps.geo import haversine_m
from .maps.folium_maps import build_map
from .maps.geo import DEFAULT_RADIUS_KM, clamp_radius, normalize_mode, radius_for_minutes


class BadRequest(ValueError):
    pass


def _point(params, required=True):
    lat, lng = params.get("lat"), params.get("lng")
    if not lat or not lng:
        if required:
            raise BadRequest("lat and lng are required.")
        return None, None
    try:
        lat, lng = float(lat), float(lng)
    except ValueError:
        raise BadRequest("lat and lng must be numbers.")
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        raise BadRequest("lat/lng out of range.")
    return lat, lng


def _radius_and_mode(params):
    """Radius can be given directly (radius_km) or as a travel time (minutes + mode)."""
    mode = normalize_mode(params.get("mode"))
    try:
        if params.get("minutes"):
            return round(radius_for_minutes(float(params["minutes"]), mode), 1), mode
        return clamp_radius(float(params.get("radius_km") or DEFAULT_RADIUS_KM)), mode
    except ValueError:
        raise BadRequest("radius_km / minutes must be numbers.")


def login_or_preview(view):
    """Signed-in users, and visitors trying the renter / landlord preview (core_preview)."""
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not signed_in_or_previewing(request):
            return redirect_to_login(request.get_full_path())
        return view(request, *args, **kwargs)
    return wrapper


def _json_endpoint(view):
    @login_or_preview
    @require_GET
    def wrapper(request, *args, **kwargs):
        try:
            return JsonResponse(view(request, *args, **kwargs))
        except BadRequest as error:
            return JsonResponse({"error": str(error)}, status=400)
    wrapper.__name__ = view.__name__
    return wrapper


# =========================================================
# JSON API
# =========================================================

@_json_endpoint
def landmarks_api(request):
    lat, lng = _point(request.GET)
    radius_km, mode = _radius_and_mode(request.GET)
    landmarks, source = services.nearby_landmarks(lat, lng, radius_km, mode)
    return {"landmarks": landmarks, "source": source, "radius_km": radius_km, "mode": mode}


@_json_endpoint
def complexes_api(request):
    lat, lng = _point(request.GET)
    radius_km, mode = _radius_and_mode(request.GET)
    filters = {
        "min_price": request.GET.get("min_price") or None,
        "max_price": request.GET.get("max_price") or None,
        "sex_restriction": request.GET.get("sex_restriction") or None,
        "pet_friendly": request.GET.get("pet_friendly") == "1",
    }
    for key in ("min_price", "max_price"):
        if filters[key] is not None:
            try:
                filters[key] = float(filters[key])
            except ValueError:
                raise BadRequest(f"{key} must be a number.")
    complexes = services.complexes_near(lat, lng, radius_km, mode, filters)
    return {"complexes": complexes, "radius_km": radius_km, "mode": mode}


@_json_endpoint
def search_api(request):
    return {"results": services.search_place(request.GET.get("q", ""))}


@_json_endpoint
def reverse_api(request):
    lat, lng = _point(request.GET)
    return services.reverse_geocode(lat, lng)


# =========================================================
# FOLIUM MAP (shown in an iframe)
# =========================================================

def _manual_pins(raw, lat, lng, mode, limit=15):
    """Landmarks the landlord added by hand (not saved yet), drawn on the map too.
    ?pins=[{"name", "category", "lat", "lng"}, ...]"""
    try:
        pins = json.loads(raw or "[]")
    except ValueError:
        return []
    items = []
    for pin in pins[:limit] if isinstance(pins, list) else []:
        try:
            name, plat, plng = str(pin["name"])[:120], float(pin["lat"]), float(pin["lng"])
        except (KeyError, TypeError, ValueError):
            continue
        distance_m = haversine_m(lat, lng, plat, plng)
        items.append({"name": name, "lat": plat, "lng": plng, **category_style(pin.get("category")),
                      **services._travel_info(distance_m, mode)})
    return items


@login_or_preview
@require_GET
@xframe_options_sameorigin
def map_frame(request):
    try:
        lat, lng = _point(request.GET, required=False)
        radius_km, mode = _radius_and_mode(request.GET)
    except BadRequest as error:
        return HttpResponse(str(error), status=400)

    kind = request.GET.get("kind", "landlord")
    editable = request.GET.get("editable", "1") == "1"
    show_radius = request.GET.get("show_radius", "1") == "1"
    label = request.GET.get("label", "")[:80] or "Selected Location"

    landmarks, complexes = [], []
    if lat is not None:
        if request.GET.get("complex"):
            # Saved landmarks of an existing property
            complex_obj = get_object_or_404(Complex, pk=request.GET["complex"])
            landmarks = services.complex_landmarks(complex_obj)
        elif kind == "renter":
            complexes = services.complexes_near(lat, lng, radius_km, mode)
        elif kind == "landlord":
            landmarks, _ = services.nearby_landmarks(lat, lng, radius_km, mode)
        if kind == "landlord":
            landmarks = landmarks + _manual_pins(request.GET.get("pins"), lat, lng, mode)

    html = build_map(
        lat, lng,
        radius_km=radius_km if show_radius else None,
        landmarks=landmarks,
        complexes=complexes,
        editable=editable,
        label=label,
    )
    response = HttpResponse(html)
    response["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response
