# core_inquiries/tests.py
import io
import json
from datetime import date, timedelta
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from django.test import TestCase
from django.urls import reverse

from core.core_listings.models import Area, Complex, Unit
from core.models import Landlord, Renter, User

from . import services
from .models import Application, Conversation, Message


def make_user(username, role, phone):
    return User.objects.create_user(
        username=username, password="pw-12345!", first_name=username.title(), last_name="Test",
        phone_number=phone, sex="female", role=role,
    )


class Base(TestCase):

    def setUp(self):
        self.landlord_user = make_user("liza", "landlord", "09111111111")
        self.landlord = Landlord.objects.create(user=self.landlord_user)
        self.renter_user = make_user("arem", "renter", "09222222222")
        Renter.objects.create(user=self.renter_user)

        self.complex = Complex.objects.create(
            landlord=self.landlord, area=Area.objects.create(area_name="Davao City"),
            complex_name="Sunrise", address="Poblacion", complex_description="Nice",
            min_price=5000, max_price=20000, status=Complex.ComplexStatus.ACTIVE,
            lease_term="annual", turnover_days=7,
        )
        self.available = self.make_unit(201)
        self.occupied = self.make_unit(401, availability=Unit.Availability.OCCUPIED, occupied_since=date(2025, 10, 26))
        self.client.force_login(self.renter_user)

    def make_unit(self, identifier, **kwargs):
        defaults = dict(
            complex=self.complex, identifier=identifier, bedroom_type="studio",
            width_dimension=4, length_dimension=5, furnish_level="unfurnished",
            max_occupant=2, price=8000,
        )
        defaults.update(kwargs)
        return Unit.objects.create(**defaults)

    def post(self, url, data):
        return self.client.post(url, json.dumps(data), content_type="application/json")


class MoveInDateTests(Base):

    def test_waitlist_date_is_lease_end_plus_turnover(self):
        # Oct 26, 2025 + 1 year lease + 7 days of preparation
        self.assertEqual(services.earliest_move_in(self.occupied, on=date(2026, 10, 6)), date(2026, 11, 2))

    def test_renewed_lease_uses_the_next_end_date(self):
        self.complex.lease_term = "monthly"
        self.complex.save()
        # Monthly lease from Oct 26, 2025: on Mar 1, 2026 the current term ends Mar 26
        self.assertEqual(services.current_lease_end(self.occupied, on=date(2026, 3, 1)), date(2026, 3, 26))

    def test_unknown_lease_start_falls_back_to_turnover_from_today(self):
        self.occupied.occupied_since = None
        self.assertEqual(services.earliest_move_in(self.occupied, on=date(2026, 1, 1)), date(2026, 1, 8))

    def test_available_unit_can_move_in_today(self):
        self.assertEqual(services.earliest_move_in(self.available, on=date(2026, 1, 1)), date(2026, 1, 1))


