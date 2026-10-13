"""
Dashboard sections (abstraction + polymorphism).

A dashboard page (landlord or renter) is built from several sections, one per
app: listings, inquiries, rentals, reports ... Every section is a subclass of
DashboardSection and answers the same question, context(): "what does the
template need from me?". The dashboard view only loops over its list of
section classes; it doesn't need to know what each one does.

    class ListingsSection(DashboardSection):
        def context(self):
            return {"properties": ...}

`shared` holds what the earlier sections already added, so a later section
(e.g. the landlord Home tab) can reuse it instead of loading it again.
"""
from abc import ABC, abstractmethod


class DashboardSection(ABC):

    def __init__(self, user, request=None, shared=None):
        self.user = user
        self.request = request
        self.shared = shared if shared is not None else {}

    @abstractmethod
    def context(self):
        """The template variables this section adds (a dict)."""


class SectionedDashboardMixin:
    """For a TemplateView: `sections` is a list of DashboardSection subclasses,
    added to the template context in order."""

    sections = ()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["active_tab"] = self.request.GET.get("tab", "home")
        for section_class in self.sections:
            context.update(section_class(self.request.user, self.request, context).context())
        return context
