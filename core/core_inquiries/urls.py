from django.urls import path
from . import views

app_name = "core_inquiries"

urlpatterns = [
    # Renter: "Apply as Renter" / "Join Waitlist"
    path("inquiries/apply/<uuid:unit_pk>/", views.SubmitApplicationView.as_view(), name="submit_application"),

    # Pending Requests / Waitlist (landlord)
    path("inquiries/requests/<uuid:pk>/reject/", views.RejectRequestView.as_view(), name="reject_request"),
    path("inquiries/requests/<uuid:pk>/waitlist/", views.ApproveWaitlistView.as_view(), name="approve_waitlist"),
    path("inquiries/requests/<uuid:pk>/notify/", views.NotifyApplicantView.as_view(), name="notify_applicant"),
    path("inquiries/requests/<uuid:pk>/site-visit/", views.SiteVisitDecisionView.as_view(), name="site_visit_decision"),

    # Pending Requests / Waitlist (renter)
    path("inquiries/requests/<uuid:pk>/cancel/", views.CancelRequestView.as_view(), name="cancel_request"),
    path("inquiries/requests/<uuid:pk>/edit/", views.EditRequestView.as_view(), name="edit_request"),

    # Renter: "Inquire with Landlord" pop-up
    path("inquiries/inquiry/", views.InquiryThreadView.as_view(), name="inquiry_thread"),
    path("inquiries/inquiry/send/", views.SendInquiryView.as_view(), name="send_inquiry"),

    # Landlord: "Message" button in Manage Rentals (tenants / applicants only)
    path("inquiries/renter-thread/", views.RenterThreadView.as_view(), name="renter_thread"),
    path("inquiries/renter-thread/send/", views.SendToRenterView.as_view(), name="send_to_renter"),

    # Both: Messages in the Inquiries tab
    path("inquiries/inbox/", views.InboxView.as_view(), name="inbox"),
    path("inquiries/conversations/<uuid:pk>/", views.ConversationDetailView.as_view(), name="conversation_detail"),
    path("inquiries/conversations/<uuid:pk>/reply/", views.ConversationReplyView.as_view(), name="conversation_reply"),
]
