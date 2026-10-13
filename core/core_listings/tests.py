from django.test import TestCase, override_settings
from django.urls import reverse

from core.core_rentals.services import get_rentals_context
from core.models import Landlord, User

from .models import Area, Complex, Unit


def make_landlord(username="liza", phone="09111111111"):
    user = User.objects.create_user(
        username=username, password="pw-12345!", first_name=username.title(), last_name="Test",
        phone_number=phone, sex="female", role="landlord", is_verified=True,
    )
    Landlord.objects.create(user=user)
    return user


class ListingSetup(TestCase):
    """A landlord with one published complex: units 1 available, 2 occupied, 3 unpublished."""

    def setUp(self):
        self.user = make_landlord()
        self.client.force_login(self.user)
        self.complex = Complex.objects.create(
            landlord=self.user.landlord, area=Area.objects.create(area_name="Davao City"),
            complex_name="Sunrise", address="Poblacion", complex_description="x",
            min_price=5000, max_price=20000, status="active", lease_term="monthly",
        )
        self.available = self.make_unit(1, "available")
        self.occupied = self.make_unit(2, "occupied")
        self.hidden = self.make_unit(3, "unpublished")

    def make_unit(self, identifier, availability):
        return Unit.objects.create(
            complex=self.complex, identifier=identifier, bedroom_type="studio", width_dimension=4,
            length_dimension=5, furnish_level="unfurnished", max_occupant=2, price=8000,
            availability=availability,
        )

    def set_visibility(self, visibility):
        return self.client.post(reverse("core_listings:property_set_visibility", args=[self.complex.pk]),
                                {"visibility": visibility}, HTTP_ACCEPT="application/json")

    def fresh_complex(self):
        return Complex.objects.prefetch_related("units").get(pk=self.complex.pk)



