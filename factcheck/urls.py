"""URL routes for the fact-checking app."""

from django.urls import path

from .views import HomeView

app_name = "factcheck"

urlpatterns = [
    path("", HomeView.as_view(), name="home"),
]
