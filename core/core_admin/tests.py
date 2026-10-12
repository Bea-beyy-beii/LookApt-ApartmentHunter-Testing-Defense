import io
from unittest import mock

from django.core import mail
from django.core.files.storage import InMemoryStorage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from core.core_listings.models import Area, Complex
from core.core_listings.services import renter_visible_complexes
from core.core_reports.models import Report
from core.core_verification.models import VerificationRequest
from core.models import Landlord, Renter, User

from .models import Notice

TEST_SETTINGS = dict(
    STORAGES={"default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
              "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
              "verification": {"BACKEND": "django.core.files.storage.InMemoryStorage"}},
    MAILERS={"default": {"BACKEND": "django.core.mail.backends.locmem.EmailBackend"}},
    ANTHROPIC_API_KEY="", SITE_URL="https://lookapt.example",
)


def make_user(username, role, phone, **extra):
    user = User.objects.create_user(
        username=username, password="pw-12345!", first_name=username.title(), last_name="Test",
        phone_number=phone, sex="female", role=role, email=f"{username}@example.com", **extra,
    )
    if role in ("landlord", "renter"):
        (Landlord if role == "landlord" else Renter).objects.create(user=user)
    return user


def jpg(name="id.jpg"):
    buffer = io.BytesIO()
    Image.new("RGB", (40, 30), "blue").save(buffer, "JPEG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/jpeg")


@override_settings(**TEST_SETTINGS)
class Base(TestCase):

    def setUp(self):
        memory = InMemoryStorage()
        for name in ("id_photo", "selfie", "ownership_document"):
            patcher = mock.patch.object(VerificationRequest._meta.get_field(name), "storage", memory)
            patcher.start()
            self.addCleanup(patcher.stop)

        self.admin = make_user("boss", "admin", "09000000000", is_staff=True)
        self.landlord = make_user("liza", "landlord", "09111111111")
        self.renter = make_user("arem", "renter", "09222222222")
        self.client.force_login(self.admin)

    def post(self, name, pk, data):
        with self.captureOnCommitCallbacks(execute=True):      # emails go out after the save
            return self.client.post(reverse(f"core_admin:{name}", args=[pk]), data)

    def make_request(self, status="review"):
        return VerificationRequest.objects.create(
            landlord=self.landlord.landlord, id_type="drivers_license", id_photo=jpg(), selfie=jpg("s.jpg"),
            ownership_type="business_permit", ownership_document=jpg("p.jpg"), status=status,
        )

    def make_report(self):
        return Report.objects.create(reporter=self.renter, reported_user=self.landlord,
                                     category="price_mismatch", description="Asked for more than listed.")


