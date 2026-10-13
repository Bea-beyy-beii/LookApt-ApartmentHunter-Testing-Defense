from django.test import TestCase
from django.urls import reverse

from core.models import Landlord, Renter, User

from .guide import LandlordGuide, RenterGuide, UserGuide
from .models import Feedback

ANSWERS = {
    "enjoyed": "The map with nearby landmarks.",
    "challenges": "None so far.",
    "suggestions": "Add more filters.",
    "continue_using": "yes",
    "other": "",
}


def make_user(username, role, phone, **extra):
    user = User.objects.create_user(username=username, password="pw-12345!", first_name=username.title(),
                                    last_name="Test", phone_number=phone, sex="female", role=role,
                                    email=f"{username}@example.com", **extra)
    if role == "renter":
        Renter.objects.create(user=user)
    elif role == "landlord":
        Landlord.objects.create(user=user)
    return user


class FeedbackSetup(TestCase):

    def setUp(self):
        self.renter = make_user("rina", "renter", "09111111111")
        self.landlord = make_user("liza", "landlord", "09222222222")
        self.admin = make_user("boss", "admin", "09333333333", is_staff=True)
        self.url = reverse("core_feedback:submit")

    def send(self, user, **changes):
        self.client.force_login(user)
        return self.client.post(self.url, {**ANSWERS, **changes}, HTTP_ACCEPT="application/json")


class GuideTests(FeedbackSetup):

    def test_each_role_gets_its_own_guide(self):
        self.assertIsInstance(UserGuide.for_user(self.renter), RenterGuide)
        self.assertIsInstance(UserGuide.for_user(self.landlord), LandlordGuide)
        self.assertIsNone(UserGuide.for_user(self.admin))

    def test_profile_menu_shows_the_role_journey(self):
        self.client.force_login(self.renter)
        page = self.client.get(reverse("core_renters:dashboard")).content.decode()
        self.assertIn("LookApt Guide", page)
        self.assertIn("Feedback Form", page)
        self.assertIn("Apply or join the waitlist", page)          # renter step
        self.assertNotIn("Get verified", page)                     # landlord step

        self.client.force_login(self.landlord)
        page = self.client.get(reverse("core_landlords:dashboard")).content.decode()
        self.assertIn("Get verified", page)
        self.assertIn("With a grateful heart,", page)              # thank-you note under the form


class FeedbackFormTests(FeedbackSetup):

    def test_sending_feedback_saves_it(self):
        response = self.send(self.renter, other="Great work!")
        self.assertEqual(response.status_code, 201)
        feedback = Feedback.objects.get()
        self.assertEqual((feedback.user, feedback.role, feedback.continue_using, feedback.other),
                         (self.renter, "renter", "yes", "Great work!"))

    def test_required_questions(self):
        response = self.send(self.landlord, enjoyed="  ", continue_using="")
        self.assertEqual(response.status_code, 400)
        errors = response.json()["errors"]
        self.assertEqual(errors["enjoyed"], "Please answer this question.")
        self.assertEqual(errors["continue_using"], "Please choose an answer.")
        self.assertNotIn("other", errors)                          # optional
        self.assertFalse(Feedback.objects.exists())

    def test_only_renters_and_landlords(self):
        self.assertEqual(self.send(self.admin).status_code, 403)
        self.client.logout()
        self.assertEqual(self.client.post(self.url, ANSWERS).status_code, 302)    # to the login page
        self.assertEqual(self.client.get(self.url).status_code, 302)


class AdminFeedbackTabTests(FeedbackSetup):

    def setUp(self):
        super().setUp()
        self.send(self.renter, enjoyed="Saved listings")
        self.send(self.landlord, enjoyed="Bulk listing", continue_using="maybe")
        self.client.force_login(self.admin)

    def test_feedback_tab_lists_answers_and_counts(self):
        response = self.client.get(reverse("core_admin:overview") + "?tab=feedback")
        ctx = response.context["feedback"]
        self.assertEqual(ctx["total"], 2)
        self.assertEqual({a["value"]: a["count"] for a in ctx["summary"]}, {"yes": 1, "maybe": 1, "no": 0})
        self.assertContains(response, "Bulk listing")
        self.assertContains(response, "Saved listings")

    def test_filters(self):
        live = {"HTTP_X_REQUESTED_WITH": "ap-live"}
        response = self.client.get(reverse("core_admin:feedback_list"), {"role": "landlord"}, **live)
        self.assertContains(response, "Bulk listing")
        self.assertNotContains(response, "Saved listings")
        response = self.client.get(reverse("core_admin:feedback_list"), {"q": "saved"}, **live)
        self.assertContains(response, "Saved listings")
        self.assertNotContains(response, "Bulk listing")

    def test_admins_only(self):
        self.client.force_login(self.renter)
        self.assertEqual(self.client.get(reverse("core_admin:feedback_list")).status_code, 403)
