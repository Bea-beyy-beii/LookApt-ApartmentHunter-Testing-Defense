from datetime import date

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from core.core_inquiries.models import Application
from core.core_listings.models import Area, Complex, Unit
from core.models import Landlord, Renter, User

from . import services
from .models import Report


def make_user(username, role, phone):
    user = User.objects.create_user(
        username=username, password="pw-12345!", first_name=username.title(), last_name="Test",
        phone_number=phone, sex="female", role=role,
    )
    (Landlord if role == "landlord" else Renter).objects.create(user=user)
    return user


PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


class ReportTests(TestCase):

    def setUp(self):
        self.landlord = make_user("liza", "landlord", "09111111111")
        self.landlord.is_verified = True          # unverified landlords can't file reports (core_verification)
        self.landlord.save()
        self.other_landlord = make_user("mark", "landlord", "09444444444")
        self.renter = make_user("arem", "renter", "09222222222")
        self.stranger = make_user("bea", "renter", "09333333333")
        area = Area.objects.create(area_name="Davao City")
        self.complex = Complex.objects.create(
            landlord=self.landlord.landlord, area=area, complex_name="Sunrise", address="Poblacion",
            complex_description="x", min_price=5000, max_price=9000, status="active",
        )
        # Mark's listing is hidden (unpublished): renters can't see it
        Complex.objects.create(
            landlord=self.other_landlord.landlord, area=area, complex_name="Hidden", address="Buhangin",
            complex_description="x", min_price=5000, max_price=9000, status="unpublished",
        )
        self.unit = Unit.objects.create(
            complex=self.complex, identifier=1, bedroom_type="studio", width_dimension=4,
            length_dimension=5, furnish_level="unfurnished", max_occupant=2, price=8000,
        )

    def post(self, user, **data):
        self.client.force_login(user)
        files = data.pop("files", [])
        payload = {"category": "others", "other_category_text": "", "description": "It happened.", **data}
        if files:
            payload["evidence"] = files
        return self.client.post(reverse("core_reports:create"), payload)

    # ---------- who can be reported ----------

    def test_renter_can_report_any_visible_landlord_without_inquiring(self):
        ids = {p["id"] for p in services.reportable_people(self.renter)}
        self.assertEqual(ids, {str(self.landlord.pk)})        # not the hidden listing's landlord

    def test_landlord_can_only_report_linked_renters(self):
        self.assertEqual(services.reportable_people(self.landlord), [])
        Application.objects.create(
            renter=self.renter.renter, unit=self.unit, kind="apply",
            occupants=["Arem Test"], move_in_date=date(2026, 12, 1),
        )
        people = services.reportable_people(self.landlord)
        self.assertEqual([p["id"] for p in people], [str(self.renter.pk)])
        self.assertIn("Applied", people[0]["detail"])

        response = self.post(self.landlord, reported_user=str(self.stranger.pk), category="harassment")
        self.assertEqual(response.status_code, 400)
        self.assertIn("reported_user", response.json()["errors"])

    # ---------- the form ----------

    def test_others_needs_a_reason(self):
        response = self.post(self.renter, reported_user=str(self.landlord.pk))
        self.assertIn("other_category_text", response.json()["errors"])

    def test_reason_must_match_the_role(self):
        response = self.post(self.renter, reported_user=str(self.landlord.pk), category="no_show")
        self.assertIn("category", response.json()["errors"])

    def test_file_report_with_evidence(self):
        response = self.post(
            self.renter, reported_user=str(self.landlord.pk), category="others",
            other_category_text="Rude listing text", files=[SimpleUploadedFile("proof.png", PNG, "image/png")],
        )
        self.assertEqual(response.status_code, 201)
        report = Report.objects.get()
        self.assertEqual(report.status, Report.Status.WAITING)
        self.assertEqual(report.evidence.get().kind, "image")
        self.assertEqual(report.get_status_display(), "Pending")

    def test_renamed_file_is_rejected(self):
        response = self.post(
            self.renter, reported_user=str(self.landlord.pk), category="safety_concerns",
            files=[SimpleUploadedFile("proof.png", b"MZ not a picture", "image/png")],
        )
        self.assertIn("evidence", response.json()["errors"])
        self.assertFalse(Report.objects.exists())

    def test_no_duplicate_open_reports(self):
        self.post(self.renter, reported_user=str(self.landlord.pk), category="safety_concerns")
        response = self.post(self.renter, reported_user=str(self.landlord.pk), category="safety_concerns")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Report.objects.count(), 1)

    def test_page_shows_only_my_reports(self):
        self.post(self.renter, reported_user=str(self.landlord.pk), category="safety_concerns")
        self.assertEqual(len(services.get_reports_context(self.renter)["reports"]), 1)
        self.assertEqual(len(services.get_reports_context(self.stranger)["reports"]), 0)

        self.client.force_login(self.renter)
        page = self.client.get(reverse("core_renters:dashboard"))
        self.assertContains(page, "Report Guidelines")
        self.assertContains(page, "Select Landlord to Report")
        self.client.force_login(self.landlord)
        page = self.client.get(reverse("core_landlords:dashboard"))
        self.assertContains(page, "Select Renter to Report")