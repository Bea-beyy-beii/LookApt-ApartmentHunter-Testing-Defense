# core_maps/urls.py
from django.urls import path
from . import views

app_name = "core_maps"

urlpatterns = [
    path("frame/", views.MapFrameView.as_view(), name="frame"),
    path("api/landmarks/", views.LandmarksApiView.as_view(), name="landmarks_api"),
    path("api/complexes/", views.ComplexesApiView.as_view(), name="complexes_api"),
    path("api/search/", views.SearchApiView.as_view(), name="search_api"),
    path("api/reverse/", views.ReverseApiView.as_view(), name="reverse_api"),
]
