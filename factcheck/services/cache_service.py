"""Postgres cache service (Phase 3).

Will provide read/write helpers with TTL over the :class:`CacheEntry` table so
repeated claims never re-burn external API quota (AGENT.md Rule 11): always
check the cache before any external call. Not implemented in Phase 1.
"""
