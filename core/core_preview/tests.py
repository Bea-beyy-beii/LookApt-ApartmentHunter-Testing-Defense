from django.test import TestCase
from django.urls import reverse

from core.models import Landlord, Renter, User


def make_user(username, role, phone):
    user = User.objects.create_user(username=username, password="pw-12345!", first_name=username.title(),
                                    last_name="Test", phone_number=phone, sex="female", role=role,
                                    email=f"{username}@example.com")
    (Landlord if role == "landlord" else Renter).objects.create(user=user)
    return user


class LandingTests(TestCase):

    def test_landing_is_the_home_page(self):
        response = self.client.get("/")
        self.assertTemplateUsed(response, "core_preview/landing.html")
        self.assertContains(response, reverse("signup"))
        self.assertContains(response, reverse("login"))
        self.assertContains(response, reverse("core_preview:renter"))
        self.assertContains(response, reverse("core_preview:landlord"))
        self.assertContains(response, "lookapt.support@gmail.com")

    def test_signed_in_users_go_to_their_dashboard(self):
        self.client.force_login(make_user("liza", "landlord", "09111111111"))
        self.assertRedirects(self.client.get("/"), reverse("core_landlords:dashboard"), fetch_redirect_response=False)
        self.assertRedirects(self.client.get(reverse("core_preview:renter")), reverse("core_landlords:dashboard"),
                             fetch_redirect_response=False)


class PreviewTests(TestCase):

    def test_renter_preview(self):
        response = self.client.get(reverse("core_preview:renter"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-preview="renter"')
        self.assertContains(response, 'data-preview-tabs="home,findNear"')
        self.assertContains(response, "data-preview-prompt")
        self.assertContains(response, "pv-topbar")                     # Log in / Create an Account, no profile menu
        self.assertNotContains(response, "data-notif-bell")

    def test_landlord_preview(self):
        response = self.client.get(reverse("core_preview:landlord"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-preview-tabs="home,myListings"')
        self.assertContains(response, "Sunrise Residences")            # sample data
        self.assertContains(response, 'name="visibility"')             # the Add Property form is there
        self.assertNotContains(response, "data-verify-banner")         # no verification banner

    def test_locked_tab_in_the_address_opens_home(self):
        response = self.client.get(reverse("core_preview:renter") + "?tab=saved")
        self.assertEqual(response.context["active_tab"], "home")

    def test_map_works_only_after_opening_a_preview(self):
        url = reverse("core_maps:search_api") + "?q="
        self.assertEqual(self.client.get(url).status_code, 302)        # not signed in, no preview
        self.client.get(reverse("core_preview:renter"))
        self.assertEqual(self.client.get(url).status_code, 200)

    def test_sign_up_link_picks_the_role(self):
        response = self.client.get(reverse("signup") + "?role=landlord")
        self.assertContains(response, '<option value="landlord" selected>')
