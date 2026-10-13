import io
from datetime import timedelta
from unittest import mock

from django.core.files.storage import InMemoryStorage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from core.core_listings.models import Area, Complex
from core.models import Landlord, Renter, User

from . import services
from .extractors import ai_reader
from .models import VerificationRequest

Status = VerificationRequest.Status
FILE_FIELDS = ("id_photo", "selfie", "ownership_document")
TEST_STORAGES = {"default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
                 "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
                 "verification": {"BACKEND": "django.core.files.storage.InMemoryStorage"}}


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


def pdf(name="permit.pdf"):
    return SimpleUploadedFile(name, b"%PDF-1.4 fake permit", content_type="application/pdf")


def clear_result(**changes):
    """What Claude returns when everything checks out (change one part to test the rules)."""
    result = {
        "government_id": {"readable": True, "document_type_seen": "Driver's license", "name_on_document": "Liza Test",
                          "name_matches_account": True, "signs_of_editing": False, "notes": "",
                          "is_government_id": True, "expiry_date": "2030-01-01", "is_expired": False},
        "selfie": {"readable": True, "shows_person_holding_id": True, "notes": ""},
        "ownership_document": {"readable": True, "document_type_seen": "Mayor's permit", "name_on_document": "Liza Test",
                               "name_matches_account": True, "signs_of_editing": False, "notes": "",
                               "matches_claimed_type": True, "property_address": "Poblacion, Davao City"},
        "verdict": "pass", "summary": "All documents match.", "message_for_landlord": "",
    }
    for path, value in changes.items():
        section, _, key = path.partition("__")
        if key:
            result[section][key] = value
        else:
            result[section] = value
    return result


@override_settings(STORAGES=TEST_STORAGES, ANTHROPIC_API_KEY="")
class Base(TestCase):

    def setUp(self):
        # The documents' storage is picked when the model loads, so swap it here
        memory = InMemoryStorage()
        for name in FILE_FIELDS:
            field = VerificationRequest._meta.get_field(name)
            patcher = mock.patch.object(field, "storage", memory)
            patcher.start()
            self.addCleanup(patcher.stop)

        self.landlord = make_user("liza", "landlord", "09111111111")
        self.client.force_login(self.landlord)

    def documents(self, **changes):
        data = {"id_type": "drivers_license", "id_photo": jpg(), "selfie": jpg("selfie.jpg"),
                "ownership_type": "business_permit", "ownership_document": pdf()}
        data.update(changes)
        return data

    def make_request(self, status=Status.CHECKING, **extra):
        return VerificationRequest.objects.create(
            landlord=self.landlord.landlord, id_type="drivers_license", id_photo=jpg(), selfie=jpg("selfie.jpg"),
            ownership_type="business_permit", ownership_document=pdf(), status=status, **extra,
        )


class DecideTests(TestCase):

    def test_everything_clear_is_approved(self):
        self.assertEqual(services.AIVerdict(clear_result()).decide(), (Status.APPROVED, ""))

    def test_any_doubt_goes_to_an_admin(self):
        for change in ({"government_id__name_matches_account": False}, {"government_id__is_expired": True},
                       {"ownership_document__signs_of_editing": True}, {"selfie__shows_person_holding_id": False},
                       {"ownership_document__name_matches_account": False}, {"verdict": "review"}):
            with self.subTest(change):
                self.assertEqual(services.AIVerdict(clear_result(**change)).status, Status.REVIEW)

    def test_pass_verdict_does_not_override_a_failed_check(self):
        result = clear_result(government_id__is_government_id=False)
        self.assertEqual(result["verdict"], "pass")
        self.assertEqual(services.AIVerdict(result).status, Status.REVIEW)

    def test_missing_fields_are_not_trusted(self):
        self.assertEqual(services.AIVerdict({"verdict": "pass"}).status, Status.REVIEW)

    def test_unreadable_document_asks_to_resubmit(self):
        verdict = services.AIVerdict(clear_result(verdict="resubmit", message_for_landlord="Your ID is blurry."))
        status, message = verdict.decide()
        self.assertEqual((status, message), (Status.RESUBMIT, "Your ID is blurry."))
        self.assertEqual(services.AIVerdict(clear_result(verdict="resubmit")).message,
                         VerificationRequest.RESUBMIT_DEFAULT)