class ApplicationTests(Base):

    def url(self, unit):
        return reverse("core_inquiries:submit_application", args=[unit.pk])

    def apply(self, unit, **overrides):
        data = {
            "kind": "apply", "occupants": ["", "Juan Dela Cruz"],
            "move_in_date": (date.today() + timedelta(days=30)).isoformat(),
            "site_visit_date": (date.today() + timedelta(days=5)).isoformat(),
            "site_visit_time": "14:00",
        }
        data.update(overrides)
        return self.post(self.url(unit), data)

    def test_apply_saves_account_holder_first(self):
        response = self.apply(self.available, occupants=["Someone Else", "Juan Dela Cruz"])
        self.assertEqual(response.status_code, 201)
        application = Application.objects.get()
        self.assertEqual(application.occupants, [self.renter_user.display_name, "Juan Dela Cruz"])
        self.assertEqual(application.kind, "apply")

    def test_too_many_occupants(self):
        response = self.apply(self.available, occupants=["", "A", "B"])   # max is 2
        self.assertEqual(response.status_code, 400)
        self.assertIn("occupants", response.json()["errors"])

    def test_site_visit_after_move_in_is_rejected(self):
        response = self.apply(self.available,
                              move_in_date=(date.today() + timedelta(days=5)).isoformat(),
                              site_visit_date=(date.today() + timedelta(days=10)).isoformat())
        self.assertEqual(response.status_code, 400)
        self.assertIn("site_visit_date", response.json()["errors"])

    def test_cannot_apply_to_occupied_unit(self):
        self.assertEqual(self.apply(self.occupied).status_code, 400)

    def test_sex_restriction_is_checked(self):
        # The renter is female
        self.complex.sex_restriction = "male_only"
        self.complex.save()
        response = self.apply(self.available)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["errors"]["__all__"], "Sunrise is for male tenants only.")
        waitlist = self.apply(self.occupied, kind="waitlist", site_visit_date="", site_visit_time="")
        self.assertEqual(waitlist.status_code, 400)
        self.assertIn("male tenants only", waitlist.json()["errors"]["__all__"])

        self.complex.sex_restriction = "female_only"
        self.complex.save()
        self.assertEqual(self.apply(self.available).status_code, 201)

    def test_restricted_unit_shows_a_disabled_button(self):
        self.complex.sex_restriction = "male_only"
        self.complex.save()
        response = self.client.get(reverse("core_listings:renter_complex_detail", args=[self.complex.pk]))
        self.assertContains(response, "Male tenants only")
        self.assertNotContains(response, "data-open-application")

    def test_only_one_pending_application_per_unit(self):
        self.assertEqual(self.apply(self.available).status_code, 201)
        response = self.apply(self.available)
        self.assertEqual(response.status_code, 400)
        self.assertIn("already", response.json()["errors"]["__all__"])

    @mock.patch("core.core_inquiries.services.today", return_value=date(2026, 10, 6))
    def test_waitlist_enforces_earliest_date_and_drops_site_visit(self, _today):
        early = self.post(self.url(self.occupied), {"kind": "waitlist", "occupants": [""], "move_in_date": "2026-10-30"})
        self.assertEqual(early.status_code, 400)
        self.assertIn("Nov 2, 2026", early.json()["errors"]["move_in_date"])

        ok = self.post(self.url(self.occupied), {
            "kind": "waitlist", "occupants": [""], "move_in_date": "2026-11-02", "site_visit_date": "2026-10-20",
        })
        self.assertEqual(ok.status_code, 201)
        self.assertIsNone(Application.objects.get().site_visit_date)

    def test_application_shows_in_landlord_requests(self):
        self.apply(self.available)
        self.client.force_login(self.landlord_user)
        context = services.get_inquiries_context(self.landlord_user)
        self.assertEqual(len(context["pending_requests"]), 1)
        self.assertEqual(context["pending_requests_count"], 1)

    def test_site_visit_needs_a_time(self):
        response = self.apply(self.available, site_visit_time="")
        self.assertEqual(response.status_code, 400)
        self.assertIn("site_visit_time", response.json()["errors"])

    def test_site_visit_time_is_saved_as_pending(self):
        self.apply(self.available)
        application = Application.objects.get()
        self.assertEqual(application.site_visit_time.hour, 14)
        self.assertEqual(application.site_visit_status, Application.SiteVisit.PENDING)

    def test_landlords_cannot_apply(self):
        self.client.force_login(self.landlord_user)
        self.assertEqual(self.apply(self.available).status_code, 403)


class MessageTests(Base):

    def send(self, body="Is this still available?", **target):
        target = target or {"unit": str(self.available.pk)}
        return self.post(reverse("core_inquiries:send_inquiry"), {**target, "body": body})

    def reply_url(self, conversation):
        return reverse("core_inquiries:conversation_reply", args=[conversation.pk])

    def test_renter_message_starts_a_thread_for_both_sides(self):
        self.assertEqual(self.send().status_code, 201)
        self.assertEqual(self.send("Second message").status_code, 201)

        conversation = Conversation.objects.get()
        self.assertEqual(conversation.landlord, self.landlord)
        self.assertEqual(conversation.messages.count(), 2)

        landlord_tab = services.get_inquiries_context(self.landlord_user)
        self.assertEqual(landlord_tab["unread_messages_count"], 2)

    def test_landlord_can_reply_after_renter_wrote(self):
        self.send()
        conversation = Conversation.objects.get()
        self.client.force_login(self.landlord_user)
        response = self.post(self.reply_url(conversation), {"body": "Yes it is!"})
        self.assertEqual(response.status_code, 201)

    def test_landlord_cannot_message_first(self):
        # A thread with no renter message (shouldn't happen, but the server must still refuse)
        conversation = Conversation.objects.create(
            renter=self.renter_user.renter, landlord=self.landlord, complex=self.complex,
        )
        self.client.force_login(self.landlord_user)
        response = self.post(self.reply_url(conversation), {"body": "Hi, want to rent?"})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(Message.objects.count(), 0)

    def test_landlords_cannot_start_inquiries(self):
        self.client.force_login(self.landlord_user)
        self.assertEqual(self.send().status_code, 403)

    def test_strangers_cannot_read_a_thread(self):
        self.send()
        conversation = Conversation.objects.get()
        stranger = make_user("other", "renter", "09333333333")
        self.client.force_login(stranger)
        url = reverse("core_inquiries:conversation_detail", args=[conversation.pk])
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_complex_level_inquiry(self):
        self.assertEqual(self.send(complex=str(self.complex.pk)).status_code, 201)
        self.assertIsNone(Conversation.objects.get().unit)

    def test_empty_message_is_rejected(self):
        self.assertEqual(self.send("   ").status_code, 400)


