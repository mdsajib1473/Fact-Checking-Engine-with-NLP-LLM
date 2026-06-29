"""Postgres cache service (Phase 3).

Read/write helpers with TTL over the :class:`CacheEntry` table so repeated
claims never re-burn external API quota (AGENT.md Rule 11): always check the
cache before any external call.

Cache keys are deterministic SHA-256 hashes of the *normalized* query string
(lowercased, whitespace-collapsed), so the same logical query maps to the same
row regardless of incidental casing/spacing. Expired entries are ignored on
read; no separate sweep job is needed for this phase — stale rows are simply
skipped (and overwritten on the next write).
"""

import hashlib
import logging
import re

from django.utils import timezone

from ..models import CacheEntry

logger = logging.getLogger(__name__)

_WS_RE = re.compile(r"\s+")


def make_cache_key(api_name: str, query: str) -> str:
    """Return a deterministic SHA-256 cache key for ``query`` under ``api_name``.

    The query is normalized (trimmed, lowercased, internal whitespace collapsed)
    before hashing so trivially different spellings of the same query collide on
    purpose. ``api_name`` is folded into the digest so the same query against
    different sources never shares a cache row.
    """
    normalized = _WS_RE.sub(" ", (query or "").strip().lower())
    digest = hashlib.sha256(f"{api_name}:{normalized}".encode("utf-8")).hexdigest()
    return digest


def get_cached_response(api_name: str, cache_key: str) -> dict | None:
    """Return the cached payload for ``cache_key`` if present and unexpired.

    Looks up the :class:`CacheEntry` row by its unique key. Returns the stored
    ``response_payload`` dict on a fresh hit, or ``None`` on a miss or when the
    entry has passed its ``expires_at`` TTL (expired rows are ignored on read,
    AGENT.md Rule 11). ``api_name`` is accepted for symmetry/logging; the key is
    already source-scoped by :func:`make_cache_key`.
    """
    try:
        entry = CacheEntry.objects.get(cache_key=cache_key)
    except CacheEntry.DoesNotExist:
        return None

    if entry.is_expired:
        logger.debug("cache expired: %s:%s", api_name, cache_key)
        return None

    return entry.response_payload


def set_cached_response(
    api_name: str, cache_key: str, payload: dict, ttl_seconds: int
) -> None:
    """Write ``payload`` to the cache under ``cache_key`` with a TTL.

    Stores (or overwrites) the :class:`CacheEntry` row, stamping ``expires_at``
    at ``ttl_seconds`` into the future. ``ttl_seconds`` is supplied by the caller
    from Django settings (never hardcoded — AGENT.md Rule 7). Uses
    ``update_or_create`` so a refreshed response replaces the stale one in place.
    """
    expires_at = timezone.now() + timezone.timedelta(seconds=ttl_seconds)
    CacheEntry.objects.update_or_create(
        cache_key=cache_key,
        defaults={
            "api_name": api_name,
            "response_payload": payload,
            "expires_at": expires_at,
        },
    )
