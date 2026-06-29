"""Evidence retrieval service (Phase 3).

Single public entry point :func:`retrieve_evidence`. It queries three free
evidence sources in parallel — Wikipedia, Wikidata (SPARQL), and the Google
Fact Check Tools API — and returns a flat list of normalized evidence dicts.

Design rules (AGENT.md):
- Rule 11: every source checks the Postgres cache before any HTTP request, and
  writes the response back on a miss.
- Rule 15: each source is wrapped in its own try/except, so a failure in one
  never prevents the others from running. If *all* sources fail or return
  nothing, the result is an empty list — the Phase 4 verdict engine maps that to
  "Unverifiable" (Rule 9). This service never produces a verdict.
- Rule 12: all text pulled from external sources is stripped of markup and
  whitespace-normalized before it leaves this module.
- Rule 13: this module performs no database writes. Persisting evidence to the
  Source model is the caller's job (claim_service).

Every evidence dict has the shape::

    {
        "source_name": str,       # "wikipedia" | "wikidata" | "google_factcheck"
        "source_url": str,
        "evidence_snippet": str,
        "relevance_score": float, # 0.0–1.0 cosine similarity (claim vs snippet)
    }
"""

import html
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from django.conf import settings

from . import cache_service

logger = logging.getLogger(__name__)

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_WORD_RE = re.compile(r"\w+", re.UNICODE)


# --- Text sanitization (Rule 12) -------------------------------------------


def _sanitize(text: str) -> str:
    """Strip HTML, unescape entities, collapse whitespace, and length-cap text.

    All external content is untrusted; this is the single chokepoint that cleans
    it before it leaves the module (AGENT.md Rule 12). Returns ``""`` for empty
    or non-string input.
    """
    if not text or not isinstance(text, str):
        return ""
    cleaned = html.unescape(_TAG_RE.sub(" ", text))
    cleaned = _WS_RE.sub(" ", cleaned).strip()
    return cleaned[: settings.EVIDENCE_SNIPPET_MAX_CHARS]


# --- Relevance scoring ------------------------------------------------------

_EMBEDDER = None
_EMBEDDER_TRIED = False


def _get_embedder():
    """Return the lazy-loaded sentence-transformers model, or ``None``.

    Loaded once and cached. Returns ``None`` immediately when
    ``ENABLE_EMBEDDING_RELEVANCE`` is off, or if the model fails to load (missing
    package / not enough memory) — callers then fall back to a lexical score
    rather than crashing, mirroring the Phase 2 NLP graceful-degrade pattern.
    """
    global _EMBEDDER, _EMBEDDER_TRIED
    if not getattr(settings, "ENABLE_EMBEDDING_RELEVANCE", True):
        return None
    if _EMBEDDER_TRIED:
        return _EMBEDDER
    _EMBEDDER_TRIED = True
    try:
        from sentence_transformers import SentenceTransformer

        _EMBEDDER = SentenceTransformer(settings.EMBEDDING_MODEL)
    except Exception as exc:  # noqa: BLE001 - degrade to lexical score, never crash
        logger.warning(
            "Embedding model '%s' unavailable; relevance falls back to lexical "
            "overlap (%s)",
            settings.EMBEDDING_MODEL,
            exc,
        )
        _EMBEDDER = None
    return _EMBEDDER


def _lexical_relevance(claim: str, snippet: str) -> float:
    """Jaccard token-overlap similarity in ``[0, 1]`` — the no-model fallback."""
    a = set(_WORD_RE.findall(claim.lower()))
    b = set(_WORD_RE.findall(snippet.lower()))
    if not a or not b:
        return 0.0
    return round(len(a & b) / len(a | b), 4)


def _relevance(claim: str, snippet: str) -> float:
    """Return cosine similarity of ``claim`` vs ``snippet`` embeddings in ``[0, 1]``.

    Uses the sentence-transformers model when available; otherwise falls back to
    :func:`_lexical_relevance`. The cosine value is clamped to ``[0, 1]`` (a
    negative cosine means "unrelated" → 0.0).
    """
    if not claim or not snippet:
        return 0.0
    model = _get_embedder()
    if model is None:
        return _lexical_relevance(claim, snippet)
    try:
        emb = model.encode([claim, snippet], normalize_embeddings=True)
        cosine = float(emb[0] @ emb[1])
        return round(max(0.0, min(1.0, cosine)), 4)
    except Exception as exc:  # noqa: BLE001 - never let scoring crash retrieval
        logger.warning("embedding relevance failed; using lexical (%s)", exc)
        return _lexical_relevance(claim, snippet)


# --- HTTP helper ------------------------------------------------------------


def _http_get(url: str, params: dict | None = None) -> requests.Response:
    """GET ``url`` with the project User-Agent and the configured timeout.

    Centralizes the two non-negotiable HTTP settings (Rule: explicit timeout +
    descriptive User-Agent) so no source can forget them. Raises for HTTP error
    status so the caller's try/except records the failure.
    """
    response = requests.get(
        url,
        params=params,
        timeout=settings.HTTP_TIMEOUT_SECONDS,
        headers={"User-Agent": settings.PROJECT_USER_AGENT},
    )
    response.raise_for_status()
    return response


