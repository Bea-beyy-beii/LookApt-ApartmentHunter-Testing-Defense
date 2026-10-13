# core_reviews/models.py
# - Review: a renter's ratings (1-5 stars) of the complex, the unit and the
#   landlord, with optional feedback. One per tenancy (Rental History).
# - ReviewPhoto: up to 5 photos attached to a review.
import uuid

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

STARS = [MinValueValidator(1), MaxValueValidator(5)]


class Review(models.Model):
    review_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    tenancy = models.OneToOneField("core_rentals.Tenancy", on_delete=models.CASCADE, related_name="review")
    # Copied from the tenancy so the listing pages can average them quickly
    renter = models.ForeignKey("core.Renter", on_delete=models.CASCADE, related_name="reviews")
    complex = models.ForeignKey("core_listings.Complex", on_delete=models.CASCADE, related_name="reviews")
    unit = models.ForeignKey("core_listings.Unit", on_delete=models.CASCADE, related_name="reviews")
    landlord = models.ForeignKey("core.Landlord", on_delete=models.CASCADE, related_name="reviews")

    complex_rating = models.PositiveSmallIntegerField(validators=STARS)
    unit_rating = models.PositiveSmallIntegerField(validators=STARS)
    landlord_rating = models.PositiveSmallIntegerField(validators=STARS)

    complex_feedback = models.TextField(blank=True)
    unit_feedback = models.TextField(blank=True)
    landlord_feedback = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.renter} on {self.complex} ({self.complex_rating}★)"


class ReviewPhoto(models.Model):
    review = models.ForeignKey(Review, on_delete=models.CASCADE, related_name="photos")
    image = models.ImageField(upload_to="review_photos/%Y/%m/")
    position = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["position", "id"]
