# core_listings/services.py

from django.db.models import Count, Q
from django.conf import settings
from .models import Complex
from .forms import ComplexForm

def renter_visible_complexes():
    """Complexes renters are allowed to see.

    TEMPORARY: while settings.LISTINGS_REQUIRE_APPROVAL is False, every
    active complex is shown right away (no admin approval yet).
    """
    complexes = Complex.objects.filter(status=Complex.ComplexStatus.ACTIVE)
    if getattr(settings, "LISTINGS_REQUIRE_APPROVAL", True):
        complexes = complexes.filter(approval_status=Complex.Approval.APPROVED)
    return complexes

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