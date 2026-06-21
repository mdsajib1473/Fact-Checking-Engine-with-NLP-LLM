"""Verdict engine service (Phase 4).

Will use the Groq free-tier LLM for chain-of-thought verdict reasoning with
mandatory source citation (AGENT.md Rule 9): no verdict without at least one
source, defaulting to "unverifiable" when evidence is missing. Not implemented
in Phase 1.
"""
