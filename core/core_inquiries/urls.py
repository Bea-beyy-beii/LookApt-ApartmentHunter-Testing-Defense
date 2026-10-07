from django.urls import path
from . import views

app_name = "core_inquiries"

urlpatterns = [
    # Renter: "Apply as Renter" / "Join Waitlist"
    path("inquiries/apply/<uuid:unit_pk>/", views.submit_application, name="submit_application"),

    # Renter: "Inquire with Landlord" pop-up
    path("inquiries/inquiry/", views.inquiry_thread, name="inquiry_thread"),
    path("inquiries/inquiry/send/", views.send_inquiry, name="send_inquiry"),

    # Both: Messages in the Inquiries tab
    path("inquiries/inbox/", views.inbox, name="inbox"),
    path("inquiries/conversations/<uuid:pk>/", views.conversation_detail, name="conversation_detail"),
    path("inquiries/conversations/<uuid:pk>/reply/", views.conversation_reply, name="conversation_reply"),
]