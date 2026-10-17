"""
One class per role, found without `if role == ...` (polymorphism).

The parent of a family mixes in RoleBased; each child sets ROLE:

    class Calendar(RoleBased, ABC): ...
    class LandlordCalendar(Calendar):  ROLE = "landlord"
    class RenterCalendar(Calendar):    ROLE = "renter"

    Calendar.class_for(user)       -> LandlordCalendar for a landlord
"""
from django.core.exceptions import PermissionDenied


class RoleBased:
    ROLE = None               # "renter" / "landlord", set by each child class

    @classmethod
    def for_role(cls, role):
        """The child class for this role, or None (e.g. admins)."""
        return next((child for child in cls._children() if child.ROLE == role), None)

    @classmethod
    def class_for(cls, user):
        """The child class for this user's role; a 403 for roles that have none."""
        child = cls.for_role(user.role)
        if child is None:
            raise PermissionDenied(f"{cls.__name__} has nothing for {user.role} accounts.")
        return child

    @classmethod
    def _children(cls):
        for child in cls.__subclasses__():
            yield child
            yield from child._children()
