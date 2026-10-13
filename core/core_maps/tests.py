# core_maps/tests.py
from decimal import Decimal
from unittest import mock

import requests
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from core.core_listings.models import Area, Complex, ComplexLandmark, Landmark
from core.models import Landlord, User

from .maps.geo import GeoPoint, SearchRadius, TravelMode
from .maps.providers import Geocoder, LandmarkSource, LocalProvider, NominatimGeocoder, OverpassProvider, PhotonGeocoder
from .maps.services import ComplexLandmarks, ComplexSearch, LandmarkFinder, PlaceSearch

MAPUA = (7.0588, 125.5962)


def nearby_landmarks(lat, lng, radius_km, mode):
    return LandmarkFinder(GeoPoint(lat, lng), SearchRadius(radius_km), mode).find()


def overpass_down(*args, **kwargs):
    raise requests.ConnectionError("offline")


class GeoTests(TestCase):

    def test_haversine_one_degree_latitude(self):
        self.assertAlmostEqual(GeoPoint(0, 0).distance_to(1, 0), 111_195, delta=50)

    def test_estimates_follow_transport_mode(self):
        # 1 km straight line -> 1.3 km road
        self.assertEqual(TravelMode.get("walking").minutes_for(1000), 16)
        self.assertEqual(TravelMode.get("driving").minutes_for(1000), 3)
        self.assertLess(TravelMode.get("commute").minutes_for(1000), TravelMode.get("walking").minutes_for(1000))

    def test_radius_for_minutes_is_inverse(self):
        walking = TravelMode.get("walking")
        km = walking.radius_for(30)
        self.assertAlmostEqual(walking.minutes_for(km * 1000), 30, delta=1)

    def test_unknown_mode_falls_back_to_walking(self):
        self.assertEqual(TravelMode.get("teleport").key, "walking")

    def test_radius_is_clamped(self):
        self.assertEqual(SearchRadius.clamped(500).km, SearchRadius.MAX_KM)
        self.assertEqual(SearchRadius.clamped(0).km, SearchRadius.MIN_KM)

    def test_bounding_box_contains_circle(self):
        mapua = GeoPoint(*MAPUA)
        min_lat, max_lat, min_lng, max_lng = mapua.bounding_box(3)
        self.assertGreater(mapua.distance_to(max_lat, MAPUA[1]), 2990)
        self.assertGreater(mapua.distance_to(MAPUA[0], max_lng), 2990)


class ProviderTests(TestCase):

    def test_providers_share_abstract_interfaces(self):
        for geocoder in (PhotonGeocoder, NominatimGeocoder, LocalProvider):
            self.assertTrue(issubclass(geocoder, Geocoder))
        for source in (OverpassProvider, LocalProvider):
            self.assertTrue(issubclass(source, LandmarkSource))
        with self.assertRaises(TypeError):
            Geocoder()


class OverpassParsingTests(TestCase):

    def test_parse_maps_tags_and_skips_unnamed(self):
        payload = {"elements": [
            {"type": "node", "id": 1, "lat": 7.06, "lon": 125.6, "tags": {"amenity": "university", "name": "Mapúa MCM"}},
            {"type": "way", "id": 2, "center": {"lat": 7.07, "lon": 125.61}, "tags": {"shop": "mall", "name": "SM"}},
            {"type": "node", "id": 3, "lat": 7.0, "lon": 125.0, "tags": {"amenity": "school"}},
            {"type": "node", "id": 4, "lat": 7.0, "lon": 125.0, "tags": {"amenity": "bench", "name": "x"}},
        ]}
        results = OverpassProvider().parse(payload)
        self.assertEqual([(r["name"], r["category"]) for r in results], [("Mapúa MCM", "school"), ("SM", "mall")])

    def test_query_limits_restaurants_to_small_radius(self):
        query = OverpassProvider().build_query(7.0, 125.0, 5000)
        self.assertIn("around:5000", query)
        self.assertIn("around:1500", query)


class MapSetup(TestCase):
    """A landlord, Mapúa and a far airport in the Landmark table."""

    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(
            username="land.lord", password="pw-12345!", first_name="Land", last_name="Lord",
            phone_number="09123456789", sex="female", role="landlord",
        )
        self.landlord = Landlord.objects.create(user=self.user)
        self.area = Area.objects.create(area_name="Davao City")
        Landmark.objects.create(name="Mapúa Malayan Colleges Mindanao", category="school", latitude=MAPUA[0], longitude=MAPUA[1])
        Landmark.objects.create(name="Far Airport", category="airport", latitude=7.1255, longitude=125.6458)

    def make_complex(self, name, lat, lng, **kwargs):
        defaults = dict(
            landlord=self.landlord, area=self.area, complex_name=name, address="Matina",
            latitude=Decimal(str(lat)), longitude=Decimal(str(lng)), complex_description="d",
            min_price=5000, max_price=8000,
            status=Complex.ComplexStatus.ACTIVE, approval_status=Complex.Approval.APPROVED,
        )
        defaults.update(kwargs)
        return Complex.objects.create(**defaults)



