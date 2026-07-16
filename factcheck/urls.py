"""URL routes for the fact-checking app."""

from django.urls import path

from .views import CheckUrlView, ExtractClaimsView, HomeView, ReportView

app_name = "factcheck"

urlpatterns = [
    path("", HomeView.as_view(), name="home"),
    path("report/", ReportView.as_view(), name="report"),
    path("api/v1/extract/", ExtractClaimsView.as_view(), name="extract"),
    path("api/v1/check-url/", CheckUrlView.as_view(), name="check_url"),
]
