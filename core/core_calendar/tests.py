from datetime import date, time

from django.test import TestCase

from core.core_inquiries.models import Application
from core.core_listings.models import Area, Complex, Unit
from core.core_rentals.services import assign_tenant, end_tenancy
from core.models import Landlord, Renter, User

from .services import Bulletin, Calendar


def make_user(username, role, phone):
    user = User.objects.create_user(
        username=username, password="pw-12345!", first_name=username.title(), last_name="Test",
        phone_number=phone, sex="female", role=role,
    )
    (Landlord if role == "landlord" else Renter).objects.create(user=user)
    return user


class CalendarSetup(TestCase):
    """A landlord with two complexes; arem rents in Sunrise, bea doesn't rent anywhere."""

    def setUp(self):
        self.landlord = make_user("liza", "landlord", "09111111111")
        self.tenant = make_user("arem", "renter", "09222222222")
        self.visitor = make_user("bea", "renter", "09333333333")
        area = Area.objects.create(area_name="Davao City")
        self.sunrise = self.make_complex("Sunrise", area)
        self.moonlight = self.make_complex("Moonlight", area)
        self.unit = self.make_unit(self.sunrise, 1)
        self.other_unit = self.make_unit(self.moonlight, 1)
        self.tenancy = self.assign(self.unit, self.tenant, date(2026, 9, 1))

    def make_complex(self, name, area):
        return Complex.objects.create(
            landlord=self.landlord.landlord, area=area, complex_name=name, address="Poblacion",
            complex_description="x", min_price=5000, max_price=9000, status="active", lease_term="annual",
        )

    def make_unit(self, complex_obj, identifier):
        return Unit.objects.create(
            complex=complex_obj, identifier=identifier, bedroom_type="studio", width_dimension=4,
            length_dimension=5, furnish_level="unfurnished", max_occupant=2, price=8000,
        )

    def assign(self, unit, user, start):
        application = Application.objects.create(
            renter=user.renter, unit=unit, kind="apply", occupants=[user.display_name], move_in_date=start,
        )
        return assign_tenant(unit, start, application=application, on=date(2026, 9, 1))

    def items(self, user, start=date(2026, 10, 1), end=date(2026, 11, 30)):
        return Calendar.for_user(user, start, end).items()

    def post(self, complexes, day):
        return Bulletin(
            self.landlord, message="Water interruption", complex_ids=[str(c.pk) for c in complexes],
            event_date=day, event_title="Water",
        ).post()

    def visit(self, user, unit, status):
        return Application.objects.create(
            renter=user.renter, unit=unit, kind="apply", occupants=[user.display_name],
            move_in_date=date(2026, 11, 30), site_visit_date=date(2026, 10, 25),
            site_visit_time=time(14, 0), site_visit_status=status,
        )

    def titles(self, items, category):
        return [i["title"] for i in items if i["category"] == category]


class RenterCalendarTests(CalendarSetup):
    """Renters see bulletins only for complexes they rent in, and only confirmed site visits."""

    def test_tenant_sees_bulletins_for_their_complex(self):
        self.post([self.sunrise], date(2026, 10, 20))
        self.assertEqual(self.titles(self.items(self.tenant), "announcement"), ["Water"])

    def test_non_tenant_sees_no_bulletins(self):
        self.post([self.sunrise, self.moonlight], date(2026, 10, 20))
        self.assertEqual(self.titles(self.items(self.visitor), "announcement"), [])

    def test_bulletin_for_another_complex_is_hidden(self):
        self.post([self.moonlight], date(2026, 10, 20))
        self.assertEqual(self.titles(self.items(self.tenant), "announcement"), [])

    def test_other_complex_names_are_not_revealed(self):
        self.post([self.sunrise, self.moonlight], date(2026, 10, 20))
        item = next(i for i in self.items(self.tenant) if i["category"] == "announcement")
        self.assertEqual(item["detail"], "Sunrise")

    def test_no_bulletins_from_before_move_in(self):
        newcomer = make_user("carlo", "renter", "09444444444")
        self.assign(self.other_unit, newcomer, date(2026, 11, 1))
        self.post([self.moonlight], date(2026, 10, 20))     # before they move in
        self.post([self.moonlight], date(2026, 11, 5))      # after
        days = [i["date"] for i in self.items(newcomer) if i["category"] == "announcement"]
        self.assertEqual(days, ["2026-11-05"])

    def test_ended_tenancy_sees_no_bulletins(self):
        end_tenancy(self.tenancy, "completed", on=date(2026, 9, 30))
        self.post([self.sunrise], date(2026, 10, 20))
        self.assertEqual(self.titles(self.items(self.tenant), "announcement"), [])

    def test_only_confirmed_site_visits_show(self):
        self.visit(self.visitor, self.other_unit, Application.SiteVisit.PENDING)
        self.assertEqual(self.titles(self.items(self.visitor), "site_visit"), [])
        self.assertEqual(self.titles(self.items(self.landlord), "site_visit"), [])

        Application.objects.update(site_visit_status=Application.SiteVisit.CONFIRMED)
        self.assertEqual(self.titles(self.items(self.visitor), "site_visit"), ["Unit 1 – Site Visit"])
        landlord_visit = next(i for i in self.items(self.landlord) if i["category"] == "site_visit")
        self.assertEqual(landlord_visit["time_label"], "2:00 PM")

    def test_declined_site_visit_is_hidden(self):
        self.visit(self.visitor, self.other_unit, Application.SiteVisit.DECLINED)
        self.assertEqual(self.titles(self.items(self.visitor), "site_visit"), [])

