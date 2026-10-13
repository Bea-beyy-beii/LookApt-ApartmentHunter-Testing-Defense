# core_renters/urls.py
from django.urls import path
from . import views

app_name = 'core_renters'   

urlpatterns = [
    path('dashboard/', views.DashboardView.as_view(), name='dashboard'),
    path('listings/search/', views.search_listings, name='search_listings'),
]