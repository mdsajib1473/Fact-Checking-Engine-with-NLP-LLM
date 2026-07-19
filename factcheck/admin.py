"""Django admin registrations for the fact-checking models.

The claims/verdicts/sources tables are the Rule 14 audit trail — every verdict
decision (claim, sources used, score, timestamp) must stay queryable and
explainable. Their admin views are therefore strictly read-only: the trail can
be inspected but never edited or deleted from the admin. Cache entries remain
deletable (purging cache is operational, not audit-relevant).
"""

from django.contrib import admin

from .models import CacheEntry, Claim, ClaimEmbedding, Source, Verdict


class ReadOnlyAdmin(admin.ModelAdmin):
    """Base admin that disables add/change/delete — audit rows are immutable."""

    def has_add_permission(self, request):
        """Audit rows are created by the pipeline only, never by hand."""
        return False

    def has_change_permission(self, request, obj=None):
        """The audit trail must never be editable (Rule 14)."""
        return False

    def has_delete_permission(self, request, obj=None):
        """The audit trail must never be deletable (Rule 14)."""
        return False


@admin.register(Claim)
class ClaimAdmin(ReadOnlyAdmin):
    """Read-only view of extracted claims (audit trail root)."""

    list_display = ("id", "extracted_claim", "source_input_type", "language", "created_at")
    list_filter = ("source_input_type", "language")
    search_fields = ("raw_text", "extracted_claim")
    date_hierarchy = "created_at"


@admin.register(Verdict)
class VerdictAdmin(ReadOnlyAdmin):
    """Read-only view of verdict decisions: label, score, timestamp (Rule 14)."""

    list_display = ("id", "claim", "label", "confidence_score", "created_at")
    list_filter = ("label",)
    search_fields = ("claim__extracted_claim", "explanation")
    date_hierarchy = "created_at"


@admin.register(Source)
class SourceAdmin(ReadOnlyAdmin):
    """Read-only view of the evidence behind each verdict (Rules 10/14)."""

    list_display = ("id", "source_name", "verdict", "relevance_score")
    list_filter = ("source_name",)
    search_fields = ("source_name", "source_url", "evidence_snippet")


@admin.register(CacheEntry)
class CacheEntryAdmin(admin.ModelAdmin):
    """Cache rows stay deletable — purging cache is operational, not audit data."""

    list_display = ("cache_key", "api_name", "expires_at", "is_expired")
    list_filter = ("api_name",)
    search_fields = ("cache_key",)
    readonly_fields = ("id",)

    def has_add_permission(self, request):
        """Cache rows are written by the pipeline, not created by hand."""
        return False


@admin.register(ClaimEmbedding)
class ClaimEmbeddingAdmin(ReadOnlyAdmin):
    """Read-only view of pgvector claim embeddings."""

    list_display = ("id", "claim")
