from datetime import date, datetime, time
from datetime import timezone as dt_timezone
from unittest import mock

from django.test import TestCase
from django.urls import reverse

from core.core_inquiries.models import Application
from core.core_listings.models import Area, Complex, ListingView, Unit
from core.core_rentals.models import RentPayment, Tenancy
from core.core_rentals.services import TenantAssignment
from core.models import Landlord, Renter, User

from .services import PerformanceChart, ReceivablesReport

TODAY = date(2026, 10, 9)


def make_user(username, role, phone):
    user = User.objects.create_user(
        username=username, password="pw-12345!", first_name=username.title(), last_name="Test",
        phone_number=phone, sex="female", role=role,
    )
    (Landlord if role == "landlord" else Renter).objects.create(user=user)
    return user


@mock.patch("core.core_inquiries.services.today", return_value=TODAY)
@mock.patch("core.core_landlords.services.today", return_value=TODAY)
@mock.patch("core.core_landlords.sections.today", return_value=TODAY)
class HomeTests(TestCase):

    def setUp(self):
        self.landlord = make_user("liza", "landlord", "09111111111")
        self.renter = make_user("arem", "renter", "09222222222")
        self.complex = Complex.objects.create(
            landlord=self.landlord.landlord, area=Area.objects.create(area_name="Davao City"),
            complex_name="Sunrise", address="Poblacion", complex_description="x",
            min_price=5000, max_price=20000, status="active", lease_term="monthly",
        )
        self.units = [self.make_unit(i, price) for i, price in enumerate([12000, 12000, 8500, 6000], start=1)]

    def make_unit(self, identifier, price):
        return Unit.objects.create(
            complex=self.complex, identifier=identifier, bedroom_type="studio", width_dimension=4,
            length_dimension=5, furnish_level="unfurnished", max_occupant=2, price=price,
        )

    def tenant(self, unit, start, application=None):
        return TenantAssignment.create(
            unit, start, application=application, tenant_name="" if application else "Guest", on=start,
        ).save()

    # ---------- receivables ----------

    def test_receivables_add_up_by_rate(self, *_):
        paid = self.tenant(self.units[0], date(2026, 9, 5))      # due Oct 5 (paid)
        self.tenant(self.units[1], date(2026, 9, 2))             # due Oct 2 (overdue)
        self.tenant(self.units[2], date(2026, 9, 12))            # due Oct 12 (next 7 days)
        self.tenant(self.units[3], date(2026, 9, 28))            # due Oct 28 (not yet due)
        RentPayment.objects.create(tenancy=paid, due_date=date(2026, 10, 5), amount=12000, paid_on=TODAY)

        r = ReceivablesReport(self.landlord, TODAY, TODAY).as_dict()
        self.assertEqual(r["expected"], {"count": 4, "amount": 38500})
        self.assertEqual(r["paid"]["amount"], 12000)
        self.assertEqual(r["overdue"]["count"], 1)
        self.assertEqual(r["due_soon"]["count"], 1)
        self.assertEqual(r["not_due"]["count"], 1)
        self.assertEqual(r["percent"], 31)
        self.assertEqual([(b["rate"], b["units"]) for b in r["breakdown"]], [(12000, 2), (8500, 1), (6000, 1)])

    def test_ended_contract_is_never_overdue(self, *_):
        ended = self.tenant(self.units[0], date(2026, 8, 3))          # Aug 3, Sep 3 unpaid
        RentPayment.objects.create(tenancy=ended, due_date=date(2026, 8, 3), amount=12000, paid_on=date(2026, 8, 3))
        ended.end("terminated", on=date(2026, 9, 20))

        september = ReceivablesReport(self.landlord, date(2026, 9, 1), TODAY).as_dict()
        self.assertEqual(september["overdue"]["count"], 0)
        self.assertEqual(september["expected"]["count"], 0)
        august = ReceivablesReport(self.landlord, date(2026, 8, 1), TODAY).as_dict()
        self.assertEqual(august["paid"]["amount"], 12000)                # what was paid still counts

    def test_future_tenancy_is_not_expected_yet(self, *_):
        self.tenant(self.units[0], date(2026, 11, 1))
        self.assertEqual(ReceivablesReport(self.landlord, TODAY, TODAY).as_dict()["expected"]["count"], 0)

    # ---------- performance ----------

    def test_performance_counts_views_and_lookapt_rentals_only(self, *_):
        ListingView.objects.create(complex=self.complex, viewer=self.renter, viewed_on=date(2026, 10, 3))
        ListingView.objects.create(complex=self.complex, viewer=self.renter, viewed_on=date(2026, 9, 3))
        application = Application.objects.create(
            renter=self.renter.renter, unit=self.units[0], kind="apply",
            occupants=["Arem Test"], move_in_date=date(2026, 10, 20),
        )
        self.tenant(self.units[0], date(2026, 10, 20), application=application)   # from LookApt
        self.tenant(self.units[1], date(2026, 10, 1))                              # walk-in: not counted
        # created_at is "now"; pin it inside the month being checked (TODAY is mocked)
        on_oct_5 = datetime(2026, 10, 5, 12, tzinfo=dt_timezone.utc)
        Application.objects.update(created_at=on_oct_5)
        Tenancy.objects.update(created_at=on_oct_5)

        data = PerformanceChart(self.landlord, TODAY, TODAY).as_dict()
        totals = {s["key"]: s["total"] for s in data["series"]}
        self.assertEqual(totals["views"], 1)
        self.assertEqual(totals["inquiries"], 1)
        self.assertEqual(totals["rentals"], 1)
        self.assertEqual(len(data["days"]), 9)          # Oct 1 – Oct 9
        views = next(s for s in data["series"] if s["key"] == "views")
        self.assertEqual(views["change"], 0)            # 1 view vs 1 view in Sep 1–9

    def test_views_are_counted_once_per_day(self, *_):
        self.client.force_login(self.renter)
        url = reverse("core_listings:renter_complex_detail", args=[self.complex.pk])
        self.client.get(url)
        self.client.get(url)
        self.assertEqual(ListingView.objects.count(), 1)

    # ---------- attention ----------

    def test_attention_lists_only_what_needs_action(self, *_):
        self.client.force_login(self.landlord)
        response = self.client.get(reverse("core_landlords:dashboard"))
        self.assertEqual(response.context["home"]["attention"], [])
        self.assertContains(response, "all caught up")

        Application.objects.create(
            renter=self.renter.renter, unit=self.units[0], kind="apply", occupants=["Arem Test"],
            move_in_date=date(2026, 10, 30), site_visit_date=date(2026, 10, 15),
            site_visit_time=time(10, 0), site_visit_status=Application.SiteVisit.PENDING,
        )
        self.tenant(self.units[1], date(2026, 8, 1))     # Aug, Sep, Oct unpaid -> overdue
        response = self.client.get(reverse("core_landlords:dashboard"))
        titles = [item["title"] for item in response.context["home"]["attention"]]
        self.assertEqual(titles, ["Overdue rent", "Pending requests", "Site visits to confirm"])
        overdue = response.context["home"]["attention"][0]
        self.assertIn("₱36,000", overdue["detail"])      # 3 months x 12,000 (Aug 1, Sep 1, Oct 1)

    # ---------- page + endpoints ----------

    def test_dashboard_and_endpoints(self, *_):
        self.client.force_login(self.landlord)
        response = self.client.get(reverse("core_landlords:dashboard"))
        self.assertContains(response, "Welcome back, Liza!")
        self.assertContains(response, "Managed Properties")

        panel = self.client.get(reverse("core_landlords:receivables_panel"), {"month": "2026-11"})
        self.assertIn("November 2026", panel.json()["html"])

        chart = self.client.get(reverse("core_landlords:performance_data"), {"month": "2026-09"})
        self.assertEqual(len(chart.json()["days"]), 30)

    def test_export_financials_pdf(self, *_):
        from io import BytesIO
        from pypdf import PdfReader

        paid = self.tenant(self.units[0], date(2026, 9, 5))
        self.tenant(self.units[1], date(2026, 9, 2))                 # overdue Oct 2
        RentPayment.objects.create(tenancy=paid, due_date=date(2026, 10, 5), amount=12000, paid_on=TODAY)
        Tenancy.objects.filter(pk=paid.pk).update(tenant_name="Ana <Cruz> & Co")   # markup must be escaped

        self.client.force_login(self.landlord)
        response = self.client.get(reverse("core_landlords:export_receivables"), {"month": "2026-10"})
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertIn('filename="LookApt-receivables-2026-10.pdf"', response["Content-Disposition"])

        text = "".join(page.extract_text() for page in PdfReader(BytesIO(response.content)).pages)
        for expected in ("Monthly Receivables: October 2026", "PHP 12,000 of PHP 24,000 collected (50%)",
                         "Expected Rental Income", "Overdue (1)", "Paid (1)", "Ana <Cruz> & Co", "Sunrise"):
            self.assertIn(expected, text)

        # The home button and the drawer link to it
        home = self.client.get(reverse("core_landlords:dashboard"))
        self.assertContains(home, reverse("core_landlords:export_receivables"))
        panel = self.client.get(reverse("core_landlords:receivables_panel"), {"month": "2026-11"})
        self.assertIn("?month=2026-11", panel.json()["html"])

    def test_renters_cannot_use_landlord_endpoints(self, *_):
        self.client.force_login(self.renter)
        self.assertEqual(self.client.get(reverse("core_landlords:receivables_panel")).status_code, 403)
        self.assertEqual(self.client.get(reverse("core_landlords:export_receivables")).status_code, 403)