class SubmitTests(Base):

    def submit(self, **changes):
        return self.client.post(reverse("core_verification:submit"), self.documents(**changes))

    def test_submit_saves_and_starts_the_check(self):
        with mock.patch.object(services.DocumentCheck, "start") as start, self.captureOnCommitCallbacks(execute=True):
            response = self.submit()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": True, "state": "checking"})
        request = VerificationRequest.objects.get()
        self.assertEqual(request.status, Status.CHECKING)
        self.assertTrue(request.id_photo.name.startswith(f"{self.landlord.landlord.pk}/"))
        self.assertRegex(request.id_photo.name, r"/[0-9a-f]{32}\.jpg$")      # random name, not "id.jpg"
        start.assert_called_once_with(request.pk)

    def test_photo_of_ownership_works_too(self):
        with mock.patch.object(services.DocumentCheck, "start"):
            self.assertEqual(self.submit(ownership_document=jpg("title.jpg")).status_code, 200)

    def test_missing_and_fake_files_are_refused(self):
        fake = SimpleUploadedFile("id.jpg", b"MZ this is an exe", content_type="image/jpeg")
        response = self.submit(id_photo=fake, selfie="", ownership_type="")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(set(response.json()["errors"]), {"id_photo", "selfie", "ownership_type"})
        self.assertFalse(VerificationRequest.objects.exists())

    def test_senior_citizen_id_is_accepted_and_other_is_gone(self):
        with mock.patch.object(services.DocumentCheck, "start"):
            self.assertEqual(self.submit(id_type="senior_citizen").status_code, 200)
        VerificationRequest.objects.all().delete()
        response = self.submit(id_type="other")
        self.assertEqual(response.status_code, 400)
        self.assertIn("id_type", response.json()["errors"])

    def test_pdf_is_not_accepted_as_an_id(self):
        response = self.submit(id_photo=pdf("id.pdf"))
        self.assertEqual(response.status_code, 400)
        self.assertIn("id_photo", response.json()["errors"])

    def test_cannot_submit_again_while_waiting(self):
        self.make_request(Status.REVIEW)
        self.assertEqual(self.submit().status_code, 400)
        self.assertEqual(VerificationRequest.objects.count(), 1)

    def test_can_submit_again_when_asked_to(self):
        self.make_request(Status.RESUBMIT, message="Blurry")
        with mock.patch.object(services.DocumentCheck, "start"):
            self.assertEqual(self.submit().status_code, 200)
        self.assertEqual(services.LandlordVerification(self.landlord).state, Status.CHECKING)

    def test_renters_cannot_submit(self):
        self.client.force_login(make_user("arem", "renter", "09222222222"))
        self.assertEqual(self.submit().status_code, 403)