class OneThreadPerLandlordTests(Base):

    def send(self, body, **target):
        return self.post(reverse("core_inquiries:send_inquiry"), {**target, "body": body})

    def test_all_inquire_buttons_lead_to_one_thread(self):
        self.send("About 201", unit=str(self.available.pk))
        self.send("About 401", unit=str(self.occupied.pk))
        self.send("General question", complex=str(self.complex.pk))
        self.send("Follow-up", complex=str(self.complex.pk))

        self.assertEqual(Conversation.objects.count(), 1)
        topics = list(Message.objects.order_by("pk").values_list("topic", flat=True))
        # A topic marks every change of subject, not repeated messages
        self.assertEqual(topics, ["Unit 201 · Sunrise", "Unit 401 · Sunrise", "Sunrise", ""])
        self.assertEqual(Conversation.objects.get().subject, "Sunrise")

    def test_other_landlord_gets_a_separate_thread(self):
        other_user = make_user("other", "landlord", "09444444444")
        other_complex = Complex.objects.create(
            landlord=Landlord.objects.create(user=other_user), area=self.complex.area,
            complex_name="Bajada", address="Bajada", complex_description="x",
            min_price=1, max_price=9, status=Complex.ComplexStatus.ACTIVE,
        )
        self.send("Hi", complex=str(self.complex.pk))
        self.send("Hi", complex=str(other_complex.pk))
        self.assertEqual(Conversation.objects.count(), 2)

    def test_popup_finds_the_thread_from_any_unit(self):
        self.send("About 201", unit=str(self.available.pk))
        url = reverse("core_inquiries:inquiry_thread")
        data = self.client.get(url, {"unit": str(self.occupied.pk)}).json()
        self.assertEqual(len(data["conversation"]["messages"]), 1)


class SeenAndRefreshTests(Base):

    def setUp(self):
        super().setUp()
        self.post(reverse("core_inquiries:send_inquiry"), {"unit": str(self.available.pk), "body": "Hello"})
        self.conversation = Conversation.objects.get()
        self.detail = reverse("core_inquiries:conversation_detail", args=[self.conversation.pk])

    def test_seen_once_the_landlord_opens_the_thread(self):
        message = Message.objects.get()
        self.assertEqual(self.client.get(self.detail).json()["conversation"]["seen"], {})

        self.client.force_login(self.landlord_user)
        self.client.get(self.detail, {"seen": "0"})          # background tab: not seen yet
        self.assertIsNone(Message.objects.get().read_at)
        self.client.get(self.detail)                          # opened: seen
        self.client.force_login(self.renter_user)
        self.assertIn(str(message.pk), self.client.get(self.detail).json()["conversation"]["seen"])

    def test_refresh_returns_only_newer_messages(self):
        first = Message.objects.get()
        self.post(reverse("core_inquiries:send_inquiry"), {"unit": str(self.available.pk), "body": "Second"})
        newer = self.client.get(self.detail, {"after": first.pk}).json()["conversation"]["messages"]
        self.assertEqual([m["body"] for m in newer], ["Second"])

    def test_inbox_lists_newest_thread_first(self):
        self.client.force_login(self.landlord_user)
        data = self.client.get(reverse("core_inquiries:inbox")).json()
        self.assertEqual(data["unread_messages_count"], 1)
        self.assertEqual(data["threads"][0]["preview"], "Hello")


def png_file(name="photo.png"):
    buffer = io.BytesIO()
    Image.new("RGB", (20, 20), "red").save(buffer, "PNG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/png")


