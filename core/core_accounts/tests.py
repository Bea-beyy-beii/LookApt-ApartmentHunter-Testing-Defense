from django.test import TestCase
from django.urls import reverse

from core.models import User

from .legal import TERMS_VERSION
from .services import AccountService

SIGNUP = {
    "first_name": "Nina", "last_name": "Reyes", "phone_number": "09555555555", "email": "nina@example.com",
    "sex": "female", "role": "renter", "password": "Sunny#Days2026", "confirm_password": "Sunny#Days2026",
}


class TermsStepTests(TestCase):
    """Sign-up step 5: the Terms and Privacy Notice must be accepted."""

    def test_step_5_needs_the_box(self):
        response = self.client.post(reverse("signup_check"), {"step": 5})
        self.assertFalse(response.json()["ok"])
        self.assertIn("agree_terms", response.json()["errors"])
        self.assertTrue(self.client.post(reverse("signup_check"), {"step": 5, "agree_terms": "1"}).json()["ok"])

    def test_create_account_without_agreeing_goes_back_to_step_5(self):
        response = self.client.post(reverse("signup"), SIGNUP)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["start_step"], 5)
        self.assertContains(response, "Please read and agree")

    def test_consent_is_recorded_on_the_account(self):
        response = self.client.post(reverse("signup"), {**SIGNUP, "agree_terms": "1"})
        self.assertRedirects(response, reverse("otp"), fetch_redirect_response=False)
        request = self.client.get(reverse("otp")).wsgi_request
        user = AccountService.create_pending_account(request)
        self.assertEqual(user.terms_version, TERMS_VERSION)
        self.assertIsNotNone(user.terms_accepted_at)

    def test_signup_shows_both_texts(self):
        response = self.client.get(reverse("signup"))
        self.assertContains(response, 'data-step="5"')
        self.assertContains(response, "Terms and Conditions")
        self.assertContains(response, "Privacy Notice")
        self.assertContains(response, "Claude")          # the AI check is disclosed

    def test_public_pages(self):
        self.assertContains(self.client.get(reverse("terms")), "18 years old")
        self.assertContains(self.client.get(reverse("privacy")), "Data Privacy Act of 2012")


class ProfileMenuTests(TestCase):

    def make(self, role):
        user = User.objects.create_user(username=role, password="pw-12345!", first_name="A", last_name="B",
                                        phone_number="0911111111" + str(len(role) % 10), sex="female",
                                        role=role, email=f"{role}@example.com")
        return user

    def test_renters_have_no_verification(self):
        from django.template import Context, Template
        from django.test import RequestFactory
        template = Template("{% load topbar_tags %}{% topbar_right %}")
        for role, shown in (("renter", False), ("landlord", True)):
            request = RequestFactory().get("/")
            request.user = self.make(role)
            html = template.render(Context({"request": request, "user": request.user}))
            self.assertEqual("Not verified" in html, shown, role)
            self.assertNotIn('data-coming-soon="Verification"', html)     # removed from the menu for everyone


# ------------------------------------------------------------------ Account pop-up (account.py)

import io as _io
from unittest import mock as _mock

from django.core.files.storage import InMemoryStorage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from PIL import Image

from core.models import Landlord, Renter

MEMORY_STORAGES = {"default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
                   "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
                   "verification": {"BACKEND": "django.core.files.storage.InMemoryStorage"}}


def photo(name="me.png", size=(600, 400)):
    buffer = _io.BytesIO()
    Image.new("RGB", size, "teal").save(buffer, "PNG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/png")


