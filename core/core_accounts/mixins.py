"""
Mixins for class-based views: who may open a page.

    class Dashboard(LandlordRequiredMixin, TemplateView): ...

RoleRequiredMixin is the parent; each subclass only sets `role`
(inheritance + a class attribute instead of repeating the check).
Logged out -> the login page; logged in with another role -> 403.
"""
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied

from core.core_preview.access import PreviewAccess


class RoleRequiredMixin(LoginRequiredMixin):
    role = None               # set by the subclasses below

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and request.user.role != self.role:
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)


class RenterRequiredMixin(RoleRequiredMixin):
    role = 'renter'


class LandlordRequiredMixin(RoleRequiredMixin):
    role = 'landlord'


class AdminRequiredMixin(RoleRequiredMixin):
    role = 'admin'


class RoleOrPreviewMixin:
    """Signed in with `role`, or a visitor trying that preview (core_preview); anyone else gets a 403.
    `self.viewer` is the signed-in user, or None in the preview."""
    role = None

    def dispatch(self, request, *args, **kwargs):
        user = request.user
        allowed = user.role == self.role if user.is_authenticated else PreviewAccess(request).is_previewing
        if not allowed:
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)

    @property
    def viewer(self):
        user = self.request.user
        return user if user.is_authenticated else None


class RenterOrPreviewMixin(RoleOrPreviewMixin):
    role = 'renter'
