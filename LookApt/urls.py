"""
URL configuration for LookApt project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include

from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('lookapt-manage/', admin.site.urls),
    path("", include('core.core_accounts.urls')),
    path("renters/", include("core.core_renters.urls")),
    path("landlords/", include("core.core_landlords.urls")),
    path("", include("core.core_inquiries.urls")),
    path("rentals/", include("core.core_rentals.urls")),
    path("", include("core.core_listings.urls")),
    path("", include("core.core_calendar.urls")),
    path("", include("core.core_reports.urls")),
    path("maps/", include("core.core_maps.urls")),
    path("verification/", include("core.core_verification.urls")),
]

urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)