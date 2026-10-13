# core_renters/urls.py
from django.urls import path
from . import views

app_name = 'core_renters'   

urlpatterns = [
    path('dashboard/', views.DashboardView.as_view(), name='dashboard'),
    path('listings/search/', views.SearchListingsView.as_view(), name='search_listings'),
]