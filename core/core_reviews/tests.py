# core_reviews/tests.py
import io
import json
from datetime import date, timedelta

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from core.core_listings.models import Area, Complex, Unit
from core.core_rentals.services import assign_tenant
from core.models import Landlord, Renter, User

from .models import Review


def make_user(username, role, phone, first="Test", last="User"):
    user = User.objects.create_user(
        username=username, password="pw-12345!", first_name=first, last_name=last,
        phone_number=phone, sex="female", role=role,
    )
    (Landlord if role == "landlord" else Renter).objects.create(user=user)
    return user


def photo(name="room.jpg", kind="JPEG", size=(40, 30)):
    buffer = io.BytesIO()
    Image.new("RGB", size, (90, 140, 200)).save(buffer, kind)
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/jpeg" if kind == "JPEG" else "image/png")


STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}


@override_settings(STORAGES=STORAGES)
class ReviewTests(TestCase):

    def setUp(self):
        self.landlord = make_user("liza", "landlord", "09111111111", "Liza", "Soberano")
        self.renter = make_user("rina", "renter", "09222222222", "Rina", "Santos")
        self.other = make_user("ben", "renter", "09333333333")
        self.complex = Complex.objects.create(
            landlord=self.landlord.landlord, area=Area.objects.create(area_name="Davao City"),
            complex_name="Sunrise", address="Poblacion", complex_description="x",
            min_price=5000, max_price=20000, status="active", approval_status="approved", lease_term="monthly",
        )
        self.unit = Unit.objects.create(complex=self.complex, identifier=1, bedroom_type="studio", width_dimension=4,
                                        length_dimension=5, furnish_level="unfurnished", max_occupant=2, price=8000)
        start = date.today() - timedelta(days=20)
        self.tenancy = assign_tenant(self.unit, start, tenant_name="Rina Santos", on=start)
        self.tenancy.renter = self.renter.renter
        self.tenancy.save()
        self.url = reverse("core_reviews:save_review", args=[self.tenancy.pk])
        self.client.force_login(self.renter)

    def post(self, **overrides):
        data = {"complex_rating": "4", "unit_rating": "5", "landlord_rating": "3",
                "complex_feedback": "  Quiet place.  ", "unit_feedback": "", "landlord_feedback": "Slow replies."}
        data.update(overrides)
        return self.client.post(self.url, data, HTTP_ACCEPT="application/json")

    def test_leave_a_review_with_photos(self):
        response = self.post(photos=[photo(), photo("b.png", "PNG")])
        self.assertEqual(response.status_code, 201)
        review = Review.objects.get()
        self.assertEqual((review.complex_rating, review.unit_rating, review.landlord_rating), (4, 5, 3))
        self.assertEqual(review.complex_feedback, "Quiet place.")
        self.assertEqual((review.complex, review.unit, review.landlord), (self.complex, self.unit, self.landlord.landlord))
        self.assertEqual(review.photos.count(), 2)

    def test_editing_updates_the_same_review(self):
        self.post(photos=[photo(), photo("b.jpg")])
        first_photo = Review.objects.get().photos.first()
        response = self.post(complex_rating="2", remove_photos=[first_photo.pk], photos=[photo("c.jpg")])
        self.assertEqual(response.status_code, 200)
        review = Review.objects.get()
        self.assertEqual(review.complex_rating, 2)
        self.assertEqual(review.photos.count(), 2)
        self.assertFalse(review.photos.filter(pk=first_photo.pk).exists())

    def test_validation(self):
        self.assertIn("unit_rating", self.post(unit_rating="").json()["errors"])
        self.assertIn("landlord_rating", self.post(landlord_rating="6").json()["errors"])
        self.assertIn("complex_feedback", self.post(complex_feedback="x" * 501).json()["errors"])
        too_many = self.post(photos=[photo(f"{i}.jpg") for i in range(6)])
        self.assertIn("up to 5 photos", too_many.json()["errors"]["photos"])
        fake = SimpleUploadedFile("fake.jpg", b"not an image", content_type="image/jpeg")
        self.assertIn("PNG or JPG", self.post(photos=[fake]).json()["errors"]["photos"])
        self.assertFalse(Review.objects.exists())

    def test_only_the_tenant_after_the_rental_starts(self):
        self.client.force_login(self.other)
        self.assertEqual(self.post().status_code, 404)

        self.client.force_login(self.renter)
        self.tenancy.start_date = date.today() + timedelta(days=5)
        self.tenancy.save()
        self.assertEqual(self.post().status_code, 403)
        self.assertFalse(Review.objects.exists())

    def test_rental_history_button(self):
        page = self.client.get(reverse("core_renters:dashboard") + "?tab=rentals")
        self.assertContains(page, "Leave a Review")
        self.assertContains(page, 'data-review-modal')
        self.post()
        page = self.client.get(reverse("core_renters:dashboard") + "?tab=rentals")
        self.assertContains(page, "Edit Review")
        data = json.loads(page.context["current_rentals"][0].review_data)
        self.assertEqual(data["complex_rating"], 4)

    def test_listing_pages_show_stars_and_reviews(self):
        self.post(photos=[photo()])
        response = self.client.get(reverse("core_listings:renter_complex_detail", args=[self.complex.pk]))
        self.assertEqual(response.context["complex_rating"], {"avg": 4.0, "count": 1})
        self.assertEqual(response.context["landlord"]["rating"], {"avg": 3.0, "count": 1})
        self.assertEqual(response.context["units"][0].rating, {"avg": 5.0, "count": 1})
        self.assertContains(response, "Rina S.")             # first name + last initial only
        self.assertContains(response, "Quiet place.")
        self.assertContains(response, 'aria-label="4.0 out of 5 stars"')
        self.assertEqual(response.context["review_summary"]["breakdown"][1], {"stars": 4, "count": 1, "percent": 100})

        unit_page = self.client.get(reverse("core_listings:renter_unit_detail", args=[self.unit.pk]))
        self.assertEqual(unit_page.context["unit"].rating, {"avg": 5.0, "count": 1})

    def test_no_reviews_yet(self):
        response = self.client.get(reverse("core_listings:renter_complex_detail", args=[self.complex.pk]))
        self.assertContains(response, "No reviews yet")
        self.assertIsNone(response.context["units"][0].rating)
