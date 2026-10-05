# core_listings/services.py

from django.db.models import Count, Q

from .models import Complex
from .forms import ComplexForm


def get_listings_context(user):
    landlord = user.landlord

    properties = (
        Complex.objects
        .filter(landlord=landlord)
        .prefetch_related(
            "pictures",
            "units",
            "units__pictures",
            "units__videos",
        )
        .order_by("-created_at")
    )

    property_counts = Complex.objects.filter(
        landlord=landlord
    ).aggregate(
        all=Count("pk"),
        active=Count(
            "pk",
            filter=Q(
                status=Complex.ComplexStatus.ACTIVE
            )
        ),
        unpublished=Count(
            "pk",
            filter=Q(
                status=Complex.ComplexStatus.UNPUBLISHED
            )
        ),
    )

    return {
        "properties": properties,
        "property_counts": property_counts,
        "form": ComplexForm(),
        "property": None,
        "current_step": 1,
    }