from django.urls import path
from . import views

app_name = "calendar"

urlpatterns = [
    path("", views.calendar, name="calendar"),
    path("calendar/events/", views.events_api, name="events_api"),
    path("calendar/bulletin/", views.post_bulletin, name="post_bulletin"),
]