# core_reviews/models.py
# - Review: a renter's ratings (1-5 stars) of the complex, the unit and the
#   landlord, with optional feedback. One per tenancy (Rental History).
# - ReviewPhoto: up to 5 photos attached to a review.
import json
import uuid

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Avg, Count

STARS = [MinValueValidator(1), MaxValueValidator(5)]


class ReviewQuerySet(models.QuerySet):
    """The star averages on the listing pages:

        Review.objects.for_complex(c).summary("complex") -> {"avg": 4.3, "count": 12}
    """

    def for_complex(self, complex_obj):
        return self.filter(complex=complex_obj)

    def for_unit(self, unit):
        return self.filter(unit=unit)

    def for_landlord(self, landlord):
        return self.filter(landlord=landlord)

    def summary(self, part):
        """Average stars of one part ("complex", "unit" or "landlord") + how many reviews."""
        result = self.aggregate(avg=Avg(f"{part}_rating"), count=Count("pk"))
        return {"avg": round(result["avg"] or 0, 1), "count": result["count"]}

    def unit_summaries(self, units):
        """{unit pk: {"avg", "count"}} for the Units tab, in one query."""
        rows = (self.filter(unit__in=units).values("unit")
                .annotate(avg=Avg("unit_rating"), count=Count("pk")))
        return {row["unit"]: {"avg": round(row["avg"], 1), "count": row["count"]} for row in rows}


class Review(models.Model):
    # The three parts of a review: (form field prefix, label, hint, placeholder, icon)
    PARTS = [
        ("complex", "Complex", "Rate the overall property and facilities.",
         "Share your experience about the complex…", "units"),
        ("unit", "Unit", "Rate the specific unit you rented.",
         "Share your experience about the unit…", "unit_type"),
        ("landlord", "Landlord", "Share your experience with the landlord.",
         "Share your experience about the landlord…", "person"),
    ]

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

    objects = ReviewQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.renter} on {self.complex} ({self.complex_rating}★)"

    # ---------- shown on the complex page's Reviews tab ----------

    @property
    def reviewer_name(self):
        """"Rina T." — first name and last initial only."""
        user = self.renter.user
        last = (user.last_name or "").strip()
        first = (user.first_name or "").strip()
        return f"{first[0]}. {last[0]}." if last else user.first_name or "LookApt renter"

    @property
    def reviewer_initials(self):
        return self.renter.user.initials

    @property
    def reviewer_avatar(self):
        return self.renter.user.avatar_url

    @property
    def parts(self):
        return [
            {"label": label, "rating": getattr(self, f"{part}_rating"), "feedback": getattr(self, f"{part}_feedback")}
            for part, label, *_ in self.PARTS
        ]

    def to_json(self):
        """The pop-up's starting values when the renter edits their review."""
        data = {
            f"{part}_{kind}": getattr(self, f"{part}_{kind}")
            for part, *_ in self.PARTS for kind in ("rating", "feedback")
        }
        data["photos"] = [{"id": photo.pk, "url": photo.image.url} for photo in self.photos.all()]
        return json.dumps(data)


class ReviewPhoto(models.Model):
    review = models.ForeignKey(Review, on_delete=models.CASCADE, related_name="photos")
    image = models.ImageField(upload_to="review_photos/%Y/%m/")
    position = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["position", "id"]
