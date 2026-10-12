# core_landlords/urls.py
from django.urls import path
from . import views

app_name = 'core_landlords'

urlpatterns = [
    path('dashboard/', views.dashboard, name='dashboard'),
    path('dashboard/receivables/', views.receivables_panel, name='receivables_panel'),
    path('dashboard/receivables/export/', views.export_receivables, name='export_receivables'),
    path('dashboard/performance/', views.performance_data, name='performance_data'),
]