class CheckTests(Base):

    def test_clear_documents_verify_the_landlord(self):
        request = self.make_request()
        with mock.patch.object(ai_reader.AIReader, "read", return_value=clear_result()):
            services.DocumentCheck(request.pk).run()
        request.refresh_from_db()
        self.landlord.refresh_from_db()
        self.assertEqual(request.status, Status.APPROVED)
        self.assertEqual(request.ai_summary, "All documents match.")
        self.assertIsNone(request.reviewed_by)
        self.assertTrue(self.landlord.is_verified)

    def test_doubtful_documents_wait_for_an_admin(self):
        request = self.make_request()
        with mock.patch.object(ai_reader.AIReader, "read",
                               return_value=clear_result(ownership_document__name_matches_account=False)):
            services.DocumentCheck(request.pk).run()
        request.refresh_from_db()
        self.landlord.refresh_from_db()
        self.assertEqual(request.status, Status.REVIEW)
        self.assertFalse(self.landlord.is_verified)

    def test_no_api_key_means_admin_review(self):
        request = self.make_request()
        services.DocumentCheck(request.pk).run()          # ANTHROPIC_API_KEY is "" in these tests
        request.refresh_from_db()
        self.assertEqual(request.status, Status.REVIEW)
        self.assertIn("ANTHROPIC_API_KEY", request.ai_summary)

    def test_unexpected_error_means_admin_review(self):
        request = self.make_request()
        with mock.patch.object(ai_reader.AIReader, "read", side_effect=RuntimeError("boom")):
            services.DocumentCheck(request.pk).run()
        request.refresh_from_db()
        self.assertEqual(request.status, Status.REVIEW)

    def test_lost_check_goes_to_admin_review(self):
        request = self.make_request()
        VerificationRequest.objects.filter(pk=request.pk).update(created_at=timezone.now() - timedelta(minutes=11))
        self.assertEqual(services.LandlordVerification(self.landlord).state, Status.REVIEW)

    def test_status_endpoint(self):
        self.make_request()
        response = self.client.get(reverse("core_verification:status"))
        self.assertEqual(response.json(), {"state": "checking"})


@override_settings(ANTHROPIC_API_KEY="test-key", VERIFICATION_AI_MODEL="claude-opus-5-5")
class AIReaderTests(Base):

    def fake_response(self, text, stop_reason="end_turn"):
        return mock.Mock(stop_reason=stop_reason, content=[mock.Mock(type="text", text=text)])

    def test_sends_the_three_documents_and_parses_the_answer(self):
        request = self.make_request()
        with mock.patch("anthropic.Anthropic") as client_class:
            create = client_class.return_value.beta.messages.create
            create.return_value = self.fake_response('{"verdict": "pass"}')
            self.assertEqual(ai_reader.AIReader(request).read(), {"verdict": "pass"})

        kwargs = create.call_args.kwargs
        self.assertEqual(kwargs["model"], "claude-opus-5-5")
        self.assertEqual(kwargs["output_config"]["format"]["schema"], ai_reader.RESULT_SCHEMA)
        self.assertEqual(kwargs["fallbacks"], "default")
        blocks = [block["type"] for block in kwargs["messages"][0]["content"]]
        self.assertEqual(blocks.count("image"), 2)        # ID + selfie
        self.assertEqual(blocks.count("document"), 1)     # the PDF permit
        self.assertIn("Liza Test", kwargs["messages"][0]["content"][-1]["text"])

    def test_refusal_is_an_error(self):
        request = self.make_request()
        with mock.patch("anthropic.Anthropic") as client_class:
            client_class.return_value.beta.messages.create.return_value = self.fake_response("", "refusal")
            with self.assertRaises(ai_reader.AIReadError):
                ai_reader.AIReader(request).read()


class AdminDecisionTests(Base):

    def setUp(self):
        super().setUp()
        self.admin = make_user("admin", "admin", "09333333333", is_staff=True, is_superuser=True)
        self.client.force_login(self.admin)

    def change(self, request, status, message=""):
        url = reverse("admin:core_verification_verificationrequest_change", args=[request.pk])
        return self.client.post(url, {"status": status, "message": message})

    def test_admin_page_shows_the_documents(self):
        request = self.make_request(Status.REVIEW, ai_summary="Name differs on the permit.")
        response = self.client.get(reverse("admin:core_verification_verificationrequest_change", args=[request.pk]))
        self.assertContains(response, "Name differs on the permit.")
        self.assertContains(response, "Open PDF")

    def test_approving_verifies_the_landlord(self):
        request = self.make_request(Status.REVIEW)
        self.assertEqual(self.change(request, Status.APPROVED).status_code, 302)
        request.refresh_from_db()
        self.landlord.refresh_from_db()
        self.assertEqual(request.reviewed_by, self.admin)
        self.assertTrue(self.landlord.is_verified)

    def test_rejecting_needs_a_reason(self):
        request = self.make_request(Status.REVIEW)
        self.assertEqual(self.change(request, Status.REJECTED).status_code, 200)     # form shown again
        self.change(request, Status.REJECTED, "The permit belongs to someone else.")
        request.refresh_from_db()
        self.assertEqual(request.status, Status.REJECTED)
        self.assertEqual(services.LandlordVerification(self.landlord).state, Status.REJECTED)

    def test_rejecting_an_approved_landlord_removes_the_badge(self):
        request = self.make_request(Status.REVIEW)
        request.approve(self.admin)
        self.change(request, Status.REJECTED, "Fake documents.")
        self.landlord.refresh_from_db()
        self.assertFalse(self.landlord.is_verified)


