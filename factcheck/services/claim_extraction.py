"""Claim extraction service (Phase 2).

Will turn raw input text into clean, verifiable claim strings using spaCy for
fast dependency-parse extraction, with HuggingFace transformers as a fallback
for ambiguous cases. Not implemented in Phase 1.
"""
