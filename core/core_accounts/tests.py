from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.core_inquiries.services import start_or_continue_inquiry
from core.core_listings.models import Area, Complex, Unit
from core.models import Landlord, Renter, User


def make_user(username, role, phone, **extra):
    user = User.objects.create_user(
        username=username, password="pw-12345!", first_name=username.title(), last_name="Test",
        phone_number=phone, sex="female", role=role, **extra,
    )
    (Landlord if role == "landlord" else Renter).objects.create(user=user)
    return user


class TopBarTests(TestCase):
    """Dark mode switch, notification bell and profile menu."""

    def setUp(self):
        self.landlord = make_user("liza", "landlord", "09111111111", is_verified=True)
        self.renter = make_user("arem", "renter", "09222222222")
        area = Area.objects.create(area_name="Davao City")
        complex_obj = Complex.objects.create(
            landlord=self.landlord.landlord, area=area, complex_name="Sunrise", address="Poblacion",
            complex_description="x", min_price=5000, max_price=9000, status="active",
        )
        self.unit = Unit.objects.create(
            complex=complex_obj, identifier=1, bedroom_type="studio", width_dimension=4,
            length_dimension=5, furnish_level="unfurnished", max_occupant=2, price=8000,
        )

    # ---------- dark mode ----------

    def test_theme_switch_saves_on_the_account(self):
        self.client.force_login(self.renter)
        response = self.client.post(reverse("account_theme"), {"theme": "dark"})
        self.assertEqual(response.json(), {"theme": "dark"})
        self.renter.refresh_from_db()
        self.assertEqual(self.renter.theme, "dark")

        page = self.client.get(reverse("core_renters:dashboard"))
        self.assertContains(page, 'data-theme="dark"')
        self.assertContains(page, 'aria-checked="true"')

    def test_theme_switch_rejects_unknown_values_and_get(self):
        self.client.force_login(self.renter)
        self.assertEqual(self.client.post(reverse("account_theme"), {"theme": "neon"}).status_code, 400)
        self.assertEqual(self.client.get(reverse("account_theme")).status_code, 405)
        self.renter.refresh_from_db()
        self.assertEqual(self.renter.theme, "light")

    def test_new_accounts_start_light(self):
        self.client.force_login(self.landlord)
        self.assertContains(self.client.get(reverse("core_landlords:dashboard")), 'data-theme="light"')

    def test_endpoints_need_login(self):
        for name in ("account_theme", "account_notifications_seen"):
            self.assertEqual(self.client.post(reverse(name)).status_code, 302)
        self.assertEqual(self.client.get(reverse("account_notifications")).status_code, 302)

    # ---------- bell ----------

    def test_bell_shows_new_until_opened(self):
        start_or_continue_inquiry(self.renter, "Is it still available?", unit=self.unit)
        self.client.force_login(self.landlord)

        data = self.client.get(reverse("account_notifications")).json()
        self.assertEqual(data["new_count"], 1)
        self.assertIn("New message", data["html"])
        self.assertIn("?tab=inquiries", data["html"])      # landlord's own dashboard

        self.assertEqual(self.client.post(reverse("account_notifications_seen")).status_code, 200)
        data = self.client.get(reverse("account_notifications")).json()
        self.assertEqual(data["new_count"], 0)
        self.assertIn("New message", data["html"])         # still listed, just not new

    def test_only_newer_notifications_count_after_opening(self):
        self.landlord.notifications_seen_at = timezone.now() - timedelta(hours=1)
        self.landlord.save(update_fields=["notifications_seen_at"])
        start_or_continue_inquiry(self.renter, "Hello!", unit=self.unit)
        self.client.force_login(self.landlord)
        self.assertEqual(self.client.get(reverse("account_notifications")).json()["new_count"], 1)

    def test_empty_bell(self):
        self.client.force_login(self.renter)
        data = self.client.get(reverse("account_notifications")).json()
        self.assertEqual(data["new_count"], 0)
        self.assertIn("all caught up", data["html"])

    def test_renter_links_go_to_renter_inquiries(self):
        self.client.force_login(self.renter)
        html = self.client.get(reverse("account_notifications")).json()["html"]
        self.assertNotIn("/landlords/", html)
        self.assertContains(self.client.get(reverse("core_renters:dashboard")), "/renters/dashboard/?tab=inquiries")

    # ---------- profile menu ----------

    def test_profile_menu_for_both_roles(self):
        self.client.force_login(self.renter)
        page = self.client.get(reverse("core_renters:dashboard"))
        for text in ("Arem Test", "@arem", "Renter", "Not verified", "My Profile", "Settings",
                     "Verification", "Contact Support", "mailto:", "Log Out", "data-theme-switch", "data-notif-bell"):
            self.assertContains(page, text)

        self.client.force_login(self.landlord)
        page = self.client.get(reverse("core_landlords:dashboard"))
        self.assertContains(page, "@liza")
        self.assertContains(page, "Landlord")
        self.assertContains(page, "Verified")
        self.assertNotContains(page, "Not verified")