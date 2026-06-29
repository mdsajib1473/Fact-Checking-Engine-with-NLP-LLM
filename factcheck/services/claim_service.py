"""Claim orchestration service (Phase 2 + Phase 3).

Thin coordination layer that wires the pure pipeline stages to the database. It
detects language, extracts claims, persists each as a :class:`Claim` row, then
(Phase 3) retrieves evidence for each claim and persists it to the
:class:`Source` model.

Keeping *all* database writes here — and none in ``claim_extraction.py`` or
``evidence_retrieval.py`` — preserves the rule that pipeline stages stay
independently testable and side-effect free (AGENT.md Rule 13).
"""

import logging

from ..models import Claim, Source
from .claim_extraction import extract_claims
from .evidence_retrieval import retrieve_evidence
from .language_service import detect_language

logger = logging.getLogger(__name__)

_VALID_INPUT_TYPES = {choice.value for choice in Claim.InputType}


def process_text_input(raw_text: str, source_type: str) -> list[Claim]:
    """Extract claims from ``raw_text`` and persist each as a :class:`Claim` row.

    Detects the input language, runs claim extraction, and saves one ``Claim``
    per extracted claim with ``raw_text``, ``extracted_claim``, ``language``,
    ``source_input_type``, and ``created_at`` (auto) populated. Returns the list
    of saved ``Claim`` instances (empty when no claim clears the confidence
    threshold). Persistence lives here, never in the extraction stage.

    The extraction confidence is not part of the locked ``claims`` schema, so it
    is attached to each returned instance as a transient ``.confidence``
    attribute (not a database column) for callers that surface it — e.g. the
    development endpoint.

    ``source_type`` must be one of the :class:`Claim.InputType` values
    (``"text"`` / ``"url"``); anything else raises :class:`ValueError`.
    """
    if source_type not in _VALID_INPUT_TYPES:
        raise ValueError(
            f"source_type must be one of {sorted(_VALID_INPUT_TYPES)}, got {source_type!r}"
        )

    language = detect_language(raw_text)
    extracted = extract_claims(raw_text)

    saved = []
    for item in extracted:
        claim = Claim.objects.create(
            raw_text=raw_text,
            extracted_claim=item["claim"],
            # Prefer the per-claim language from extraction; fall back to the
            # document-level detection for safety.
            language=item.get("lang") or language,
            source_input_type=source_type,
        )
        # Transient (non-persisted) — carried through to the response only.
        claim.confidence = item.get("confidence")
        saved.append(claim)

    logger.info(
        "process_text_input: %d claim(s) saved (lang=%s, source=%s)",
        len(saved),
        language,
        source_type,
    )
    return saved


def gather_evidence(claim: Claim) -> list[dict]:
    """Retrieve evidence for ``claim`` and persist it to the :class:`Source` model.

    Calls the evidence-retrieval pipeline (which performs no DB writes — Rule 13)
    and saves each returned evidence dict as a ``Source`` row with ``verdict=None``
    (no verdict exists until Phase 4; the rows are linked then). Returns the list
    of evidence dicts unchanged so the caller can include them in a response.
    """
    evidence = retrieve_evidence(claim.extracted_claim, claim.language)

    rows = [
        Source(
            verdict=None,
            source_name=item["source_name"],
            source_url=item["source_url"],
            evidence_snippet=item["evidence_snippet"],
            relevance_score=item["relevance_score"],
        )
        for item in evidence
    ]
    if rows:
        Source.objects.bulk_create(rows)

    logger.info(
        "gather_evidence: %d source(s) saved for claim %s", len(rows), claim.id
    )
    return evidence


def process_text_input_with_evidence(raw_text: str, source_type: str) -> list[dict]:
    """Full Phase 3 pipeline: extract + persist claims, then retrieve evidence.

    Orchestration entry point for the development endpoint. Runs
    :func:`process_text_input`, then :func:`gather_evidence` for each saved claim,
    and returns one dict per claim shaped for the API response::

        {"claim": str, "language": str, "confidence": float, "evidence": [...]}

    All persistence happens in the called helpers (Rule 13); this function only
    assembles the response payload.
    """
    claims = process_text_input(raw_text, source_type)
    return [
        {
            "claim": claim.extracted_claim,
            "language": claim.language,
            "confidence": getattr(claim, "confidence", None),
            "evidence": gather_evidence(claim),
        }
        for claim in claims
    ]
