# core_reviews/services.py
# Writing a review (Rental History → "Leave a Review") and the Reviews tab of
# the complex page. The star averages are on Review.objects (models.py).
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from PIL import Image

from .models import Review, ReviewPhoto


class ReviewSubmission:
    """One renter's "Leave a Review" / "Edit Review" for one tenancy.

        ReviewSubmission(user, tenancy, request.POST, photos=..., remove_photo_ids=...).save()
    """

    MAX_PHOTOS = 5
    MAX_PHOTO_MB = 5
    FEEDBACK_MAX = 500
    PHOTO_TYPES = {"image/jpeg": "JPEG", "image/png": "PNG"}

    def __init__(self, user, tenancy, data, photos=(), remove_photo_ids=()):
        self.user = user
        self.tenancy = tenancy
        self.data = data
        self.photos = list(photos)
        self.remove_photo_ids = list(remove_photo_ids)

    @classmethod
    def form_context(cls):
        """What the "Write a Review" pop-up needs (Rental History)."""
        return {
            "review_parts": [
                {"key": key, "label": label, "hint": hint, "placeholder": placeholder, "icon": icon}
                for key, label, hint, placeholder, icon in Review.PARTS
            ],
            "review_max_photos": cls.MAX_PHOTOS,
            "review_max_mb": cls.MAX_PHOTO_MB,
            "review_feedback_max": cls.FEEDBACK_MAX,
        }

    # ---------- checks ----------

    def _rating(self, part):
        try:
            value = int(self.data.get(f"{part}_rating") or 0)
        except (TypeError, ValueError):
            value = 0
        if not 1 <= value <= 5:
            raise ValidationError({f"{part}_rating": "Pick 1 to 5 stars."})
        return value

    def _feedback(self, part):
        text = (self.data.get(f"{part}_feedback") or "").strip()
        if len(text) > self.FEEDBACK_MAX:
            raise ValidationError({f"{part}_feedback": f"Keep it under {self.FEEDBACK_MAX} characters."})
        return text

    def _clean_photos(self, keep_count):
        if keep_count + len(self.photos) > self.MAX_PHOTOS:
            raise ValidationError({"photos": f"You can add up to {self.MAX_PHOTOS} photos."})
        for photo in self.photos:
            if photo.size > self.MAX_PHOTO_MB * 1024 * 1024:
                raise ValidationError({"photos": f"{photo.name} is larger than {self.MAX_PHOTO_MB} MB."})
            try:
                with Image.open(photo) as image:
                    kind = image.format
            except Exception:
                kind = None
            finally:
                photo.seek(0)
            if kind not in self.PHOTO_TYPES.values():
                raise ValidationError({"photos": f"{photo.name} isn't a PNG or JPG photo."})

    # ---------- save ----------

    @transaction.atomic
    def save(self):
        """Create the renter's review of this rental, or update it. Raises ValidationError({field: message})."""
        tenancy = self.tenancy
        if not tenancy.can_be_reviewed_by(self.user):
            raise PermissionDenied

        values = {}
        for part, *_ in Review.PARTS:
            values[f"{part}_rating"] = self._rating(part)
            values[f"{part}_feedback"] = self._feedback(part)

        review = Review.objects.filter(tenancy=tenancy).first()
        removing = list(review.photos.filter(pk__in=self.remove_photo_ids)) if review else []
        self._clean_photos((review.photos.count() if review else 0) - len(removing))

        unit = tenancy.unit
        if review is None:
            review = Review(tenancy=tenancy, renter=tenancy.renter, unit=unit, complex=unit.complex,
                            landlord=unit.complex.landlord)
        for field, value in values.items():
            setattr(review, field, value)
        review.save()

        for photo in removing:
            photo.image.delete(save=False)
            photo.delete()
        start = review.photos.count()
        for index, photo in enumerate(self.photos):
            ReviewPhoto.objects.create(review=review, image=photo, position=start + index)
        return review


class ReviewList:
    """A list of reviews with its averages and a 5→1 star breakdown of one part.
    Subclasses pick which reviews (queryset()) and which part the breakdown counts."""

    BREAKDOWN_PART = "complex"

    def __init__(self):
        self.reviews = list(
            self.queryset()
            .select_related("renter__user", "unit__complex", "tenancy")
            .prefetch_related("photos")
        )

    def queryset(self):
        raise NotImplementedError

    @property
    def count(self):
        return len(self.reviews)

    def _average(self, field):
        return round(sum(getattr(r, field) for r in self.reviews) / self.count, 1) if self.count else 0

    def _breakdown(self):
        field = f"{self.BREAKDOWN_PART}_rating"
        rows = []
        for stars in range(5, 0, -1):
            n = sum(1 for r in self.reviews if getattr(r, field) == stars)
            rows.append({"stars": stars, "count": n, "percent": round(n * 100 / self.count) if self.count else 0})
        return rows

    def summary(self):
        return {
            "count": self.count,
            "complex": self._average("complex_rating"),
            "unit": self._average("unit_rating"),
            "landlord": self._average("landlord_rating"),
            "breakdown": self._breakdown(),
        }

    def context(self):
        return {"reviews": self.reviews, "review_summary": self.summary()}


class ComplexReviews(ReviewList):
    """The complex page's Reviews tab (renters): every review of one complex."""

    def __init__(self, complex_obj):
        self.complex = complex_obj
        super().__init__()

    def queryset(self):
        return Review.objects.for_complex(self.complex)


class LandlordReviews(ReviewList):
    """Inquiries > Reviews (landlords): every review of this landlord's rentals, newest first.
    The breakdown counts the Landlord stars; `chat` (optional) adds a Message link per review."""

    BREAKDOWN_PART = "landlord"

    def __init__(self, landlord, chat=None):
        self.landlord = landlord
        super().__init__()
        if chat:
            for review in self.reviews:
                review.chat = chat(review)

    def queryset(self):
        return Review.objects.for_landlord(self.landlord).order_by("-created_at")

    def complexes(self):
        """The complexes that have reviews, for the filter."""
        seen = {}
        for review in self.reviews:
            seen.setdefault(review.complex_id, review.unit.complex.complex_name)
        return sorted(({"id": str(pk), "name": name} for pk, name in seen.items()), key=lambda c: c["name"].lower())

    def context(self):
        return {**super().context(), "review_complexes": self.complexes()}