class DashboardTests(Base):

    def dashboard(self):
        with mock.patch("core.core_landlords.sections.HomeSection.context", return_value={}):
            return self.client.get(reverse("core_landlords:dashboard"))

    def test_new_landlord_gets_the_pop_up(self):
        response = self.dashboard()
        self.assertContains(response, "data-auto-open")
        self.assertContains(response, "Verify your account to publish listings, post bulletins and file reports.")

    def test_waiting_landlord_sees_the_banner_only(self):
        self.make_request(Status.REVIEW)
        response = self.dashboard()
        self.assertNotContains(response, "data-auto-open")
        self.assertContains(response, "Your documents are with our team.")

    def test_resubmit_shows_what_to_fix(self):
        self.make_request(Status.RESUBMIT, message="Your selfie is too dark.")
        response = self.dashboard()
        self.assertContains(response, "data-auto-open")
        self.assertContains(response, "Your selfie is too dark.")

    def test_submitted_documents_can_be_viewed(self):
        request = self.make_request(Status.REVIEW)
        response = self.dashboard()
        self.assertContains(response, "data-verify-docs-open")
        self.assertContains(response, "Your submitted documents")
        self.assertContains(response, f'data-lightbox-src="{request.id_photo.url}"')
        self.assertContains(response, "data-verify-lightbox")

    def test_no_documents_button_before_submitting(self):
        self.assertNotContains(self.dashboard(), "data-verify-docs-open")

    def test_bulletin_and_report_buttons_need_verification(self):
        self.assertContains(self.dashboard(), "data-verify-required", count=4)    # bulletin x2, report x2
        self.landlord.is_verified = True
        self.landlord.save()
        self.assertNotContains(self.dashboard(), "data-verify-required")

    def test_welcome_once_after_approval(self):
        request = self.make_request(Status.REVIEW)
        request.approve(None)
        self.assertContains(self.dashboard(), "You're verified")
        self.client.post(reverse("core_verification:welcome_seen"))
        response = self.dashboard()
        self.assertNotContains(response, "You're verified")
        self.assertNotContains(response, "data-verify-banner")


