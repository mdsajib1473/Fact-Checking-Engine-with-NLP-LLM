from django.apps import AppConfig


class FactcheckConfig(AppConfig):
    """App configuration for the fact-checking app (models, views, services)."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "factcheck"
