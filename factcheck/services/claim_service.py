"""Claim orchestration service (Phase 2 + Phase 3 + Phase 4).

Thin coordination layer that wires the pure pipeline stages to the database. It
detects language, extracts claims, persists each as a :class:`Claim` row,
retrieves evidence for each claim and persists it to the :class:`Source` model
(Phase 3), then generates a verdict per claim, persists it to the
:class:`Verdict` model, and links the evidence rows to it (Phase 4).

Keeping *all* database writes here — and none in ``claim_extraction.py``,
``evidence_retrieval.py``, or ``verdict_engine.py`` — preserves the rule that
pipeline stages stay independently testable and side-effect free (AGENT.md
Rule 13). The Verdict + Source rows (with auto ``created_at``) double as the
audit log required by Rule 14.
"""

import logging

from django.conf import settings

from ..models import Claim, Source, Verdict
from .claim_extraction import extract_claims
from .evidence_retrieval import retrieve_evidence
from .language_service import detect_language
from .scraper_service import scrape_url
from .verdict_engine import generate_verdict

logger = logging.getLogger(__name__)

_VALID_INPUT_TYPES = {choice.value for choice in Claim.InputType}


def process_text_input(
    raw_text: str, source_type: str, source_url: str | None = None
) -> list[Claim]:
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
    ``source_url`` records the page a URL submission was scraped from.
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
            source_url=source_url,
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


def gather_evidence(claim: Claim) -> tuple[list[dict], list[Source]]:
    """Retrieve evidence for ``claim`` and persist it to the :class:`Source` model.

    Calls the evidence-retrieval pipeline (which performs no DB writes — Rule 13)
    and saves each returned evidence dict as a ``Source`` row with ``verdict=None``
    (linked to the claim's verdict by :func:`score_claim` once it exists).
    Returns both the evidence dicts (for the API response) and the saved rows
    (for linking).
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
    return evidence, rows


def score_claim(claim: Claim, evidence: list[dict], sources: list[Source]) -> dict:
    """Generate and persist the verdict for ``claim``, linking its evidence rows.

    Calls the verdict engine (pure, no DB writes — Rule 13), saves the result as
    a :class:`Verdict` row (label stored lowercase to match the model choices),
    and points the previously-unlinked ``Source`` rows at the new verdict. The
    persisted Verdict + Source rows with their ``created_at`` timestamps form
    the audit trail of the decision (Rule 14). Returns the verdict dict
    unchanged (uppercase label + disclaimer) for the API response.
    """
    verdict_dict = generate_verdict(claim.extracted_claim, evidence, claim.language)

    verdict = Verdict.objects.create(
        claim=claim,
        label=verdict_dict["label"].lower(),
        confidence_score=verdict_dict["confidence_score"],
        explanation=verdict_dict["explanation"],
    )
    if sources:
        Source.objects.filter(pk__in=[s.pk for s in sources]).update(verdict=verdict)

    logger.info(
        "score_claim: verdict %s (%d/10) saved for claim %s with %d source(s)",
        verdict.label,
        verdict.confidence_score,
        claim.id,
        len(sources),
    )
    return verdict_dict


def process_text_input_with_evidence(
    raw_text: str, source_type: str, source_url: str | None = None
) -> list[dict]:
    """Full pipeline: extract + persist claims, retrieve evidence, score verdicts.

    Orchestration entry point for the API. Runs :func:`process_text_input`, then
    :func:`gather_evidence` and :func:`score_claim` for each saved claim, and
    returns one dict per claim shaped for the API response::

        {
            "claim": str,
            "language": str,
            "confidence": float,
            "evidence": [...],
            "verdict": {"label", "confidence_score", "explanation", "disclaimer"},
        }

    All persistence happens in the called helpers (Rule 13); this function only
    assembles the response payload. ``source_url`` is recorded on each Claim when
    the text came from a scraped URL.
    """
    claims = process_text_input(raw_text, source_type, source_url=source_url)
    results = []
    for claim in claims:
        evidence, sources = gather_evidence(claim)
        verdict = score_claim(claim, evidence, sources)
        results.append(
            {
                "claim": claim.extracted_claim,
                "language": claim.language,
                "confidence": getattr(claim, "confidence", None),
                "evidence": evidence,
                "verdict": verdict,
            }
        )
    return results


def process_url_input(url: str) -> list[dict]:
    """Scrape ``url`` and run the full pipeline over the extracted page text.

    Fetches clean text via :func:`scraper_service.scrape_url` (which enforces
    the http(s)-only scheme check, timeout, and content cap — Rules 6/12), then
    hands it to :func:`process_text_input_with_evidence` with
    ``source_type="url"`` and the page URL recorded on each Claim. Raises
    :class:`ValueError` when the page yields no usable text; scraper network
    errors propagate for the view to translate into a 4xx/5xx response.
    """
    text = scrape_url(url)
    if not text.strip():
        raise ValueError("The page contained no readable text to fact-check.")
    # Hold URL submissions to the same input bound as the text tab so a long
    # article can't fan out into dozens of Groq calls (free-tier limits).
    text = text[: settings.EXTRACT_INPUT_MAX_CHARS]
    return process_text_input_with_evidence(text, "url", source_url=url)
