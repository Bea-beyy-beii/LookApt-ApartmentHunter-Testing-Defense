# core_reviews/services.py
# Writing a review (Rental History → "Leave a Review") and the star averages /
# review list shown on the listing pages.
import json

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Avg, Count
from PIL import Image

from core.core_inquiries.services import today

from .models import Review, ReviewPhoto

MAX_PHOTOS = 5
MAX_PHOTO_MB = 5
FEEDBACK_MAX = 500
PHOTO_TYPES = {"image/jpeg": "JPEG", "image/png": "PNG"}

# The three parts of a review: (form field prefix, label, hint, placeholder, icon)
PARTS = [
    ("complex", "Complex", "Rate the overall property and facilities.",
     "Share your experience about the complex…", "units"),
    ("unit", "Unit", "Rate the specific unit you rented.",
     "Share your experience about the unit…", "unit_type"),
    ("landlord", "Landlord", "Share your experience with the landlord.",
     "Share your experience about the landlord…", "person"),
]


def review_form_context():
    """What the "Write a Review" pop-up needs (Rental History)."""
    return {
        "review_parts": [
            {"key": key, "label": label, "hint": hint, "placeholder": placeholder, "icon": icon}
            for key, label, hint, placeholder, icon in PARTS
        ],
        "review_max_photos": MAX_PHOTOS,
        "review_max_mb": MAX_PHOTO_MB,
        "review_feedback_max": FEEDBACK_MAX,
    }


# =========================================================
# WHO CAN REVIEW
# =========================================================

def can_review(user, tenancy):
    """The tenancy's own renter, once the rental has started (current or past)."""
    renter = tenancy.renter
    return bool(renter and renter.user_id == user.pk and tenancy.start_date <= today())


# =========================================================
# SAVE
# =========================================================

def _rating(data, part):
    try:
        value = int(data.get(f"{part}_rating") or 0)
    except (TypeError, ValueError):
        value = 0
    if not 1 <= value <= 5:
        raise ValidationError({f"{part}_rating": "Pick 1 to 5 stars."})
    return value


def _feedback(data, part):
    text = (data.get(f"{part}_feedback") or "").strip()
    if len(text) > FEEDBACK_MAX:
        raise ValidationError({f"{part}_feedback": f"Keep it under {FEEDBACK_MAX} characters."})
    return text


def _clean_photos(photos, keep_count):
    if keep_count + len(photos) > MAX_PHOTOS:
        raise ValidationError({"photos": f"You can add up to {MAX_PHOTOS} photos."})
    for photo in photos:
        if photo.size > MAX_PHOTO_MB * 1024 * 1024:
            raise ValidationError({"photos": f"{photo.name} is larger than {MAX_PHOTO_MB} MB."})
        try:
            with Image.open(photo) as image:
                kind = image.format
        except Exception:
            kind = None
        finally:
            photo.seek(0)
        if kind not in PHOTO_TYPES.values():
            raise ValidationError({"photos": f"{photo.name} isn't a PNG or JPG photo."})
    return photos


@transaction.atomic
def save_review(user, tenancy, data, photos=(), remove_photo_ids=()):
    """Create the renter's review of this rental, or update it. Raises ValidationError({field: message})."""
    if not can_review(user, tenancy):
        raise PermissionDenied

    values = {}
    for part, *_ in PARTS:
        values[f"{part}_rating"] = _rating(data, part)
        values[f"{part}_feedback"] = _feedback(data, part)

    review = Review.objects.filter(tenancy=tenancy).first()
    removing = list(review.photos.filter(pk__in=list(remove_photo_ids))) if review else []
    keep_count = (review.photos.count() if review else 0) - len(removing)
    photos = _clean_photos(list(photos), keep_count)

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
    for index, photo in enumerate(photos):
        ReviewPhoto.objects.create(review=review, image=photo, position=start + index)
    return review


def review_json(review):
    """The pop-up's starting values when the renter edits their review."""
    if review is None:
        return ""
    data = {f"{part}_{kind}": getattr(review, f"{part}_{kind}") for part, *_ in PARTS for kind in ("rating", "feedback")}
    data["photos"] = [{"id": photo.pk, "url": photo.image.url} for photo in review.photos.all()]
    return json.dumps(data)


# =========================================================
# STARS ON THE LISTING PAGES
# =========================================================

def _summary(queryset, field):
    result = queryset.aggregate(avg=Avg(field), count=Count("pk"))
    return {"avg": round(result["avg"] or 0, 1), "count": result["count"]}


def complex_rating(complex_obj):
    return _summary(Review.objects.filter(complex=complex_obj), "complex_rating")


def landlord_rating(landlord):
    return _summary(Review.objects.filter(landlord=landlord), "landlord_rating")


def unit_rating(unit):
    return _summary(Review.objects.filter(unit=unit), "unit_rating")


def unit_ratings(units):
    """{unit pk: {"avg", "count"}} for the Units tab, in one query."""
    rows = (Review.objects.filter(unit__in=units).values("unit")
            .annotate(avg=Avg("unit_rating"), count=Count("pk")))
    return {row["unit"]: {"avg": round(row["avg"], 1), "count": row["count"]} for row in rows}


def _reviewer_name(user):
    """"Rina T." — first name and last initial only."""
    last = (user.last_name or "").strip()
    return f"{user.first_name} {last[0]}." if last else user.first_name or "LookApt renter"


def complex_reviews_context(complex_obj):
    """The complex page's Reviews tab: averages, the 5→1 star breakdown, every review."""
    reviews = list(
        Review.objects.filter(complex=complex_obj)
        .select_related("renter__user", "unit", "tenancy")
        .prefetch_related("photos")
    )
    count = len(reviews)
    average = lambda field: round(sum(getattr(r, field) for r in reviews) / count, 1) if count else 0

    breakdown = []
    for stars in range(5, 0, -1):
        n = sum(1 for r in reviews if r.complex_rating == stars)
        breakdown.append({"stars": stars, "count": n, "percent": round(n * 100 / count) if count else 0})

    for review in reviews:
        user = review.renter.user
        review.reviewer_name = _reviewer_name(user)
        review.reviewer_initials = user.initials
        review.reviewer_avatar = user.avatar_url
        review.parts = [
            {"label": label, "rating": getattr(review, f"{part}_rating"), "feedback": getattr(review, f"{part}_feedback")}
            for part, label, *_ in PARTS
        ]

    return {
        "reviews": reviews,
        "review_summary": {
            "count": count,
            "complex": average("complex_rating"),
            "unit": average("unit_rating"),
            "landlord": average("landlord_rating"),
            "breakdown": breakdown,
        },
    }