def _cached_json(api_name: str, query: str, fetch, ttl_seconds: int) -> dict | None:
    """Return cached JSON for ``query`` under ``api_name``, fetching on a miss.

    Implements the cache-before-HTTP contract (Rule 11): builds the deterministic
    key, returns the cached payload if fresh, else calls ``fetch()`` (which does
    the HTTP request and returns a JSON-serializable dict), writes it to the
    cache with ``ttl_seconds``, and returns it. ``fetch`` exceptions propagate to
    the source-level try/except.
    """
    key = cache_service.make_cache_key(api_name, query)
    cached = cache_service.get_cached_response(api_name, key)
    if cached is not None:
        logger.debug("cache hit: %s", api_name)
        return cached

    payload = fetch()
    if payload is not None:
        cache_service.set_cached_response(api_name, key, payload, ttl_seconds)
    return payload


# --- Source 1: Wikipedia ----------------------------------------------------


def _wikipedia_for_lang(claim: str, wiki_lang: str) -> list[dict]:
    """Search one Wikipedia edition (``wiki_lang``) and return 0–1 evidence dicts.

    Two-step MediaWiki query: ``list=search`` to find the best-matching title,
    then ``prop=extracts`` (intro, plain text) for that page. Cached as one
    payload per (edition, claim). Returns ``[]`` when nothing matches.
    """
    api = f"https://{wiki_lang}.wikipedia.org/w/api.php"

    def fetch():
        search = _http_get(
            api,
            {
                "action": "query",
                "format": "json",
                "list": "search",
                "srsearch": claim,
                "srlimit": 1,
            },
        ).json()
        hits = search.get("query", {}).get("search", [])
        if not hits:
            return {"title": None, "extract": "", "lang": wiki_lang}
        title = hits[0]["title"]
        extract = _http_get(
            api,
            {
                "action": "query",
                "format": "json",
                "prop": "extracts",
                "exintro": 1,
                "explaintext": 1,
                "redirects": 1,
                "titles": title,
            },
        ).json()
        pages = extract.get("query", {}).get("pages", {})
        text = next(iter(pages.values()), {}).get("extract", "") if pages else ""
        return {"title": title, "extract": text, "lang": wiki_lang}

    data = _cached_json(
        f"wikipedia_{wiki_lang}", claim, fetch, settings.CACHE_TTL_WIKIPEDIA
    )
    if not data or not data.get("title"):
        return []

    snippet = _sanitize(data.get("extract", ""))
    if not snippet:
        return []

    title_url = data["title"].replace(" ", "_")
    source_url = f"https://{data['lang']}.wikipedia.org/wiki/{title_url}"
    return [
        {
            "source_name": "wikipedia",
            "source_url": source_url,
            "evidence_snippet": snippet,
            "relevance_score": _relevance(claim, snippet),
        }
    ]


def _wikipedia(claim: str, lang: str) -> list[dict]:
    """Wikipedia source. Bangla claims try ``bn`` first, then fall back to ``en``.

    English (and any non-Bangla) claims query the English edition directly. The
    fallback chain satisfies AGENT.md Rule 15 within the source itself.
    """
    if lang == "bn":
        results = _wikipedia_for_lang(claim, "bn")
        if results:
            return results
        logger.info("wikipedia: no bn result, falling back to en")
        return _wikipedia_for_lang(claim, "en")
    return _wikipedia_for_lang(claim, "en")


# --- Source 2: Wikidata (SPARQL) -------------------------------------------

_PROPER_SPAN_RE = re.compile(r"\b[A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)*\b")
_LEADING_ARTICLE_RE = re.compile(r"^(the|a|an)\s+", re.IGNORECASE)


def _main_entity_query(claim: str) -> str:
    """Return the claim's main entity as a search term for ``wbsearchentities``.

    ``wbsearchentities`` matches entity labels/aliases, not full sentences, so a
    raw claim almost never resolves. This picks the first capitalized
    proper-noun span — the grammatical subject in the SVO claims Phase 2
    produces (e.g. "Eiffel Tower", "Marie Curie") — stripping a leading article.
    Scripts without capitalization (e.g. Bangla) have no span, so the full claim
    is used as-is. A simple, dependency-free heuristic kept deliberately light.
    """
    for span in _PROPER_SPAN_RE.findall(claim):
        candidate = _LEADING_ARTICLE_RE.sub("", span).strip()
        if candidate:
            return candidate
    return claim


