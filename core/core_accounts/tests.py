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
            self.assertEqual('data-coming-soon="Verification"' in html, shown, role)