class AccessTests(Base):

    def test_admin_pages_open(self):
        report, request = self.make_report(), self.make_request()
        dashboard = reverse("core_admin:overview")
        for url in [dashboard, dashboard + "?tab=verification", dashboard + "?tab=users", dashboard + "?tab=reports",
                    reverse("core_admin:verification_detail", args=[request.pk]),
                    reverse("core_admin:user_detail", args=[self.landlord.pk]),
                    reverse("core_admin:report_detail", args=[report.pk]),
                    reverse("core_admin:activity_data") + "?days=7"]:
            with self.subTest(url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_all_tabs_are_in_one_page(self):
        """Switching tabs happens in the browser, so every tab is in the page; ?tab= picks the one shown."""
        response = self.client.get(reverse("core_admin:overview") + "?tab=users")
        for name in ("overview", "verification", "users", "reports"):
            self.assertContains(response, f'data-ap-section="{name}"')
        self.assertContains(response, 'data-ap-section="users" data-title="LookApt Admin — Users" >')     # shown
        self.assertContains(response, 'data-ap-section="overview" data-title="LookApt Admin — Overview" hidden>')

    def test_old_list_addresses_open_the_tab(self):
        response = self.client.get(reverse("core_admin:user_list") + "?role=renter")
        self.assertRedirects(response, reverse("core_admin:overview") + "?role=renter&tab=users",
                             fetch_redirect_response=False)

    def test_landlords_and_renters_are_refused(self):
        for user in (self.landlord, self.renter):
            self.client.force_login(user)
            self.assertEqual(self.client.get(reverse("core_admin:overview")).status_code, 403)

    def test_admin_login_lands_on_the_panel(self):
        self.client.logout()
        response = self.client.post(reverse("login"), {"identifier": "boss", "password": "pw-12345!"})
        self.assertRedirects(response, reverse("core_admin:overview"), fetch_redirect_response=False)

    def test_activity_chart_data(self):
        self.make_report()
        data = self.client.get(reverse("core_admin:activity_data") + "?days=7").json()
        self.assertEqual(len(data["dates"]), 7)
        self.assertEqual([s["key"] for s in data["series"]], ["users", "listings", "reports"])
        self.assertEqual(sum(data["series"][2]["values"]), 1)


class VerificationTests(Base):

    def test_approve_verifies_and_notifies(self):
        request = self.make_request()
        self.post("verification_detail", request.pk, {"action": "approve"})
        self.landlord.refresh_from_db()
        self.assertTrue(self.landlord.is_verified)
        self.assertTrue(Notice.objects.filter(user=self.landlord, title="You're verified!").exists())
        self.assertEqual(mail.outbox[-1].to, ["liza@example.com"])
        self.assertIn("verified", mail.outbox[-1].subject)

    def test_resubmit_needs_a_reason_and_sends_it(self):
        request = self.make_request()
        self.post("verification_detail", request.pk, {"action": "resubmit", "reason": ""})
        request.refresh_from_db()
        self.assertEqual(request.status, "review")                  # nothing happened
        self.post("verification_detail", request.pk, {"action": "resubmit", "reason": "Your ID is blurry."})
        request.refresh_from_db()
        self.assertEqual((request.status, request.message), ("resubmit", "Your ID is blurry."))
        self.assertIn("Your ID is blurry.", mail.outbox[-1].body)

    def test_take_back_verification(self):
        request = self.make_request("approved")
        self.landlord.is_verified = True
        self.landlord.save()
        self.post("verification_detail", request.pk, {"action": "reject", "reason": "The documents are fake."})
        self.landlord.refresh_from_db()
        self.assertFalse(self.landlord.is_verified)


class UserTests(Base):

    def setUp(self):
        super().setUp()
        self.complex = Complex.objects.create(
            landlord=self.landlord.landlord, area=Area.objects.create(area_name="Davao City"),
            complex_name="Sunrise", address="Poblacion", complex_description="x",
            min_price=5000, max_price=9000, status="active", lease_term="monthly",
        )

    def live(self, name, query):
        """What the live filters get: only that tab's results table."""
        return self.client.get(reverse(f"core_admin:{name}") + query, HTTP_X_REQUESTED_WITH="ap-live")

    def test_list_filters(self):
        response = self.live("user_list", "?role=renter")
        self.assertContains(response, "Arem Test")
        self.assertNotContains(response, "Liza Test")
        self.assertNotContains(response, reverse("core_admin:user_detail", args=[self.admin.pk]))   # admins aren't listed

    def test_date_joined_filter(self):
        from datetime import timedelta
        from django.utils import timezone
        User.objects.filter(pk=self.renter.pk).update(date_joined=timezone.now() - timedelta(days=40))
        self.assertNotContains(self.live("user_list", "?joined=30"), "Arem Test")
        self.assertContains(self.live("user_list", "?joined=90"), "Arem Test")
        old = (timezone.localdate() - timedelta(days=40)).isoformat()
        response = self.live("user_list", f"?joined=custom&joined_from={old}&joined_to={old}")
        self.assertContains(response, "Arem Test")
        self.assertNotContains(response, "Liza Test")
        # A broken date is ignored instead of crashing
        self.assertEqual(self.live("user_list", "?joined=custom&joined_from=nope").status_code, 200)
        # Opening the dashboard with the filter in the address applies it to the Users tab
        self.assertNotContains(self.client.get(reverse("core_admin:overview") + "?tab=users&joined=30"), "Arem Test")

    def test_live_filters_get_only_the_results(self):
        response = self.client.get(reverse("core_admin:user_list") + "?q=arem", HTTP_X_REQUESTED_WITH="ap-live")
        self.assertContains(response, "Arem Test")
        self.assertNotContains(response, "<html")            # just the table, not the whole page
        self.assertNotContains(response, "Liza Test")

    def test_suspend_hides_listings_blocks_login_and_emails(self):
        self.post("user_detail", self.landlord.pk, {"action": "suspend", "reason": "Scamming renters."})
        self.landlord.refresh_from_db()
        self.assertFalse(self.landlord.is_active)
        self.assertNotIn(self.complex, renter_visible_complexes())
        self.assertIn("suspended", mail.outbox[-1].subject)

        self.client.logout()
        response = self.client.post(reverse("login"), {"identifier": "liza", "password": "pw-12345!"}, follow=True)
        self.assertContains(response, "Your account is suspended")

        self.client.force_login(self.admin)
        self.post("user_detail", self.landlord.pk, {"action": "reactivate"})
        self.landlord.refresh_from_db()
        self.assertTrue(self.landlord.is_active)
        self.assertIn(self.complex, renter_visible_complexes())

    def test_suspend_needs_a_reason(self):
        self.post("user_detail", self.renter.pk, {"action": "suspend", "reason": " "})
        self.renter.refresh_from_db()
        self.assertTrue(self.renter.is_active)

    def test_edit_details(self):
        self.post("user_detail", self.renter.pk, {"action": "edit", "first_name": "Arem", "last_name": "Cruz",
                                                  "email": "arem.cruz@example.com", "phone_number": "09222222222"})
        self.renter.refresh_from_db()
        self.assertEqual((self.renter.last_name, self.renter.email), ("Cruz", "arem.cruz@example.com"))

    def test_edit_refuses_a_taken_email(self):
        response = self.post("user_detail", self.renter.pk, {"action": "edit", "first_name": "Arem", "last_name": "T",
                                                             "email": "LIZA@example.com", "phone_number": "09222222222"})
        self.assertContains(response, "Another account already uses this email.")

    def test_warning_reaches_the_bell_and_email(self):
        self.post("user_detail", self.renter.pk, {"action": "warn", "message": "Please stop spamming landlords."})
        self.assertTrue(Notice.objects.filter(user=self.renter, title="Warning from LookApt").exists())
        self.assertIn("Please stop spamming landlords.", mail.outbox[-1].body)

    def test_password_help_email_links_to_forgot_password(self):
        self.post("user_detail", self.renter.pk, {"action": "password"})
        self.assertIn("https://lookapt.example/forgot-password/", mail.outbox[-1].body)


class ReportTests(Base):

    def test_resolve_needs_a_note_and_tells_the_reporter(self):
        report = self.make_report()
        self.post("report_detail", report.pk, {"action": "status", "status": "resolved", "note": ""})
        report.refresh_from_db()
        self.assertEqual(report.status, "waiting")
        self.post("report_detail", report.pk, {"action": "status", "status": "resolved",
                                               "note": "We talked to the landlord and refunded you."})
        report.refresh_from_db()
        self.assertEqual((report.status, report.handled_by), ("resolved", self.admin))
        self.assertEqual(mail.outbox[-1].to, ["arem@example.com"])
        self.assertIn("refunded", mail.outbox[-1].body)
        # The reporter sees the note on their Reports tab
        self.client.force_login(self.renter)
        self.assertContains(self.client.get(reverse("core_renters:dashboard") + "?tab=reports"), "refunded you")

    def test_unpublish_reported_landlords_listings(self):
        report = self.make_report()
        Complex.objects.create(landlord=self.landlord.landlord, area=Area.objects.create(area_name="Davao"),
                               complex_name="Sunrise", address="x", complex_description="x",
                               min_price=1, max_price=2, status="active", lease_term="monthly")
        self.post("report_detail", report.pk, {"action": "unpublish", "reason": "Fake photos."})
        self.assertFalse(Complex.objects.filter(landlord__user=self.landlord, status="active").exists())
        self.assertTrue(Notice.objects.filter(user=self.landlord, title="Your listings were unpublished").exists())

    def test_filing_a_report_confirms_by_email(self):
        self.client.force_login(self.renter)
        with self.captureOnCommitCallbacks(execute=True):
            Complex.objects.create(landlord=self.landlord.landlord, area=Area.objects.create(area_name="Davao"),
                                   complex_name="Sunrise", address="x", complex_description="x",
                                   min_price=1, max_price=2, status="active", lease_term="monthly")
            response = self.client.post(reverse("core_reports:create"), {
                "reported_user": str(self.landlord.pk), "category": "price_mismatch", "description": "Too high."})
        self.assertEqual(response.status_code, 201)
        self.assertIn("we received your report", mail.outbox[-1].subject)

    def test_repeat_flag(self):
        self.make_report()
        self.make_report()
        self.assertContains(self.client.get(reverse("core_admin:overview") + "?tab=reports"), 'title="2 reports received"')


@override_settings(**TEST_SETTINGS)
class EmailTests(TestCase):

    def test_welcome_email_after_sign_up(self):
        from core.core_admin import notify
        user = make_user("nina", "landlord", "09444444444")
        with self.captureOnCommitCallbacks(execute=True):
            notify.welcome(user)
        message = mail.outbox[-1]
        self.assertEqual(message.subject, "Welcome to LookApt!")
        self.assertIn("verify your account", message.body)
        self.assertIn("lookapt.support@gmail.com", message.body)
        html = message.alternatives[0][0]
        self.assertIn("https://lookapt.example/login/", html)

    def test_email_failure_does_not_break_anything(self):
        from core.core_accounts.emails import send_email
        user = make_user("nina", "renter", "09444444444")
        with mock.patch("core.core_accounts.emails.EmailWithInlineLogo.send", side_effect=OSError("SMTP down")):
            self.assertFalse(send_email(user, "Hi", ["Hello"]))
