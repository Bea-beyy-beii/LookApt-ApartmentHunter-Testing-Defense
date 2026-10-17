# core_renters/tests.py
from django.test import RequestFactory, TestCase
from django.urls import reverse

from core.core_listings.models import Area, Complex, ComplexLandmark, Landmark, SavedListing, Unit
from core.models import Landlord, Renter, User

from .sections import RenterListingsSection


def make_user(username, role, phone, first="Test", last="User"):
    user = User.objects.create_user(
        username=username, password="pw-12345!", first_name=first, last_name=last,
        phone_number=phone, sex="female", role=role,
    )
    (Landlord if role == "landlord" else Renter).objects.create(user=user)
    return user


class ListingsSetup(TestCase):
    """Sunrise (Liza, Davao, 2 units) and Harbor View (Ben, Tagum, near Gaisano Mall)."""

    def setUp(self):
        self.liza = make_user("liza", "landlord", "09111111111", "Liza", "Soberano")
        self.ben = make_user("ben", "landlord", "09111111112", "Ben", "Reyes")
        self.renter = make_user("arem", "renter", "09222222222")
        davao, tagum = Area.objects.create(area_name="Davao City"), Area.objects.create(area_name="Tagum")

        self.sunrise = self.make_complex(self.liza, davao, "Sunrise Residences", lease_term="monthly",
                                         pet_friendly=True, has_parking_space=True, sex_restriction="female_only")
        self.unit(self.sunrise, 1, 6000, bedroom_type="studio", max_occupant=2, air_conditioned=True)
        self.unit(self.sunrise, 2, 9000, bedroom_type="one_bedroom", max_occupant=3, availability="occupied")

        self.harbor = self.make_complex(self.ben, tagum, "Harbor View", lease_term="annual")
        self.unit(self.harbor, 1, 15000, bedroom_type="two_bedroom", max_occupant=5, furnish_level="fully_furnished")

        mall = Landmark.objects.create(name="Gaisano Mall", category="mall", latitude=7.1, longitude=125.6)
        ComplexLandmark.objects.create(complex=self.harbor, landmark=mall, distance_m=500, travel_minutes=3)

        self.client.force_login(self.renter)

    def make_complex(self, landlord, area, name, **kwargs):
        return Complex.objects.create(
            landlord=landlord.landlord, area=area, complex_name=name, address=f"{name} Street",
            complex_description="x", min_price=5000, max_price=20000, status="active",
            approval_status="approved", **kwargs,
        )

    def unit(self, complex_obj, identifier, price, **kwargs):
        defaults = dict(bedroom_type="studio", width_dimension=4, length_dimension=5,
                        furnish_level="unfurnished", max_occupant=2)
        defaults.update(kwargs)
        return Unit.objects.create(complex=complex_obj, identifier=identifier, price=price, **defaults)

    def listings_context(self, **params):
        """The Home tab's cards for ?params (what the dashboard and the search endpoint use)."""
        return RenterListingsSection(self.renter, RequestFactory().get("/", params)).context()

    def names(self, **params):
        context = self.listings_context(**params)
        return sorted(listing.complex_name for listing in context["listings"])



