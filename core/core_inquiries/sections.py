"""The Inquiries tab of both dashboards (a DashboardSection, see core/sections.py)."""
from core.sections import DashboardSection

from .services import Inbox, NotificationFeed
from .workflow import RequestTabs


class InquiriesSection(DashboardSection):
    """Messages, Pending Requests / Waitlist / Archive and the bell, for landlords and renters."""

    def context(self):
        inbox = Inbox(self.user)
        tabs = RequestTabs(self.user, inbox.conversations)
        notifications = NotificationFeed.for_user(self.user, inbox.conversations, tabs.applications).items()

        return {
            "conversations": inbox.conversations,
            **tabs.context(),
            "unread_messages_count": inbox.unread_count,
            "notifications": notifications,
            "unread_notifications_count": sum(1 for n in notifications if not n["is_read"]),
            "new_notifications_count": sum(1 for n in notifications if n["is_new"]),
            "is_landlord_inbox": self.user.is_landlord,
        }
