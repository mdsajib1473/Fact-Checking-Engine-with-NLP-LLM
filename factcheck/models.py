"""Database models for the Fact-Checking Engine.

These mirror the schema locked in AGENT.md Section 5. Every table uses a UUID
primary key. No business logic lives here — models are pure schema plus
data-level helpers; pipeline logic belongs in ``factcheck/services/``.
"""

import uuid

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone
from pgvector.django import VectorField


class Claim(models.Model):
    """A single verifiable factual claim extracted from user input.

    Stores both the original raw input (text pasted or scraped from a URL) and
    the distilled claim string that downstream evidence retrieval works against.
    """

    class InputType(models.TextChoices):
        TEXT = "text", "Text"
        URL = "url", "URL"

    class Language(models.TextChoices):
        ENGLISH = "en", "English"
        BANGLA = "bn", "Bangla"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    raw_text = models.TextField()
    extracted_claim = models.TextField()
    source_input_type = models.CharField(max_length=4, choices=InputType.choices)
    source_url = models.URLField(max_length=2000, null=True, blank=True)
    language = models.CharField(max_length=2, choices=Language.choices)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "claims"
        ordering = ["-created_at"]

    def __str__(self):
        return f"Claim {self.id}: {self.extracted_claim[:60]}"


class Verdict(models.Model):
    """The assessment produced for a claim: a label plus a confidence score.

    A verdict is never valid without at least one attached :class:`Source`
    (AGENT.md Rule 9). The default/fallback label when no evidence is found is
    ``UNVERIFIABLE`` — never ``FALSE``.
    """

    class Label(models.TextChoices):
        SUPPORTED = "supported", "Supported"
        DISPUTED = "disputed", "Disputed"
        FALSE = "false", "False"
        UNVERIFIABLE = "unverifiable", "Unverifiable"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    claim = models.ForeignKey(Claim, on_delete=models.CASCADE, related_name="verdicts")
    label = models.CharField(max_length=12, choices=Label.choices)
    confidence_score = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(0), MaxValueValidator(10)]
    )
    explanation = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "verdicts"
        ordering = ["-created_at"]

    def __str__(self):
        return f"Verdict {self.label} ({self.confidence_score}/10) for {self.claim_id}"


class Source(models.Model):
    """A single piece of evidence backing a verdict.

    Holds the raw snippet and source link shown to the user so verdicts stay
    fully transparent — no black-box scoring (AGENT.md Rule 10).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    verdict = models.ForeignKey(Verdict, on_delete=models.CASCADE, related_name="sources")
    source_name = models.CharField(max_length=255)
    source_url = models.URLField(max_length=2000)
    evidence_snippet = models.TextField()
    relevance_score = models.FloatField()

    class Meta:
        db_table = "sources"
        ordering = ["-relevance_score"]

    def __str__(self):
        return f"{self.source_name} -> {self.verdict_id}"


class CacheEntry(models.Model):
    """A TTL-bound cache row for an external API response.

    Every external call (Groq, Google Fact Check, Wikipedia, Wikidata) is cached
    here to respect free-tier limits (AGENT.md Rule 11). Read/write and TTL
    logic live in ``services/cache_service.py``; this model is storage only.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    cache_key = models.CharField(max_length=255, unique=True, db_index=True)
    api_name = models.CharField(max_length=64)
    response_payload = models.JSONField()
    expires_at = models.DateTimeField()

    class Meta:
        db_table = "cache_entries"
        indexes = [models.Index(fields=["expires_at"])]

    def __str__(self):
        return f"{self.api_name}:{self.cache_key}"

    @property
    def is_expired(self):
        """True when this entry has passed its TTL and must be ignored/refreshed."""
        return timezone.now() >= self.expires_at


class ClaimEmbedding(models.Model):
    """A pgvector embedding of a claim, used for semantic similarity lookups.

    Requires the pgvector extension on the database (Neon: run
    ``CREATE EXTENSION vector;`` in the SQL editor before migrating). The vector
    dimension is left unbound here; it is fixed once the embedding model is
    chosen in a later phase.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    claim = models.OneToOneField(Claim, on_delete=models.CASCADE, related_name="embedding")
    embedding = VectorField(null=True, blank=True)

    class Meta:
        db_table = "claim_embeddings"

    def __str__(self):
        return f"Embedding for {self.claim_id}"