class SearchTests(ListingsSetup):
    """Search bar + Filter by on the renter's Home and Saved Listings."""

    def test_everything_without_a_search(self):
        self.assertEqual(self.names(), ["Harbor View", "Sunrise Residences"])

    def test_search_by_name_area_landmark_and_landlord(self):
        self.assertEqual(self.names(q="sunrise"), ["Sunrise Residences"])
        self.assertEqual(self.names(q="tagum"), ["Harbor View"])
        self.assertEqual(self.names(q="gaisano"), ["Harbor View"])
        self.assertEqual(self.names(q="Liza Soberano"), ["Sunrise Residences"])
        self.assertEqual(self.names(q="street"), ["Harbor View", "Sunrise Residences"])     # address
        self.assertEqual(self.names(q="nowhere"), [])

    def test_property_type_filter(self):
        Complex.objects.filter(pk=self.harbor.pk).update(property_type="dormitory")
        self.assertEqual(self.names(property_type="dormitory"), ["Harbor View"])
        self.assertEqual(self.names(property_type="apartment"), ["Sunrise Residences"])
        self.assertEqual(self.names(property_type="condominium"), [])
        self.assertEqual(self.names(property_type="castle"), ["Harbor View", "Sunrise Residences"])   # ignored

    def test_complex_filters(self):
        self.assertEqual(self.names(lease_term="annual"), ["Harbor View"])
        self.assertEqual(self.names(sex="female_only"), ["Sunrise Residences"])
        self.assertEqual(self.names(pets="1"), ["Sunrise Residences"])
        self.assertEqual(self.names(parking="1", pets="1"), ["Sunrise Residences"])
        self.assertEqual(self.names(cctv="1"), [])

    def test_unit_filters_need_one_matching_unit(self):
        self.assertEqual(self.names(unit_type="two_bedroom"), ["Harbor View"])
        self.assertEqual(self.names(occupants="3"), ["Harbor View", "Sunrise Residences"])
        self.assertEqual(self.names(occupants="4"), ["Harbor View"])
        self.assertEqual(self.names(furnishing="fully_furnished"), ["Harbor View"])
        self.assertEqual(self.names(aircon="1"), ["Sunrise Residences"])
        # Sunrise's 3-person unit is occupied
        self.assertEqual(self.names(occupants="3", available="1"), ["Harbor View"])

    def test_budget_and_card_price(self):
        self.assertEqual(self.names(budget_max="8000"), ["Sunrise Residences"])
        self.assertEqual(self.names(budget_min="8000", budget_max="10000"), ["Sunrise Residences"])
        listings = self.listings_context(budget_min="8000")["listings"]
        sunrise = next(c for c in listings if c.pk == self.sunrise.pk)
        self.assertEqual(sunrise.card_price, 9000)          # the price of the unit that fits the budget
        self.assertEqual(self.names(budget_max="abc"), ["Harbor View", "Sunrise Residences"])   # ignored

    def test_sort_by_price(self):
        context = self.listings_context(sort="price_high")
        self.assertEqual([c.complex_name for c in context["listings"]], ["Harbor View", "Sunrise Residences"])
        context = self.listings_context(sort="price_low")
        self.assertEqual([c.complex_name for c in context["listings"]], ["Sunrise Residences", "Harbor View"])

    def test_endpoint_returns_home_and_saved_cards(self):
        SavedListing.objects.create(renter=self.renter.renter, complex=self.harbor)
        response = self.client.get(reverse("core_renters:search_listings"), {"q": "harbor", "pets": "1"})
        data = response.json()
        self.assertEqual((data["home_count"], data["saved_count"], data["filter_count"]), (0, 0, 1))

        data = self.client.get(reverse("core_renters:search_listings"), {"q": "harbor"}).json()
        self.assertEqual((data["home_count"], data["saved_count"]), (1, 1))
        self.assertIn("Harbor View", data["home_html"])
        self.assertIn("?from=saved", data["saved_html"])

    def test_dashboard_keeps_the_search(self):
        response = self.client.get(reverse("core_renters:dashboard"), {"q": "gaisano", "lease_term": "annual"})
        self.assertContains(response, 'value="gaisano"')
        self.assertContains(response, "1 listing matches")
        self.assertNotContains(response, "Sunrise Residences Street")

    def test_only_renters_and_previews(self):
        self.client.force_login(self.liza)
        self.assertEqual(self.client.get(reverse("core_renters:search_listings")).status_code, 403)
        self.client.logout()
        self.assertEqual(self.client.get(reverse("core_renters:search_listings")).status_code, 403)
        self.client.get(reverse("core_preview:renter"))              # starts a preview session
        self.assertEqual(self.client.get(reverse("core_renters:search_listings")).status_code, 200)


class OtherListingsTabTests(ListingsSetup):
    """The complex page's "Other Listings" tab (and no more "View Landlord Profile")."""

    def test_same_landlords_other_complexes(self):
        other = self.make_complex(self.liza, self.sunrise.area, "Moonlight Homes")
        self.unit(other, 1, 7000)
        self.make_complex(self.liza, self.sunrise.area, "Empty Shell")       # no units: not listed

        response = self.client.get(reverse("core_listings:renter_complex_detail", args=[self.sunrise.pk]))
        self.assertContains(response, 'data-tab="other"')
        self.assertContains(response, "More from Liza Soberano")
        self.assertEqual([c.complex_name for c in response.context["other_listings"]], ["Moonlight Homes"])
        self.assertNotContains(response, "View Landlord Profile")

        response = self.client.get(reverse("core_listings:renter_complex_detail", args=[self.harbor.pk]))
        self.assertContains(response, "No other listings")


class PagesTests(ListingsSetup):

    def test_home_and_saved_grids_are_paged(self):
        response = self.client.get(reverse("core_renters:dashboard"))
        self.assertContains(response, 'data-paginate="9"')       # Home: 9 cards a page
        self.assertContains(response, 'data-paginate="8"')       # Saved Listings: 2 rows of 4
        self.assertContains(response, 'id="home-pager"')
        self.assertContains(response, "data-near-banner-close")