class PurgeTests(Base):
    """Privacy Notice: rejected / replaced documents are deleted 90 days after the decision."""

    def old(self, status, days, **extra):
        request = self.make_request(status, **extra)
        VerificationRequest.objects.filter(pk=request.pk).update(
            created_at=timezone.now() - timedelta(days=days))
        return request

    def test_old_rejected_and_replaced_documents_are_deleted(self):
        rejected = self.old(Status.REJECTED, 100, decided_at=timezone.now() - timedelta(days=91), ai_result={"x": 1})
        replaced = self.old(Status.RESUBMIT, 100)                     # asked by the AI: no decided_at
        recent = self.old(Status.REJECTED, 30, decided_at=timezone.now() - timedelta(days=30))
        approved = self.old(Status.APPROVED, 400, decided_at=timezone.now() - timedelta(days=400))
        storage = rejected.id_photo.storage
        old_name = rejected.id_photo.name

        self.assertEqual(services.DocumentPurge().run(), 2)

        for request in (rejected, replaced):
            request.refresh_from_db()
            self.assertTrue(request.documents_deleted)
            self.assertEqual(request.ownership_document.name, "")
        self.assertIsNone(rejected.ai_result)
        self.assertEqual(rejected.status, Status.REJECTED)              # the rejection still counts
        self.assertFalse(storage.exists(old_name))
        for request in (recent, approved):
            request.refresh_from_db()
            self.assertFalse(request.documents_deleted)

    def test_dashboard_hides_deleted_documents(self):
        self.old(Status.REJECTED, 100, decided_at=timezone.now() - timedelta(days=91), message="Fake ID.")
        services.DocumentPurge().run()
        with mock.patch("core.core_landlords.sections.HomeSection.context", return_value={}):
            response = self.client.get(reverse("core_landlords:dashboard"))
        self.assertContains(response, "Fake ID.")
        self.assertNotContains(response, "data-verify-docs-open")

    def test_command(self):
        from django.core.management import call_command
        self.old(Status.RESUBMIT, 100)
        out = io.StringIO()
        call_command("purge_verification_documents", stdout=out)
        self.assertIn("Cleaned 1", out.getvalue())


class PublishingTests(Base):

    def setUp(self):
        super().setUp()
        self.complex = Complex.objects.create(
            landlord=self.landlord.landlord, area=Area.objects.create(area_name="Davao City"),
            complex_name="Sunrise", address="Poblacion", complex_description="x",
            min_price=5000, max_price=20000, status="unpublished", lease_term="monthly",
        )

    def make_public(self):
        return self.client.post(reverse("core_listings:property_set_visibility", args=[self.complex.pk]),
                                {"visibility": "active"}, HTTP_ACCEPT="application/json")

    def test_unverified_landlord_cannot_publish(self):
        response = self.make_public()
        self.assertEqual(response.status_code, 403)
        self.assertIn("Verify your account", response.json()["error"])
        self.complex.refresh_from_db()
        self.assertEqual(self.complex.status, "unpublished")

    def test_verified_landlord_can_publish(self):
        self.landlord.is_verified = True
        self.landlord.save()
        self.assertEqual(self.make_public().status_code, 200)
        self.complex.refresh_from_db()
        self.assertEqual(self.complex.status, "active")

    def test_unverified_landlord_can_still_unpublish(self):
        Complex.objects.filter(pk=self.complex.pk).update(status="active")
        response = self.client.post(reverse("core_listings:property_set_visibility", args=[self.complex.pk]),
                                    {"visibility": "unpublished"}, HTTP_ACCEPT="application/json")
        self.assertEqual(response.status_code, 200)


class PostingTests(Base):
    """Unverified landlords can't post bulletins or file reports."""

    def post_bulletin(self):
        return self.client.post(reverse("calendar:post_bulletin"),
                                data='{"message": "Water interruption tomorrow", "audience": "all"}',
                                content_type="application/json")

    def file_report(self):
        return self.client.post(reverse("core_reports:create"), {"category": "scam", "description": "x"})

    def test_unverified_landlord_cannot_post_a_bulletin(self):
        response = self.post_bulletin()
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["errors"]["__all__"], services.NOT_VERIFIED_TO_POST)

    def test_unverified_landlord_cannot_file_a_report(self):
        response = self.file_report()
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["errors"]["__all__"], services.NOT_VERIFIED_TO_POST)

    def test_verified_landlord_gets_past_the_check(self):
        self.landlord.is_verified = True
        self.landlord.save()
        self.assertNotEqual(self.post_bulletin().status_code, 403)
        self.assertNotEqual(self.file_report().status_code, 403)

    def test_renters_are_not_affected(self):
        self.client.force_login(make_user("arem", "renter", "09222222222"))
        response = self.file_report()
        self.assertNotEqual(response.status_code, 403)
