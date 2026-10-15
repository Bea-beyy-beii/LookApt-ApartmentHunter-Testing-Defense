"""The Inquiries tab of both dashboards (a DashboardSection, see core/sections.py)."""
from core.core_reviews.services import LandlordReviews
from core.sections import DashboardSection

from .services import Inbox, NotificationFeed
from .workflow import RequestTabs


class InquiriesSection(DashboardSection):
    """Messages, Pending Requests / Waitlist / Archive (+ Reviews for landlords) and the bell."""

    def context(self):
        inbox = Inbox(self.user)
        tabs = RequestTabs(self.user, inbox.conversations)
        notifications = NotificationFeed.for_user(self.user, inbox.conversations, tabs.applications).items()

        # Landlords only: Reviews, the 5th sub-tab (renters write theirs in Rental History)
        reviews = LandlordReviews(self.user.landlord, chat=tabs.chat_with).context() if self.user.is_landlord else {}

        return {
            "conversations": inbox.conversations,
            **tabs.context(),
            **reviews,
            "unread_messages_count": inbox.unread_count,
            "notifications": notifications,
            "unread_notifications_count": sum(1 for n in notifications if not n["is_read"]),
            "new_notifications_count": sum(1 for n in notifications if n["is_new"]),
            "is_landlord_inbox": self.user.is_landlord,
        }
