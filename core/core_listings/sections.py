"""The landlord's My Listings tab (a DashboardSection, see core/sections.py)."""
from django.db.models import Count, Q

from core.sections import DashboardSection

from .forms import ComplexForm
from .models import Complex


class ListingsSection(DashboardSection):
    """The landlord's complexes (with their units and media) and the counts on the filter tabs."""

    @property
    def landlord(self):
        return self.user.landlord

    def context(self):
        return {
            "properties": self._properties(),
            "property_counts": self._property_counts(),
            # the Add Property wizard opens from this tab
            "form": ComplexForm(),
            "property": None,
            "current_step": 1,
        }

    def _properties(self):
        return (
            Complex.objects
            .filter(landlord=self.landlord)
            .prefetch_related("pictures", "units", "units__pictures", "units__videos")
            .order_by("-created_at")
        )

    def _property_counts(self):
        return Complex.objects.filter(landlord=self.landlord).aggregate(
            all=Count("pk"),
            active=Count("pk", filter=Q(status=Complex.ComplexStatus.ACTIVE)),
            unpublished=Count("pk", filter=Q(status=Complex.ComplexStatus.UNPUBLISHED)),
        )
