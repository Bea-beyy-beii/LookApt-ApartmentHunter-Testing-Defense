# core_landlords/urls.py
from django.urls import path
from . import views

app_name = 'core_landlords'

urlpatterns = [
    path('dashboard/', views.DashboardView.as_view(), name='dashboard'),
    path('dashboard/receivables/', views.ReceivablesPanelView.as_view(), name='receivables_panel'),
    path('dashboard/receivables/export/', views.ExportReceivablesView.as_view(), name='export_receivables'),
    path('dashboard/performance/', views.PerformanceDataView.as_view(), name='performance_data'),
]