class UnpublishedComplexTests(ListingSetup):
    """Unpublishing a complex shows its units as unpublished, but each unit keeps its own status."""

    def test_units_follow_the_complex_and_come_back_as_they_were(self):
        self.set_visibility("unpublished")
        units = list(self.fresh_complex().units.order_by("identifier"))
        self.assertEqual([u.listed_availability for u in units], ["unpublished"] * 3)
        self.assertEqual([u.availability for u in units], ["available", "occupied", "unpublished"])

        self.set_visibility("active")
        units = list(self.fresh_complex().units.order_by("identifier"))
        self.assertEqual([u.listed_availability for u in units], ["available", "occupied", "unpublished"])

    def test_counts_follow_the_complex(self):
        complex_obj = self.fresh_complex()
        self.assertEqual((complex_obj.available_units, complex_obj.occupied_units, complex_obj.unpublished_units),
                         (1, 1, 1))
        self.set_visibility("unpublished")
        complex_obj = self.fresh_complex()
        self.assertEqual((complex_obj.available_units, complex_obj.occupied_units, complex_obj.unpublished_units),
                         (0, 0, 3))
        self.assertEqual(complex_obj.total_units, 3)

    def test_unit_cards_show_unpublished_and_remember_their_status(self):
        self.set_visibility("unpublished")
        response = self.client.get(reverse("core_landlords:dashboard") + "?tab=myListings")
        self.assertContains(response, 'data-availability="unpublished"\n         data-own-availability="available"')
        self.assertContains(response, 'data-availability="unpublished"\n         data-own-availability="occupied"')
        self.assertContains(response, "Publish the complex to change this unit")

    def test_unit_status_cannot_change_while_the_complex_is_unpublished(self):
        self.set_visibility("unpublished")
        response = self.client.post(reverse("core_listings:unit_set_availability", args=[self.available.pk]),
                                    {"availability": "occupied"}, HTTP_ACCEPT="application/json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("Publish it first", response.json()["error"])
        self.available.refresh_from_db()
        self.assertEqual(self.available.availability, "available")

    def test_manage_rentals_only_shows_published_complexes(self):
        names = lambda: [g["complex"].complex_name for g in get_rentals_context(self.user)["rental_groups"]]
        self.assertEqual(names(), ["Sunrise"])
        self.set_visibility("unpublished")
        self.assertEqual(names(), [])
        self.set_visibility("active")
        self.assertEqual(names(), ["Sunrise"])


class RenterUnpublishTests(ListingSetup):
    """A unit with a renter can't be unpublished, on its own or through its complex."""

    def setUp(self):
        super().setUp()
        from datetime import date
        from core.core_rentals.services import assign_tenant
        assign_tenant(self.available, date.today(), tenant_name="Ana Cruz")    # now occupied with a renter

    def set_availability(self, unit, availability):
        return self.client.post(reverse("core_listings:unit_set_availability", args=[unit.pk]),
                                {"availability": availability}, HTTP_ACCEPT="application/json")

    def test_unit_with_a_renter_cannot_be_unpublished(self):
        response = self.set_availability(self.available, "unpublished")
        self.assertEqual(response.status_code, 400)
        self.assertIn("has a renter", response.json()["error"])
        self.available.refresh_from_db()
        self.assertEqual(self.available.availability, "occupied")

    def test_complex_with_a_renter_cannot_be_unpublished(self):
        response = self.set_visibility("unpublished")
        self.assertEqual(response.status_code, 400)
        self.assertIn("units with renters", response.json()["error"])
        self.assertEqual(self.fresh_complex().status, "active")

    def test_unit_without_a_renter_can_be_unpublished_and_published_again(self):
        self.assertEqual(self.set_availability(self.occupied, "unpublished").json()["availability"], "unpublished")
        self.assertEqual(self.set_availability(self.occupied, "available").json()["availability"], "available")

    def test_unit_or_complex_with_a_renter_cannot_be_deleted(self):
        response = self.client.post(reverse("core_listings:unit_delete", args=[self.available.pk]),
                                    HTTP_ACCEPT="application/json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("can't be deleted", response.json()["error"])
        self.assertTrue(Unit.objects.filter(pk=self.available.pk).exists())

        response = self.client.post(reverse("core_listings:property_delete", args=[self.complex.pk]),
                                    HTTP_ACCEPT="application/json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("units with renters", response.json()["error"])
        self.assertTrue(Complex.objects.filter(pk=self.complex.pk).exists())

        # A unit without a renter can still be deleted
        response = self.client.post(reverse("core_listings:unit_delete", args=[self.occupied.pk]),
                                    HTTP_ACCEPT="application/json")
        self.assertEqual(response.status_code, 200)

    def test_edit_form_cannot_save_it_as_unpublished(self):
        from .forms import ComplexForm, UnitForm
        form = UnitForm({"availability": "unpublished"}, instance=self.available, complex_obj=self.complex)
        self.assertFalse(form.is_valid())
        self.assertIn("has a renter", str(form.non_field_errors()))
        form = ComplexForm({"visibility": "unpublished"}, instance=self.complex)
        self.assertFalse(form.is_valid())
        self.assertIn("units with renters", str(form.non_field_errors()))

    def test_menus_only_have_edit_visibility_and_delete(self):
        response = self.client.get(reverse("core_landlords:dashboard") + "?tab=myListings")
        for gone in ("View Complex", "View Listing", "Set as Occupied", "Set as Available",
                     'href="%s"' % reverse("core_listings:unit_detail", args=[self.available.pk])):
            self.assertNotContains(response, gone)
        self.assertContains(response, "Set as Unpublished")
        self.assertContains(response, "Set as Published")


# ------------------------------------------------------------------ features, turnover, required photos

import io as _io

from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from .forms import ComplexForm, UnitForm


def jpg(name="p.jpg"):
    buffer = _io.BytesIO()
    Image.new("RGB", (40, 30), "teal").save(buffer, "JPEG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/jpeg")


class ListingFormSetup(TestCase):

    def setUp(self):
        self.user = make_landlord()
        self.complex = Complex.objects.create(
            landlord=self.user.landlord, area=Area.objects.create(area_name="Davao City"),
            complex_name="Sunrise", address="Poblacion", complex_description="x",
            min_price=5000, max_price=20000, status="active", lease_term="monthly",
        )

    def complex_data(self, **changes):
        data = {"complex_name": "Moonlight", "complex_description": "Nice", "address": "Matina",
                "latitude": "7.07", "longitude": "125.6", "lease_term": "monthly", "sex_restriction": "any",
                "min_price": "5000", "max_price": "9000", "num_of_floors": "3", "turnover_days": "10",
                "has_cctv": "on", "has_security": "on"}
        data.update(changes)
        return data



class ListingFormTests(ListingFormSetup):

    def test_eight_features_and_turnover_in_the_form(self):
        form = ComplexForm(landlord=self.user.landlord)
        self.assertEqual([f["field"].name for f in form.feature_fields()], list(Complex.FEATURE_LABELS))
        self.assertEqual(len(Complex.FEATURE_LABELS), 8)
        self.assertIn("turnover_days", form.fields)

    def test_complex_needs_two_photos(self):
        one = ComplexForm(self.complex_data(), {"photos": [jpg()]}, landlord=self.user.landlord)
        self.assertFalse(one.is_valid())
        self.assertIn("photos", one.errors)
        two = ComplexForm(self.complex_data(), {"photos": [jpg(), jpg("b.jpg")]}, landlord=self.user.landlord)
        self.assertTrue(two.is_valid(), two.errors)
        self.assertEqual(two.cleaned_data["turnover_days"], 10)
        self.assertTrue(two.cleaned_data["has_cctv"])

    def unit_data(self):
        return {"identifier": "101", "floor": "1", "bedroom_type": "studio", "width_dimension": "4",
                "length_dimension": "5", "max_occupant": "2", "furnish_level": "unfurnished", "price": "8000",
                "advance_months": "1", "deposit_months": "1"}

    def test_unit_needs_two_photos(self):
        one = UnitForm(self.unit_data(), {"photos": [jpg()]}, complex_obj=self.complex)
        self.assertFalse(one.is_valid())
        self.assertIn("photos", one.errors)
        # Videos don't count toward the 2
        mp4 = lambda name: SimpleUploadedFile(name, b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 64, content_type="video/mp4")
        videos_only = UnitForm(self.unit_data(), {"videos": [mp4("a.mp4"), mp4("b.mp4")]}, complex_obj=self.complex)
        self.assertFalse(videos_only.is_valid())
        self.assertIn("photos", videos_only.errors)
        two = UnitForm(self.unit_data(), {"photos": [jpg(), jpg("b.jpg")]}, complex_obj=self.complex)
        self.assertTrue(two.is_valid(), two.errors)

    def test_card_chips_are_complex_features_only(self):
        from core.core_renters.services import get_renter_listings_context
        for key in Complex.FEATURE_LABELS:
            setattr(self.complex, key, True)
        self.complex.save()
        Unit.objects.create(complex=self.complex, identifier=1, bedroom_type="studio", width_dimension=4,
                            length_dimension=5, furnish_level="fully_furnished", max_occupant=2, price=8000,
                            air_conditioned=True, wifi_ready=True)
        [listing] = get_renter_listings_context(None)["listings"]
        self.assertEqual([chip["key"] for chip in listing.card_chips], list(Complex.FEATURE_LABELS)[:4])


@override_settings(STORAGES={
    "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
})
class LandmarksKeptOnSaveTests(ListingFormSetup):
    """Saving the property form must not wipe its landmarks when the map never sent a list."""

    def form(self, **overrides):
        data = {**self.complex_data(), "latitude": "7.06", "longitude": "125.597", **overrides}
        return ComplexForm(data, instance=self.complex, landlord=self.user.landlord)

    def test_blank_list_keeps_landmarks_and_empty_list_clears_them(self):
        from core.core_listings.views import _save_property
        from core.core_maps.maps.services import complex_landmarks, save_complex_landmarks
        self.complex.latitude, self.complex.longitude = 7.06, 125.597
        self.complex.save()
        save_complex_landmarks(self.complex, [{"name": "Gaisano", "category": "mall", "lat": 7.065, "lng": 125.6}], "walking")
        self.complex.pictures.create(image=jpg(), position=0)
        self.complex.pictures.create(image=jpg("b.jpg"), position=1)

        form = self.form(landmarks_json="")
        self.assertTrue(form.is_valid(), form.errors)
        _save_property(form, self.user.landlord)
        self.assertEqual([item["name"] for item in complex_landmarks(self.complex)], ["Gaisano"])

        # Pin moved without a new list: same landmarks, distances from the new spot
        before = complex_landmarks(self.complex)[0]["distance_m"]
        form = self.form(landmarks_json="", latitude="7.07", longitude="125.61")
        self.assertTrue(form.is_valid(), form.errors)
        _save_property(form, self.user.landlord)
        self.assertNotEqual(complex_landmarks(self.complex)[0]["distance_m"], before)

        form = self.form(landmarks_json="[]")
        self.assertTrue(form.is_valid(), form.errors)
        _save_property(form, self.user.landlord)
        self.assertEqual(complex_landmarks(self.complex), [])
