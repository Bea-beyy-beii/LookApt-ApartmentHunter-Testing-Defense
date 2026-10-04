# core_maps/urls.py
from django.urls import path
from . import views

app_name = "core_maps"

urlpatterns = [
    path("frame/", views.map_frame, name="frame"),
    path("api/landmarks/", views.landmarks_api, name="landmarks_api"),
    path("api/complexes/", views.complexes_api, name="complexes_api"),
    path("api/search/", views.search_api, name="search_api"),
    path("api/reverse/", views.reverse_api, name="reverse_api"),
]
