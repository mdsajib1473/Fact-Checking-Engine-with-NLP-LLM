"""Tests for the Postgres cache service (Phase 3).

Covers the TTL contract (AGENT.md Rule 11): a miss returns ``None``, a fresh hit
returns the stored payload, an expired entry is ignored on read, and cache keys
are a deterministic hash of the normalized query.
"""

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from factcheck.models import CacheEntry
from factcheck.services import cache_service


class CacheServiceTests(TestCase):
    """Read/write/TTL/key behaviour of ``cache_service``."""

    def test_miss_returns_none(self):
        """A key with no stored row returns ``None``."""
        key = cache_service.make_cache_key("wikipedia", "nothing stored here")
        self.assertIsNone(cache_service.get_cached_response("wikipedia", key))

    def test_hit_returns_payload(self):
        """A freshly written entry reads back its exact payload."""
        key = cache_service.make_cache_key("wikipedia", "eiffel tower")
        payload = {"title": "Eiffel Tower", "extract": "A tower in Paris."}
        cache_service.set_cached_response("wikipedia", key, payload, 3600)
        self.assertEqual(cache_service.get_cached_response("wikipedia", key), payload)

    def test_expired_entry_returns_none(self):
        """An entry past its ``expires_at`` is ignored on read."""
        key = cache_service.make_cache_key("google_factcheck", "old claim")
        cache_service.set_cached_response("google_factcheck", key, {"a": 1}, 3600)
        CacheEntry.objects.filter(cache_key=key).update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )
        self.assertIsNone(cache_service.get_cached_response("google_factcheck", key))

    def test_key_is_deterministic_and_normalized(self):
        """Same normalized query → same key; casing/whitespace don't matter."""
        k1 = cache_service.make_cache_key("wikipedia", "The Eiffel Tower")
        k2 = cache_service.make_cache_key("wikipedia", "  the   EIFFEL tower  ")
        self.assertEqual(k1, k2)

    def test_key_is_source_scoped(self):
        """The same query against different sources yields different keys."""
        same_query = "The Eiffel Tower"
        self.assertNotEqual(
            cache_service.make_cache_key("wikipedia", same_query),
            cache_service.make_cache_key("wikidata", same_query),
        )

    def test_set_overwrites_existing_entry(self):
        """Re-writing a key replaces the stale payload in place (no duplicate row)."""
        key = cache_service.make_cache_key("wikidata", "entity")
        cache_service.set_cached_response("wikidata", key, {"v": 1}, 3600)
        cache_service.set_cached_response("wikidata", key, {"v": 2}, 3600)
        self.assertEqual(cache_service.get_cached_response("wikidata", key), {"v": 2})
        self.assertEqual(CacheEntry.objects.filter(cache_key=key).count(), 1)
