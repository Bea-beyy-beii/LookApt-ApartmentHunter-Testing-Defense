# core_listings/services.py
from core.models import Landlord   
from .models import Complex
from .forms import ComplexForm


def get_listings_context(user):
    landlord = user.landlord
    properties = (
        Complex.objects
        .filter(landlord=landlord)
        .prefetch_related("pictures", "units")   # avoids one query per card
        .order_by("-created_at")
    )

    return {
        "properties": properties,
        "property_counts": {
            "all": properties.count(),
            "active": properties.filter(status=Complex.ComplexStatus.ACTIVE).count(),
            "unpublished": properties.filter(status=Complex.ComplexStatus.UNPUBLISHED).count(),
        },
        "form": ComplexForm(),
        "property": None,
        "current_step": 1,
    }