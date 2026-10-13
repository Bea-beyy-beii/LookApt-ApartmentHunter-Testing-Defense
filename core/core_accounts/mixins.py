"""
Mixins for class-based views: who may open a page.

    class Dashboard(LandlordRequiredMixin, TemplateView): ...

RoleRequiredMixin is the parent; each subclass only sets `role`
(inheritance + a class attribute instead of repeating the check).
Logged out -> the login page; logged in with another role -> 403.
"""
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied


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
