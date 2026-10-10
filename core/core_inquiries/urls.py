from django.urls import path
from . import views

app_name = "core_inquiries"

urlpatterns = [
    # Renter: "Apply as Renter" / "Join Waitlist"
    path("inquiries/apply/<uuid:unit_pk>/", views.submit_application, name="submit_application"),

    # Pending Requests / Waitlist (landlord)
    path("inquiries/requests/<uuid:pk>/reject/", views.reject_request, name="reject_request"),
    path("inquiries/requests/<uuid:pk>/waitlist/", views.approve_waitlist, name="approve_waitlist"),
    path("inquiries/requests/<uuid:pk>/notify/", views.notify_applicant, name="notify_applicant"),
    path("inquiries/requests/<uuid:pk>/site-visit/", views.site_visit_decision, name="site_visit_decision"),

    # Pending Requests / Waitlist (renter)
    path("inquiries/requests/<uuid:pk>/cancel/", views.cancel_request, name="cancel_request"),
    path("inquiries/requests/<uuid:pk>/edit/", views.edit_request, name="edit_request"),

    # Renter: "Inquire with Landlord" pop-up
    path("inquiries/inquiry/", views.inquiry_thread, name="inquiry_thread"),
    path("inquiries/inquiry/send/", views.send_inquiry, name="send_inquiry"),

    # Landlord: "Message" button in Manage Rentals (tenants / applicants only)
    path("inquiries/renter-thread/", views.renter_thread, name="renter_thread"),
    path("inquiries/renter-thread/send/", views.send_to_renter, name="send_to_renter"),

    # Both: Messages in the Inquiries tab
    path("inquiries/inbox/", views.inbox, name="inbox"),
    path("inquiries/conversations/<uuid:pk>/", views.conversation_detail, name="conversation_detail"),
    path("inquiries/conversations/<uuid:pk>/reply/", views.conversation_reply, name="conversation_reply"),
]