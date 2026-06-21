"""Evidence retrieval service (Phase 3).

Will query Wikipedia, Wikidata SPARQL, and the Google Fact Check Tools API,
each wrapped with the Postgres cache layer, using the fallback chain in
AGENT.md Rule 15. Not implemented in Phase 1.
"""