class ServiceTests(MapSetup):

    @mock.patch("core.core_maps.maps.providers.requests.post", side_effect=overpass_down)
    def test_nearby_landmarks_falls_back_to_local(self, _post):
        landmarks, source = nearby_landmarks(7.0600, 125.5970, 1, "walking")
        self.assertEqual(source, "offline")
        self.assertEqual([l["name"] for l in landmarks], ["Mapúa Malayan Colleges Mindanao"])
        self.assertEqual(landmarks[0]["label"], "School")
        self.assertIn("minutes_by_mode", landmarks[0])

    @mock.patch("core.core_maps.maps.providers.requests.post")
    def test_nearby_landmarks_merges_osm_results(self, post):
        post.return_value.json.return_value = {"elements": [
            {"type": "node", "id": 9, "lat": 7.0610, "lon": 125.5975, "tags": {"amenity": "hospital", "name": "Clinic A"}},
        ]}
        landmarks, source = nearby_landmarks(7.0600, 125.5970, 1, "driving")
        self.assertEqual(source, "live")
        self.assertEqual({l["name"] for l in landmarks}, {"Mapúa Malayan Colleges Mindanao", "Clinic A"})

    @override_settings(LISTINGS_REQUIRE_APPROVAL=True)
    def test_complexes_near_filters_by_radius_and_visibility(self):
        near = self.make_complex("Near", 7.0600, 125.5970)                       # ~0.2 km
        self.make_complex("Mid", 7.0800, 125.5962)                               # ~2.4 km
        self.make_complex("Pending", 7.0590, 125.5960, approval_status=Complex.Approval.PENDING)
        self.make_complex("Unpublished", 7.0590, 125.5965, status=Complex.ComplexStatus.UNPUBLISHED)

        within_1km = ComplexSearch(GeoPoint(*MAPUA), SearchRadius(1), "walking").results()
        self.assertEqual([c["id"] for c in within_1km], [str(near.pk)])

        within_3km = ComplexSearch(GeoPoint(*MAPUA), SearchRadius(3), "walking").results()
        self.assertEqual([c["name"] for c in within_3km], ["Near", "Mid"])

    def test_save_complex_landmarks_recomputes_distance(self):
        complex_obj = self.make_complex("Near", 7.0600, 125.5970)
        saved = ComplexLandmarks(complex_obj).replace([
            {"name": "Mapúa Malayan Colleges Mindanao", "category": "school", "lat": MAPUA[0], "lng": MAPUA[1]},
            {"name": "bad", "category": "not-a-category", "lat": 1, "lng": 1},
            {"name": "", "category": "school", "lat": 1, "lng": 1},
        ], "walking")
        self.assertEqual(len(saved), 1)
        link = ComplexLandmark.objects.get(complex=complex_obj)
        self.assertAlmostEqual(link.distance_m, 160, delta=40)
        self.assertEqual(link.travel_mode, "walking")
        # Reuses the existing Landmark instead of duplicating it
        self.assertEqual(Landmark.objects.filter(name__startswith="Mapúa").count(), 1)


