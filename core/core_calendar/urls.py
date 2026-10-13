from django.urls import path
from . import views

app_name = "calendar"

urlpatterns = [
    path("", views.CalendarPageView.as_view(), name="calendar"),
    path("calendar/events/", views.EventsApiView.as_view(), name="events_api"),
    path("calendar/bulletin/", views.PostBulletinView.as_view(), name="post_bulletin"),
]
