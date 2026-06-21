"""Service layer for the fact-checking pipeline.

Business logic lives here, split into independently testable stages
(AGENT.md Rule 13): claim extraction, evidence retrieval, verdict scoring,
caching, language detection, and URL scraping. Stages are stubs in Phase 1.
"""
