# core_reviews/views.py
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_POST

from core.core_accounts.decorators import role_required
from core.core_rentals.models import Tenancy

from . import services


@role_required("renter")
@require_POST
def save_review(request, tenancy_pk):
    """Rental History's "Leave a Review" pop-up (reviews.js). Multipart: ratings, feedback, photos."""
    tenancy = get_object_or_404(
        Tenancy.objects.select_related("unit__complex__landlord", "renter"),
        pk=tenancy_pk, renter__user=request.user,
    )
    created = not hasattr(tenancy, "review")
    try:
        services.save_review(
            request.user, tenancy, request.POST,
            photos=request.FILES.getlist("photos"),
            remove_photo_ids=request.POST.getlist("remove_photos"),
        )
    except ValidationError as error:
        messages = {field: " ".join(errors) for field, errors in error.message_dict.items()}
        return JsonResponse({"errors": messages}, status=400)

    name = tenancy.unit.complex.complex_name
    return JsonResponse({
        "message": f"Thanks! Your review of {name} was posted." if created else f"Your review of {name} was updated.",
    }, status=201 if created else 200)
