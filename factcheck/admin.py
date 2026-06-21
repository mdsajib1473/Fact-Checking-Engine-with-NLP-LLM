"""Django admin registrations for the fact-checking models.

Lightweight read-oriented config so the audit trail (claims, verdicts, sources,
cache) is inspectable from the admin during development.
"""

from django.contrib import admin

from .models import CacheEntry, Claim, ClaimEmbedding, Source, Verdict


@admin.register(Claim)
class ClaimAdmin(admin.ModelAdmin):
    list_display = ("id", "source_input_type", "language", "created_at")
    list_filter = ("source_input_type", "language")
    search_fields = ("raw_text", "extracted_claim")
    readonly_fields = ("id", "created_at")


@admin.register(Verdict)
class VerdictAdmin(admin.ModelAdmin):
    list_display = ("id", "claim", "label", "confidence_score", "created_at")
    list_filter = ("label",)
    readonly_fields = ("id", "created_at")


@admin.register(Source)
class SourceAdmin(admin.ModelAdmin):
    list_display = ("id", "source_name", "verdict", "relevance_score")
    search_fields = ("source_name", "source_url")
    readonly_fields = ("id",)


@admin.register(CacheEntry)
class CacheEntryAdmin(admin.ModelAdmin):
    list_display = ("cache_key", "api_name", "expires_at", "is_expired")
    list_filter = ("api_name",)
    search_fields = ("cache_key",)
    readonly_fields = ("id",)


@admin.register(ClaimEmbedding)
class ClaimEmbeddingAdmin(admin.ModelAdmin):
    list_display = ("id", "claim")
    readonly_fields = ("id",)
