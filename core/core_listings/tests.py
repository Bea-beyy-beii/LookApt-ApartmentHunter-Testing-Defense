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