class AttachmentTests(Base):

    def send_file(self, upload, body=""):
        return self.client.post(reverse("core_inquiries:send_inquiry"),
                                {"unit": str(self.available.pk), "body": body, "attachment": upload})

    def test_photo_without_text(self):
        with self.settings(STORAGES={"default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
                                     "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}}):
            response = self.send_file(png_file())
            self.assertEqual(response.status_code, 201)
            attachment = response.json()["message"]["attachment"]
            self.assertEqual(attachment["kind"], "image")
            self.assertEqual(Message.objects.get().preview, "📎 photo.png")

    def test_pdf_contract(self):
        with self.settings(STORAGES={"default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
                                     "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}}):
            pdf = SimpleUploadedFile("contract.pdf", b"%PDF-1.4 fake but valid header", content_type="application/pdf")
            response = self.send_file(pdf, "Here's the contract")
            self.assertEqual(response.status_code, 201)
            self.assertEqual(response.json()["message"]["attachment"]["kind"], "pdf")

    def test_renamed_file_is_rejected(self):
        fake = SimpleUploadedFile("contract.pdf", b"MZ this is an exe", content_type="application/pdf")
        response = self.send_file(fake)
        self.assertEqual(response.status_code, 400)
        self.assertIn("attachment", response.json()["errors"])

    def test_too_big(self):
        big = SimpleUploadedFile("big.pdf", b"%PDF-" + b"0" * (5 * 1024 * 1024), content_type="application/pdf")
        self.assertEqual(self.send_file(big).status_code, 400)

    def test_unsupported_type(self):
        doc = SimpleUploadedFile("notes.docx", b"PK...", content_type="application/octet-stream")
        self.assertEqual(self.send_file(doc).status_code, 400)

# =========================================================
# PENDING REQUESTS / WAITLIST / ARCHIVE
# =========================================================

from core.core_rentals.models import Tenancy   # noqa: E402


class RequestWorkflowTests(Base):

    def setUp(self):
        super().setUp()
        self.application = services.create_application(
            self.renter_user, self.available, "apply", ["", "Elise Tan"],
            date.today() + timedelta(days=20), date.today() + timedelta(days=3), time_of(14),
        )

    def as_landlord(self):
        self.client.force_login(self.landlord_user)

    def url(self, name, application=None):
        return reverse(f"core_inquiries:{name}", args=[(application or self.application).pk])

    def refresh(self):
        self.application.refresh_from_db()
        return self.application

    def waitlist_request(self, renter_user=None):
        return services.create_application(
            renter_user or self.renter_user, self.occupied, "waitlist", [""], date(2026, 12, 1),
        )

    # ---------- reject / cancel ----------

    def test_landlord_must_give_a_reason(self):
        self.as_landlord()
        response = self.post(self.url("reject_request"), {})
        self.assertEqual(response.status_code, 400)
        self.assertIn("reason", response.json()["errors"])

    def test_reject_moves_request_to_archive(self):
        self.as_landlord()
        response = self.post(self.url("reject_request"), {"reason": "requirements", "reason_note": "Need 2 IDs"})
        self.assertEqual(response.status_code, 200)
        application = self.refresh()
        self.assertEqual(application.status, Application.Status.DECLINED)
        self.assertEqual(application.reason_note, "Need 2 IDs")

        tabs = services.get_inquiries_context(self.renter_user)
        self.assertEqual(tabs["pending_requests_count"], 0)
        self.assertEqual([a.pk for a in tabs["archived_requests"]], [application.pk])

    def test_other_reason_needs_a_note(self):
        self.as_landlord()
        response = self.post(self.url("reject_request"), {"reason": "other"})
        self.assertIn("reason_note", response.json()["errors"])

    def test_renter_reasons_are_not_allowed_for_landlords(self):
        self.as_landlord()
        response = self.post(self.url("reject_request"), {"reason": "found_other"})
        self.assertEqual(response.status_code, 400)

    def test_renter_can_cancel_without_a_reason(self):
        response = self.post(self.url("cancel_request"), {})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.refresh().status, Application.Status.WITHDRAWN)
        # ...and shows up in the landlord's archive as cancelled
        archive = services.get_inquiries_context(self.landlord_user)["archived_requests"]
        self.assertEqual(archive[0].get_status_display(), "Cancelled")

    def test_renter_cannot_touch_someone_elses_request(self):
        other = make_user("bea", "renter", "09333333333")
        Renter.objects.create(user=other)
        self.client.force_login(other)
        self.assertEqual(self.post(self.url("cancel_request"), {}).status_code, 404)

    def test_other_landlord_cannot_reject(self):
        stranger = make_user("mark", "landlord", "09444444444")
        Landlord.objects.create(user=stranger)
        self.client.force_login(stranger)
        self.assertEqual(self.post(self.url("reject_request"), {"reason": "requirements"}).status_code, 404)

    def test_archive_keeps_requests_for_30_days(self):
        self.post(self.url("cancel_request"), {})
        Application.objects.filter(pk=self.application.pk).update(
            decided_at=self.refresh().decided_at - timedelta(days=31),
        )
        self.assertEqual(services.get_inquiries_context(self.renter_user)["archive_count"], 0)

    # ---------- edit ----------

    def test_edit_changes_dates_and_resets_site_visit(self):
        self.application.site_visit_status = Application.SiteVisit.CONFIRMED
        self.application.save()
        response = self.post(self.url("edit_request"), {
            "occupants": [""], "move_in_date": (date.today() + timedelta(days=25)).isoformat(),
            "site_visit_date": (date.today() + timedelta(days=4)).isoformat(), "site_visit_time": "10:30",
        })
        self.assertEqual(response.status_code, 200)
        application = self.refresh()
        self.assertEqual(application.occupants, [self.renter_user.display_name])
        self.assertEqual(application.site_visit_status, Application.SiteVisit.PENDING)

    def test_bell_colours(self):
        # New request -> yellow
        tones = {n["title"]: n["tone"] for n in services.get_inquiries_context(self.landlord_user)["notifications"]}
        self.assertEqual(tones, {"New tenant application": "yellow"})

        # Renter changes the dates -> yellow "Request updated" with the new values
        self.post(self.url("edit_request"), {
            "occupants": [""], "move_in_date": (date.today() + timedelta(days=25)).isoformat(),
            "site_visit_date": (date.today() + timedelta(days=4)).isoformat(), "site_visit_time": "10:30",
        })
        note = services.get_inquiries_context(self.landlord_user)["notifications"][0]
        self.assertEqual((note["title"], note["tone"]), ("Request updated", "yellow"))
        self.assertIn("10:30 AM", note["message"])

        # Renter messages -> green; renter cancels -> red
        self.post(reverse("core_inquiries:send_inquiry"), {"unit": str(self.available.pk), "body": "Hi!"})
        self.post(self.url("cancel_request"), {})
        tones = {n["title"]: n["tone"] for n in services.get_inquiries_context(self.landlord_user)["notifications"]}
        self.assertEqual(tones, {"New message": "green", "Request cancelled": "red"})

    def test_edit_without_visit_clears_it(self):
        self.post(self.url("edit_request"), {
            "occupants": [""], "move_in_date": (date.today() + timedelta(days=25)).isoformat(),
        })
        application = self.refresh()
        self.assertIsNone(application.site_visit_date)
        self.assertEqual(application.site_visit_status, "")

    # ---------- site visit ----------

    def test_landlord_confirms_site_visit(self):
        self.as_landlord()
        response = self.post(self.url("site_visit_decision"), {"decision": "confirm"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.refresh().site_visit_status, Application.SiteVisit.CONFIRMED)

    # ---------- approve as tenant (= Manage Rentals assign) ----------

    def test_approve_as_tenant_creates_tenancy_and_closes_others(self):
        other = make_user("bea", "renter", "09333333333")
        Renter.objects.create(user=other)
        rival = services.create_application(other, self.available, "apply", [""], date.today() + timedelta(days=10))

        self.as_landlord()
        response = self.post(reverse("core_rentals:assign_tenant", args=[self.available.pk]), {
            "application": str(self.application.pk), "start_date": (date.today() + timedelta(days=20)).isoformat(),
        })
        self.assertEqual(response.status_code, 201)
        self.assertEqual(self.refresh().status, Application.Status.ACCEPTED)
        self.assertTrue(Tenancy.objects.filter(application=self.application, status="active").exists())
        rival.refresh_from_db()
        self.assertEqual(rival.status, Application.Status.CLOSED)
        self.assertEqual(rival.reason, Application.Reason.UNIT_RENTED)

    # ---------- waitlist ----------

    def test_approve_for_waitlist(self):
        application = self.waitlist_request()
        self.as_landlord()
        response = self.post(self.url("approve_waitlist", application), {})
        self.assertEqual(response.status_code, 200)
        application.refresh_from_db()
        self.assertEqual(application.status, Application.Status.WAITLISTED)

        tabs = services.get_inquiries_context(self.landlord_user)
        group = tabs["waitlist_groups"][0]
        self.assertEqual(group["unit"], self.occupied)
        self.assertEqual(group["outlook"]["key"], "occupied")
        self.assertFalse(group["applications"][0].can_notify)

    def test_tenant_application_cannot_go_to_waitlist(self):
        self.as_landlord()
        self.assertEqual(self.post(self.url("approve_waitlist"), {}).status_code, 400)

    def test_waitlisted_renter_cannot_apply_twice(self):
        application = self.waitlist_request()
        workflow_approve(application)
        with self.assertRaises(Exception):
            self.waitlist_request()

    def test_notify_only_once_the_unit_is_vacant(self):
        application = self.waitlist_request()
        workflow_approve(application)
        self.as_landlord()
        self.assertEqual(self.post(self.url("notify_applicant", application), {}).status_code, 400)

        self.occupied.availability = Unit.Availability.AVAILABLE
        self.occupied.save()
        tabs = services.get_inquiries_context(self.landlord_user)
        self.assertTrue(tabs["waitlist_groups"][0]["applications"][0].can_notify)

        response = self.post(self.url("notify_applicant", application), {})
        self.assertEqual(response.status_code, 200)
        application.refresh_from_db()
        self.assertIsNotNone(application.notified_at)
        # The renter got a message
        self.assertTrue(Conversation.objects.get(renter__user=self.renter_user).messages.exists())

    def test_assigning_someone_archives_the_waitlist(self):
        application = self.waitlist_request()
        workflow_approve(application)
        self.occupied.availability = Unit.Availability.AVAILABLE
        self.occupied.save()

        self.as_landlord()
        response = self.post(reverse("core_rentals:assign_tenant", args=[self.occupied.pk]), {
            "tenant_name": "Walk In", "occupant_count": 1, "start_date": date.today().isoformat(),
        })
        self.assertEqual(response.status_code, 201)
        application.refresh_from_db()
        self.assertEqual(application.status, Application.Status.CLOSED)

    def test_recording_current_tenant_keeps_the_waitlist(self):
        application = self.waitlist_request()
        workflow_approve(application)
        self.as_landlord()
        # The unit is already occupied; the landlord just records who lives there
        self.post(reverse("core_rentals:assign_tenant", args=[self.occupied.pk]), {
            "tenant_name": "Current Tenant", "occupant_count": 1, "start_date": "2025-10-26",
        })
        application.refresh_from_db()
        self.assertEqual(application.status, Application.Status.WAITLISTED)

    def test_waitlisted_renter_can_be_assigned_in_manage_rentals(self):
        application = self.waitlist_request()
        workflow_approve(application)
        self.occupied.availability = Unit.Availability.AVAILABLE
        self.occupied.save()
        self.as_landlord()
        response = self.post(reverse("core_rentals:assign_tenant", args=[self.occupied.pk]), {
            "application": str(application.pk), "start_date": "2026-12-01",
        })
        self.assertEqual(response.status_code, 201)
        application.refresh_from_db()
        self.assertEqual(application.status, Application.Status.ACCEPTED)

    def test_dashboards_render(self):
        self.waitlist_request()
        response = self.client.get(reverse("core_renters:dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Pending Requests")
        self.assertContains(response, "Edit Application")
        self.as_landlord()
        response = self.client.get(reverse("core_landlords:dashboard"))
        self.assertContains(response, "Approve as Tenant")
        self.assertContains(response, "Approve for Waitlist")


def time_of(hour):
    from datetime import time
    return time(hour, 0)


def workflow_approve(application):
    from .workflow import approve_waitlist
    approve_waitlist(application)


class ClearNotificationsTests(Base):

    def test_clear_all_hides_older_notifications_only(self):
        self.client.force_login(self.landlord_user)
        Application.objects.create(renter=self.renter_user.renter, unit=self.available, kind="apply",
                                   occupants=["Arem"], move_in_date=date.today() + timedelta(days=10))
        bell = lambda: self.client.get(reverse("account_notifications")).json()
        self.assertIn("New tenant application", bell()["html"])

        response = self.client.post(reverse("account_notifications_clear"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("all caught up", bell()["html"])
        self.assertEqual(bell()["new_count"], 0)

        # Something newer still shows
        Application.objects.create(renter=self.renter_user.renter, unit=self.occupied, kind="waitlist",
                                   occupants=["Arem"], move_in_date=date.today() + timedelta(days=60))
        html = bell()["html"]
        self.assertIn("waitlist", html.lower())
        self.assertNotIn("New tenant application", html)