class BulletinMessageTests(CalendarSetup):
    """Post on Bulletin -> a 'Bulletin Announcement' banner in the chat of current tenants only."""

    def received(self, user):
        from core.core_inquiries.models import Message
        return list(Message.objects.filter(conversation__renter=user.renter, kind=Message.Kind.BULLETIN))

    def test_tenant_gets_a_bulletin_banner(self):
        self.post([self.sunrise], date(2026, 10, 20))
        [message] = self.received(self.tenant)
        self.assertEqual(message.body, "Water interruption")          # no "📢 Bulletin from your landlord" text
        self.assertEqual(message.bulletin_event, "Water · Oct 20, 2026")
        self.assertEqual(message.preview, "Bulletin: Water interruption")

        from core.core_inquiries.services import ChatJSON
        data = ChatJSON(self.tenant).message(message)
        self.assertEqual((data["kind"], data["bulletin_event"]), ("bulletin", "Water · Oct 20, 2026"))

    def test_bulletin_without_a_date(self):
        Bulletin(self.landlord, message="Gate closes at 10 PM", complex_ids=[str(self.sunrise.pk)]).post()
        [message] = self.received(self.tenant)
        self.assertEqual(message.bulletin_event, "")

    def test_only_current_tenants_get_it(self):
        waitlisted, applicant, former = (make_user("wes", "renter", "09444444444"),
                                         make_user("ann", "renter", "09555555555"),
                                         make_user("fay", "renter", "09666666666"))
        Application.objects.create(renter=waitlisted.renter, unit=self.unit, kind="waitlist",
                                   occupants=["Wes"], move_in_date=date(2026, 12, 1))
        Application.objects.create(renter=applicant.renter, unit=self.other_unit, kind="apply",
                                   occupants=["Ann"], move_in_date=date(2026, 12, 1))
        old = self.assign(self.make_unit(self.sunrise, 2), former, date(2026, 9, 1))
        end_tenancy(old, "completed", on=date(2026, 9, 30))

        __, sent = self.post([self.sunrise, self.moonlight], date(2026, 10, 20))
        self.assertEqual(sent, 1)
        self.assertEqual(len(self.received(self.tenant)), 1)
        for user in (waitlisted, applicant, former, self.visitor):
            self.assertEqual(self.received(user), [], user.username)
            self.assertEqual(self.titles(self.items(user), "announcement"), [], user.username)

    def test_old_bulletin_messages_become_banners(self):
        """The 0006 migration turns bulletins sent before this change into banners."""
        import importlib

        from django.apps import apps as django_apps

        from core.core_inquiries.models import Conversation, Message
        conversation = Conversation.objects.create(renter=self.tenant.renter, landlord=self.landlord.landlord,
                                                   complex=self.sunrise, unit=self.unit)
        old = Message.objects.create(conversation=conversation, sender=self.landlord,
                                     body="📢 Bulletin from your landlord\n\nwazzup\n\n📅 Maintenance · Oct 11, 2026")
        normal = Message.objects.create(conversation=conversation, sender=self.landlord, body="Hello!")
        migration = importlib.import_module("core.core_inquiries.migrations.0006_message_bulletin")
        migration.mark_old_bulletins(django_apps, None)
        old.refresh_from_db()
        normal.refresh_from_db()
        self.assertEqual((old.kind, old.body, old.bulletin_event), ("bulletin", "wazzup", "Maintenance · Oct 11, 2026"))
        self.assertEqual(normal.kind, "message")