@override_settings(STORAGES=MEMORY_STORAGES)
class AccountPopupTests(TestCase):

    def setUp(self):
        patcher = _mock.patch.object(User._meta.get_field("avatar"), "storage", InMemoryStorage())
        patcher.start()
        self.addCleanup(patcher.stop)
        self.user = User.objects.create_user(username="nina", password="Old#Pass2026", first_name="Nina",
                                             last_name="Reyes", phone_number="09555555555", sex="female",
                                             role="renter", email="nina@example.com")
        Renter.objects.create(user=self.user)
        self.client.force_login(self.user)

    def test_dashboard_has_the_popup_and_initials(self):
        response = self.client.get(reverse("core_renters:dashboard"))
        self.assertContains(response, "data-account")
        self.assertContains(response, 'data-account-open="profile"')
        self.assertContains(response, 'class="avatar avatar--renter profile-picture"')
        self.assertContains(response, ">NR</span>")
        self.assertNotContains(response, 'data-coming-soon="Verification"')

    def test_upload_and_remove_photo(self):
        response = self.client.post(reverse("account_avatar"), {"avatar": photo()})
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.avatar.name.endswith(".webp"))
        with self.user.avatar.open() as stored:
            self.assertEqual(Image.open(stored).size, (320, 320))       # cropped square
        first = self.user.avatar.name
        self.client.post(reverse("account_avatar"), {"avatar": photo("again.png")})
        self.user.refresh_from_db()
        self.assertFalse(self.user.avatar.storage.exists(first))          # the old photo is deleted
        self.client.post(reverse("account_avatar"), {"remove": "1"})
        self.user.refresh_from_db()
        self.assertFalse(self.user.avatar)

    def test_rejects_non_photos(self):
        fake = SimpleUploadedFile("me.png", b"not an image", content_type="image/png")
        response = self.client.post(reverse("account_avatar"), {"avatar": fake})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.client.post(reverse("account_avatar"),
                                          {"avatar": SimpleUploadedFile("cv.pdf", b"%PDF")}).status_code, 400)

    def test_contact_sharing(self):
        self.assertEqual(self.user.shared_contact, "")                    # chat only by default
        self.client.post(reverse("account_contact"), {"share_email": "1", "share_phone": "0"})
        self.user.refresh_from_db()
        self.assertEqual(self.user.shared_contact, "nina@example.com")
        self.client.post(reverse("account_contact"), {"share_email": "1", "share_phone": "1"})
        self.user.refresh_from_db()
        self.assertEqual(self.user.shared_contact, "nina@example.com · 09555555555")

    def test_change_password(self):
        url = reverse("account_password")
        wrong = self.client.post(url, {"current_password": "nope", "password": "New#Pass2027", "confirm_password": "New#Pass2027"})
        self.assertIn("current_password", wrong.json()["errors"])
        weak = self.client.post(url, {"current_password": "Old#Pass2026", "password": "short", "confirm_password": "short"})
        self.assertIn("password", weak.json()["errors"])
        ok = self.client.post(url, {"current_password": "Old#Pass2026", "password": "New#Pass2027", "confirm_password": "New#Pass2027"})
        self.assertTrue(ok.json()["ok"])
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("New#Pass2027"))
        self.assertEqual(self.client.get(reverse("core_renters:dashboard")).status_code, 200)   # still logged in

    def test_landlord_contact_on_listing_card(self):
        from core.core_listings.detail_services import landlord_summary
        landlord = User.objects.create_user(username="liza", password="pw-12345!", first_name="Liza", last_name="Test",
                                            phone_number="09111111111", sex="female", role="landlord",
                                            email="liza@example.com")
        Landlord.objects.create(user=landlord)
        complex_obj = _mock.Mock(landlord=landlord.landlord)
        with _mock.patch("core.core_listings.detail_services.renter_visible_complexes") as visible:
            visible.return_value.filter.return_value.count.return_value = 1
            hidden = landlord_summary(complex_obj)
            landlord.share_phone = True
            landlord.save()
            shown = landlord_summary(complex_obj)
        self.assertEqual((hidden["email"], hidden["phone"]), ("", ""))
        self.assertEqual((shown["email"], shown["phone"]), ("", "09111111111"))


# ------------------------------------------------------------------ profile photos around the app