class ApiTests(TestCase):

    def setUp(self):
        cache.clear()
        user = User.objects.create_user(
            username="rent.er", password="pw-12345!", first_name="Rent", last_name="Er",
            phone_number="09987654321", sex="male", role="renter",
        )
        self.client.force_login(user)

    def test_requires_login(self):
        self.client.logout()
        response = self.client.get(reverse("core_maps:complexes_api"), {"lat": 7, "lng": 125})
        self.assertEqual(response.status_code, 302)

    def test_bad_coordinates_return_400(self):
        response = self.client.get(reverse("core_maps:complexes_api"), {"lat": 200, "lng": 125})
        self.assertEqual(response.status_code, 400)
        response = self.client.get(reverse("core_maps:landmarks_api"), {"lat": "abc", "lng": 125})
        self.assertEqual(response.status_code, 400)

    def test_minutes_converted_to_radius(self):
        response = self.client.get(reverse("core_maps:complexes_api"), {"lat": 7.06, "lng": 125.6, "minutes": 10, "mode": "driving"})
        self.assertEqual(response.status_code, 200)
        self.assertAlmostEqual(response.json()["radius_km"], TravelMode.get("driving").radius_for(10), places=1)

    @mock.patch("core.core_maps.maps.providers.requests.get", side_effect=requests.ConnectionError("offline"))
    def test_search_uses_local_landmarks(self, _get):
        Landmark.objects.create(name="Mapúa Malayan Colleges Mindanao", category="school", latitude=MAPUA[0], longitude=MAPUA[1])
        response = self.client.get(reverse("core_maps:search_api"), {"q": "mapua"})
        self.assertEqual(response.json()["results"][0]["lat"], MAPUA[0])

    @mock.patch("core.core_maps.maps.providers.requests.post", side_effect=overpass_down)
    def test_frame_renders_folium_map(self, _post):
        response = self.client.get(reverse("core_maps:frame"), {"lat": 7.06, "lng": 125.6, "radius_km": 3, "kind": "landlord"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["X-Frame-Options"], "SAMEORIGIN")
        html = response.content.decode()
        self.assertIn("L.circle", html)
        self.assertIn("lookapt:map-click", html)


# ------------------------------------------------------------------ speed, search, manual landmarks

def overpass_reply(*elements):
    response = mock.Mock()
    response.json.return_value = {"elements": list(elements)}
    response.raise_for_status.return_value = None
    return response


CLINIC = {"type": "node", "id": 9, "lat": 7.0610, "lon": 125.5975, "tags": {"amenity": "hospital", "name": "Clinic A"}}


class SpeedTests(MapSetup):
    """Fewer, faster calls to OpenStreetMap."""

    def test_overpass_rings_go_in_one_request_and_are_cached(self):
        with mock.patch("core.core_maps.maps.providers.requests.post", return_value=overpass_reply(CLINIC)) as post:
            nearby_landmarks(7.06, 125.597, 5, "walking")       # rings 1, 3 and 5 km
            self.assertEqual(post.call_count, 1)
            query = post.call_args.kwargs["data"]["data"]
            for radius in ("around:1000", "around:3000", "around:5000"):
                self.assertIn(radius, query)
            nearby_landmarks(7.06, 125.597, 5, "driving")       # same place: cached
            self.assertEqual(post.call_count, 1)

    def test_a_failing_server_moves_on_to_the_next(self):
        replies = [requests.ConnectionError("down"), overpass_reply(CLINIC)]
        with mock.patch("core.core_maps.maps.providers.requests.post", side_effect=replies) as post:
            landmarks, source = nearby_landmarks(7.06, 125.597, 1, "walking")
        self.assertEqual(source, "live")
        self.assertIn("Clinic A", [item["name"] for item in landmarks])
        self.assertEqual(post.call_count, 2)
        self.assertNotEqual(post.call_args_list[0].args[0], post.call_args_list[1].args[0])

    def test_shown_landmarks_are_remembered_for_search(self):
        with mock.patch("core.core_maps.maps.providers.requests.post", return_value=overpass_reply(CLINIC)):
            nearby_landmarks(7.06, 125.597, 1, "walking")
            nearby_landmarks(7.06, 125.597, 3, "walking")       # no duplicates
        self.assertEqual(Landmark.objects.filter(name="Clinic A").count(), 1)
        with mock.patch("core.core_maps.maps.providers.requests.get", side_effect=requests.ConnectionError("offline")):
            self.assertEqual(PlaceSearch("clinic a").results()[0]["name"], "Clinic A")

    def test_frame_only_loads_leaflet(self):
        from .maps.folium_maps import LocationMap
        html = LocationMap(7.06, 125.6, radius_km=3).render()
        self.assertIn("leaflet.js", html)
        for heavy in ("bootstrap", "jquery", "fontawesome", "awesome-markers"):
            self.assertNotIn(heavy, html)
        self.assertIn("lookapt:scan", html)          # the radar sweep listens for the parent page
        # Apartment pop-ups (renter map) are built with jQuery
        complex_item = {"name": "Sunrise", "address": "Matina", "lat": 7.061, "lng": 125.601, "min_price": 5000,
                        "max_price": 8000, "distance_label": "200 m", "minutes": 3}
        self.assertIn("jquery", LocationMap(7.06, 125.6, radius_km=3, complexes=[complex_item]).render())


def photon_reply(*features):
    response = mock.Mock()
    response.json.return_value = {"type": "FeatureCollection", "features": list(features)}
    response.raise_for_status.return_value = None
    return response


def photon_feature(name, lat, lng, country="PH", **props):
    return {"geometry": {"coordinates": [lng, lat]},
            "properties": {"name": name, "countrycode": country, "city": "Davao City", **props}}


class SearchTests(TestCase):

    def setUp(self):
        cache.clear()

    def test_local_search_matches_every_word_in_any_order(self):
        Landmark.objects.create(name="Jose Maria College Foundation", category="school", latitude=7.12, longitude=125.66)
        with mock.patch("core.core_maps.maps.providers.requests.get", side_effect=requests.ConnectionError("offline")):
            self.assertEqual(PlaceSearch("college jose").results()[0]["name"], "Jose Maria College Foundation")
            self.assertEqual(PlaceSearch("jose maria").results()[0]["category"], "school")

    def test_photon_finds_half_typed_names_in_the_philippines(self):
        reply = photon_reply(
            photon_feature("Philippine Nikkei Jin Kai International School", 7.09, 125.50,
                           osm_key="amenity", osm_value="school", district="Mintal"),
            photon_feature("Nikkei Tokyo", 35.6, 139.7, country="JP"),
        )
        with mock.patch("core.core_maps.maps.providers.requests.get", return_value=reply) as get:
            results = PlaceSearch("nikkei jin").results()
        self.assertEqual([r["name"] for r in results], ["Philippine Nikkei Jin Kai International School"])
        self.assertEqual(results[0]["category"], "school")
        self.assertEqual(results[0]["address"], "Mintal, Davao City")
        self.assertIn("photon", get.call_args.args[0])

    def test_nominatim_is_the_backup(self):
        nominatim = mock.Mock()
        nominatim.json.return_value = [{"name": "Karwasan ni Sikoy", "display_name": "Karwasan ni Sikoy, Davao City",
                                        "lat": "7.07", "lon": "125.61"}]
        nominatim.raise_for_status.return_value = None
        with mock.patch("core.core_maps.maps.providers.time.sleep"), \
             mock.patch("core.core_maps.maps.providers.requests.get",
                        side_effect=[requests.ConnectionError("photon down"), nominatim]):
            results = PlaceSearch("karwasan").results()
        self.assertEqual(results[0]["name"], "Karwasan ni Sikoy")


class ManualLandmarkTests(MapSetup):

    def test_manual_flag_is_saved_and_returned(self):
        complex_obj = self.make_complex("Near", 7.0600, 125.5970)
        ComplexLandmarks(complex_obj).replace([
            {"name": "Karwasan ni Sikoy", "category": "restaurant", "lat": 7.0605, "lng": 125.5972, "manual": True},
            {"name": "Mapúa Malayan Colleges Mindanao", "category": "school", "lat": MAPUA[0], "lng": MAPUA[1]},
        ], "walking")
        saved = {item["name"]: item["manual"] for item in ComplexLandmarks(complex_obj).as_list()}
        self.assertEqual(saved, {"Karwasan ni Sikoy": True, "Mapúa Malayan Colleges Mindanao": False})

    def test_frame_draws_unsaved_manual_pins(self):
        self.client.force_login(self.user)
        pins = '[{"name": "Karwasan ni Sikoy", "category": "restaurant", "lat": 7.0605, "lng": 125.5972}]'
        with mock.patch("core.core_maps.maps.providers.requests.post", side_effect=overpass_down):
            html = self.client.get(reverse("core_maps:frame"), {"lat": 7.06, "lng": 125.597, "kind": "landlord",
                                                                "pins": pins}).content.decode()
        self.assertIn("Karwasan ni Sikoy", html)

    def test_refresh_landmarks_fills_complexes_without_any(self):
        from django.core.management import call_command
        empty = self.make_complex("Empty", 7.0600, 125.5970)
        with mock.patch("core.core_maps.maps.providers.requests.post", return_value=overpass_reply(CLINIC)):
            call_command("refresh_landmarks", stdout=mock.Mock(), stderr=mock.Mock())
        self.assertIn("Clinic A", [item["name"] for item in ComplexLandmarks(empty).as_list()])


class FrameAndTagTests(MapSetup):

    def test_renter_frame_draws_complexes(self):
        self.make_complex("Sunrise Residences", 7.0600, 125.5970)
        self.client.force_login(self.user)
        response = self.client.get(reverse("core_maps:frame"), {"lat": 7.06, "lng": 125.597, "kind": "renter"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("Sunrise Residences", response.content.decode())

    def test_map_views_only_answer_get(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.post(reverse("core_maps:frame")).status_code, 405)
        self.assertEqual(self.client.post(reverse("core_maps:search_api")).status_code, 405)

    def test_location_picker_tag(self):
        from django.template import Context, Template
        html = Template('{% load core_maps %}{% location_picker kind="renter" mode="driving" height=200 %}').render(Context())
        self.assertIn('data-kind="renter"', html)
        self.assertIn('data-mode="driving"', html)
        self.assertIn("Commute", html)
