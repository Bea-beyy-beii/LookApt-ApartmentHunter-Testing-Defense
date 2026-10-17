from datetime import date

from django.core.exceptions import PermissionDenied
from django.test import RequestFactory, TestCase
from django.urls import reverse

from core.core_accounts.middleware import HideAdminMiddleware
from core.core_calendar.services import Calendar, LandlordCalendar, RenterCalendar
from core.core_feedback.guide import LandlordGuide, UserGuide
from core.core_inquiries.workflow import LandlordRequestTabs, RenterRequestTabs, RequestTabs
from core.core_reports.services import LandlordReporter, Reporter, RenterReporter
from core.middleware import Middleware
from core.models import Landlord, Profile, Renter, User
from core.parsing import ParsesDates


def make_user(username, role, phone):
    user = User.objects.create_user(username=username, password="pw-12345!", first_name="A", last_name="B",
                                    phone_number=phone, sex="female", role=role, email=f"{username}@example.com")
    if role in ("renter", "landlord"):
        user.create_profile()
    return user


class RoleBasedTests(TestCase):
    """core/roles.py: one class per role, found without `if role == ...`."""

    def setUp(self):
        self.renter = make_user("rina", "renter", "09111111111")
        self.landlord = make_user("liza", "landlord", "09222222222")
        self.admin = make_user("boss", "admin", "09333333333")

    def test_each_family_finds_its_class(self):
        self.assertIs(Profile.for_role("renter"), Renter)
        self.assertIs(Profile.for_role("landlord"), Landlord)
        self.assertIsNone(Profile.for_role("admin"))
        self.assertIs(Calendar.class_for(self.landlord), LandlordCalendar)
        self.assertIs(Calendar.class_for(self.renter), RenterCalendar)
        self.assertIs(Reporter.class_for(self.renter), RenterReporter)
        self.assertIs(Reporter.class_for(self.landlord), LandlordReporter)
        self.assertIsInstance(UserGuide.for_user(self.landlord), LandlordGuide)
        self.assertIsInstance(RequestTabs.for_user(self.landlord, []), LandlordRequestTabs)
        self.assertIsInstance(RequestTabs.for_user(self.renter, []), RenterRequestTabs)

    def test_a_role_without_a_class_is_refused(self):
        with self.assertRaises(PermissionDenied):
            Reporter.for_user(self.admin)          # used to fall back to LandlordReporter
        self.assertIsNone(UserGuide.for_user(self.admin))

    def test_admins_get_no_notifications(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("account_notifications")).status_code, 403)

    def test_home_pages(self):
        self.assertEqual(self.landlord.home_url_name, "core_landlords:dashboard")
        self.assertEqual(self.admin.home_url_name, User.ADMIN_HOME)

    def test_only_landlords_have_a_rating(self):
        self.assertIsNone(self.renter.renter.rating)
        self.assertIsNone(self.landlord.landlord.rating)          # no reviews yet


class SharedBaseTests(TestCase):

    def test_parses_dates(self):
        self.assertEqual(ParsesDates.parse_date("2026-10-17"), date(2026, 10, 17))
        for bad in ("", None, "17/10/2026", "2026-02-30"):
            self.assertIsNone(ParsesDates.parse_date(bad))

    def test_middleware_must_handle_requests(self):
        with self.assertRaises(TypeError):
            Middleware(lambda request: None)        # abstract: __call__ isn't written
        middleware = HideAdminMiddleware(lambda request: "next")
        request = RequestFactory().get("/")
        self.assertEqual(middleware(request), "next")