@override_settings(STORAGES=MEMORY_STORAGES)
class PhotosEverywhereTests(TestCase):
    """The profile photo (or initials) shows wherever the other person appears."""

    def setUp(self):
        from datetime import date, timedelta

        from core.core_inquiries.models import Conversation, Message
        from core.core_listings.models import Area, Complex, Unit
        from core.core_rentals.models import Tenancy

        patcher = _mock.patch.object(User._meta.get_field("avatar"), "storage", InMemoryStorage())
        patcher.start()
        self.addCleanup(patcher.stop)

        def make(username, role, phone):
            user = User.objects.create_user(username=username, password="pw-12345!", first_name=username.title(),
                                            last_name="Test", phone_number=phone, sex="female", role=role,
                                            email=f"{username}@example.com")
            (Landlord if role == "landlord" else Renter).objects.create(user=user)
            return user

        self.landlord = make("liza", "landlord", "09111111111")
        self.renter = make("rina", "renter", "09222222222")
        from .account import save_avatar
        save_avatar(self.landlord, photo())
        save_avatar(self.renter, photo("r.png"))

        complex_obj = Complex.objects.create(
            landlord=self.landlord.landlord, area=Area.objects.create(area_name="Davao City"),
            complex_name="Sunrise", address="Poblacion", complex_description="x",
            min_price=5000, max_price=9000, status="active", lease_term="monthly")
        unit = Unit.objects.create(complex=complex_obj, identifier=101, bedroom_type="studio", width_dimension=4,
                                   length_dimension=5, furnish_level="unfurnished", max_occupant=2, price=8000)
        today = date.today()
        Tenancy.objects.create(unit=unit, renter=self.renter.renter, tenant_name="Rina Test", occupants=["Rina Test"],
                               monthly_rent=8000, start_date=today - timedelta(days=10),
                               end_date=today + timedelta(days=200), status="active")
        Tenancy.objects.create(unit=unit, renter=self.renter.renter, tenant_name="Rina Test", occupants=["Rina Test"],
                               monthly_rent=7500, start_date=date(2024, 1, 1), end_date=date(2024, 12, 31),
                               ended_on=date(2024, 12, 31), status="completed")
        conversation = Conversation.objects.create(renter=self.renter.renter, landlord=self.landlord.landlord,
                                                   complex=complex_obj, unit=unit)
        Message.objects.create(conversation=conversation, sender=self.renter, body="Hello!")

    def test_rental_history(self):
        self.client.force_login(self.renter)
        response = self.client.get(reverse("core_renters:dashboard") + "?tab=rentals")
        self.assertContains(response, "rental_history.css")
        self.assertContains(response, "Current Rental")
        self.assertContains(response, "Past Rentals")
        self.assertContains(response, 'class="rh-avatar avatar--landlord"')
        self.assertContains(response, self.landlord.avatar_url)
        self.assertContains(response, "rh-status--completed")

    def test_manage_rentals_shows_the_tenant_photo(self):
        self.client.force_login(self.landlord)
        response = self.client.get(reverse("core_landlords:dashboard") + "?tab=rentals")
        self.assertContains(response, 'class="rt-avatar avatar--renter"')
        self.assertContains(response, f'data-avatar="{self.renter.avatar_url}"')

    def test_chat_threads_carry_the_photo(self):
        from core.core_inquiries.services import inbox_json
        thread = inbox_json(self.landlord)["threads"][0]
        self.assertEqual((thread["other_avatar"], thread["other_role"]), (self.renter.avatar_url, "renter"))
        self.client.force_login(self.renter)
        response = self.client.get(reverse("core_renters:dashboard") + "?tab=inquiries")
        self.assertContains(response, 'class="thread-avatar avatar--landlord"')

    def test_report_people_carry_the_photo(self):
        from core.core_reports.services import reportable_people
        person = reportable_people(self.renter)[0]
        self.assertEqual((person["avatar"], person["role"]), (self.landlord.avatar_url, "landlord"))
