from django.test import TestCase
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


class UnpublishedComplexTests(TestCase):
    """Unpublishing a complex shows its units as unpublished, but each unit keeps its own status."""

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


# ------------------------------------------------------------------ features, turnover, required photos

import io as _io

from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from .forms import ComplexForm, UnitForm


def jpg(name="p.jpg"):
    buffer = _io.BytesIO()
    Image.new("RGB", (40, 30), "teal").save(buffer, "JPEG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/jpeg")


class ListingFormTests(TestCase):

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

    def test_unit_needs_two_photos_or_videos(self):
        one = UnitForm(self.unit_data(), {"photos": [jpg()]}, complex_obj=self.complex)
        self.assertFalse(one.is_valid())
        self.assertIn("photos", one.errors)
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