def _wikidata(claim: str, lang: str) -> list[dict]:
    """Wikidata source: resolve the claim's main entity, then SPARQL label+desc.

    Step 1 derives the claim's main entity (:func:`_main_entity_query`) and maps
    it to its best entity QID via ``wbsearchentities``. Step 2 runs a simple
    SPARQL query for that entity's ``rdfs:label`` and ``schema:description`` in
    the claim language (falling back to English), yielding one structured-fact
    snippet. Returns ``[]`` when no entity matches.
    """
    lang_pref = lang if lang in ("en", "bn") else "en"
    entity_query = _main_entity_query(claim)

    def fetch():
        search = _http_get(
            "https://www.wikidata.org/w/api.php",
            {
                "action": "wbsearchentities",
                "format": "json",
                "language": lang_pref,
                "uselang": lang_pref,
                "type": "item",
                "limit": 1,
                "search": entity_query,
            },
        ).json()
        entities = search.get("search", [])
        if not entities:
            return {"qid": None, "label": "", "description": ""}
        qid = entities[0]["id"]

        # Simple SPARQL: label + description for the resolved entity, preferring
        # the claim language and falling back to English.
        sparql = (
            "SELECT ?label ?description WHERE { "
            f"OPTIONAL {{ wd:{qid} rdfs:label ?label . "
            f'FILTER(LANG(?label) IN ("{lang_pref}", "en")) }} '
            f"OPTIONAL {{ wd:{qid} schema:description ?description . "
            f'FILTER(LANG(?description) IN ("{lang_pref}", "en")) }} '
            "} LIMIT 1"
        )
        result = _http_get(
            "https://query.wikidata.org/sparql",
            {"query": sparql, "format": "json"},
        ).json()
        bindings = result.get("results", {}).get("bindings", [])
        row = bindings[0] if bindings else {}
        return {
            "qid": qid,
            "label": row.get("label", {}).get("value", ""),
            "description": row.get("description", {}).get("value", ""),
        }

    data = _cached_json("wikidata", claim, fetch, settings.CACHE_TTL_WIKIDATA)
    if not data or not data.get("qid"):
        return []

    parts = [p for p in (data.get("label"), data.get("description")) if p]
    snippet = _sanitize(" — ".join(parts))
    if not snippet:
        return []

    return [
        {
            "source_name": "wikidata",
            "source_url": f"https://www.wikidata.org/wiki/{data['qid']}",
            "evidence_snippet": snippet,
            "relevance_score": _relevance(claim, snippet),
        }
    ]


# --- Source 3: Google Fact Check Tools API ---------------------------------


def _google_factcheck(claim: str, lang: str) -> list[dict]:
    """Google Fact Check Tools source: matching published fact-checks.

    Requires ``GOOGLE_FACTCHECK_API_KEY`` (AGENT.md Rule 6/7 — from settings/.env).
    When the key is absent the source is skipped (returns ``[]``), not treated as
    an error. Each returned claimReview becomes one evidence dict whose snippet is
    the publisher's textual rating and whose URL is the fact-check page.
    """
    api_key = settings.GOOGLE_FACTCHECK_API_KEY
    if not api_key:
        logger.info("google_factcheck: no API key configured, skipping source")
        return []

    lang_code = lang if lang in ("en", "bn") else "en"

    def fetch():
        return _http_get(
            "https://factchecktools.googleapis.com/v1alpha1/claims:search",
            {
                "query": claim,
                "languageCode": lang_code,
                "pageSize": 5,
                "key": api_key,
            },
        ).json()

    data = _cached_json(
        "google_factcheck", claim, fetch, settings.CACHE_TTL_GOOGLE_FACTCHECK
    )
    if not data:
        return []

    results = []
    for item in data.get("claims", []):
        claim_text = item.get("text", "")
        for review in item.get("claimReview", []):
            rating = review.get("textualRating", "")
            publisher = review.get("publisher", {}).get("name", "")
            url = review.get("url", "")
            if not url:
                continue
            snippet = _sanitize(
                f"{publisher}: {rating}. {claim_text}".strip(". ")
            )
            results.append(
                {
                    "source_name": "google_factcheck",
                    "source_url": url,
                    "evidence_snippet": snippet,
                    "relevance_score": _relevance(claim, snippet),
                }
            )
    return results


# --- Public interface -------------------------------------------------------


def retrieve_evidence(claim: str, lang: str) -> list[dict]:
    """Retrieve evidence for ``claim`` from all sources in parallel.

    The single public interface of this module — other services call only this.
    Runs Wikipedia, Wikidata, and Google Fact Check concurrently via a
    :class:`ThreadPoolExecutor`. Each source is independently guarded: any
    exception is caught and logged so it can never sink the others (Rule 15).
    Results are flattened and sorted by descending relevance. Returns ``[]`` when
    every source fails or finds nothing (the verdict engine handles that case in
    Phase 4). Performs no database writes (Rule 13).
    """
    claim = (claim or "").strip()
    if not claim:
        return []

    # Resolved at call time (not import) so tests can patch individual sources.
    sources = (_wikipedia, _wikidata, _google_factcheck)

    evidence: list[dict] = []
    with ThreadPoolExecutor(max_workers=len(sources)) as executor:
        futures = {executor.submit(src, claim, lang): src for src in sources}
        for future in as_completed(futures):
            source = futures[future]
            try:
                evidence.extend(future.result())
            except Exception as exc:  # noqa: BLE001 - one source failing is non-fatal
                logger.warning(
                    "evidence source %s failed: %s",
                    getattr(source, "__name__", repr(source)),
                    exc,
                )

    evidence.sort(key=lambda e: e["relevance_score"], reverse=True)
    return evidence
