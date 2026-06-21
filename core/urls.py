"""Root URL configuration for the core project.

Routes: Django admin, the built-in auth views (login/logout/password flows),
and the factcheck app (home page at the site root).
"""

from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    # Standard Django auth: login, logout, password change/reset.
    path("accounts/", include("django.contrib.auth.urls")),
    path("", include("factcheck.urls")),
]
