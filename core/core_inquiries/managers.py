# core_inquiries/managers.py
# The queries the Inquiries pages ask again and again, as QuerySet methods:
#   Application.objects.for_landlord(user).open()
#   Conversation.objects.for_user(user).with_inbox_data(user)
from datetime import timedelta

from django.db import models
from django.db.models import Count, OuterRef, Q, Subquery
from django.utils import timezone


class ApplicationQuerySet(models.QuerySet):

    def with_parties(self):
        """Load the renter and the landlord along with each application."""
        return self.select_related("renter__user", "unit__complex__landlord__user")

    def open(self):
        return self.filter(status__in=self.model.OPEN_STATUSES)

    def for_landlord(self, user):
        """Applications to this landlord's units."""
        return self.filter(unit__complex__landlord__user=user)

    def for_renter(self, user):
        """This renter's own applications."""
        return self.filter(renter__user=user)

    def for_user(self, user):
        return self.for_landlord(user) if user.is_landlord else self.for_renter(user)

    def visible_to(self, user):
        """What the Inquiries tab shows: open requests + ones decided in the last ARCHIVE_DAYS."""
        cutoff = timezone.now() - timedelta(days=self.model.ARCHIVE_DAYS)
        return (
            self.with_parties()
            .for_user(user)
            .filter(Q(status__in=self.model.OPEN_STATUSES) | Q(decided_at__gte=cutoff))
            .prefetch_related("unit__pictures", "unit__complex__pictures")
        )

    def confirmed_visits(self, start, end):
        """Site visits the landlord confirmed between two dates (pending ones stay in Pending Requests)."""
        return (
            self.filter(site_visit_date__range=(start, end), site_visit_status=self.model.SiteVisit.CONFIRMED)
            .exclude(status__in=self.model.ARCHIVED_STATUSES)
            .select_related("unit__complex", "renter__user")
        )


class ConversationQuerySet(models.QuerySet):

    def for_user(self, user):
        """Threads this user takes part in (as renter or as landlord)."""
        return self.filter(Q(renter__user=user) | Q(landlord__user=user))

    def with_inbox_data(self, user):
        """Unread count + the latest message's fields, read in the same query."""
        from .models import Message

        latest = Message.objects.filter(conversation=OuterRef("pk")).order_by("-created_at", "-pk")
        return (
            self.select_related("renter__user", "landlord__user", "complex", "unit")
            .annotate(
                unread_count=Count("messages", filter=Q(messages__read_at__isnull=True) & ~Q(messages__sender=user)),
                latest_body=Subquery(latest.values("body")[:1]),
                latest_kind=Subquery(latest.values("kind")[:1]),
                latest_attachment_name=Subquery(latest.values("attachment_name")[:1]),
                latest_sender_id=Subquery(latest.values("sender_id")[:1]),
            )
            .order_by("-last_message_at")   # newest conversation on top
        )
