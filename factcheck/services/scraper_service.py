"""URL scraping + sanitization service (Phase 3).

Fetches a URL and reduces it to clean, readable text. All scraped content is
untrusted and must be stripped of markup before reaching any LLM prompt
(AGENT.md Rule 12). Defends with: an http(s)-only scheme check (Rule 6), a hard
request timeout, and a maximum content length (truncate, never crash).

Used by the URL input tab wired up in Phase 4 — here it only needs to exist and
be tested.
"""

import logging
import re
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from django.conf import settings

logger = logging.getLogger(__name__)

# Tags whose text content is noise, not readable page content.
_STRIP_TAGS = ["script", "style", "noscript", "nav", "header", "footer", "aside", "form"]

_WS_RE = re.compile(r"\s+")


def scrape_url(url: str) -> str:
    """Fetch ``url`` and return its clean, readable text.

    Rejects any non-``http``/``https`` URL with :class:`ValueError` before making
    a request (AGENT.md Rule 6 — never follow ``file://``, ``ftp://``, etc.).
    Fetches with a descriptive User-Agent and the configured timeout, strips
    scripts/styles/navigation chrome, collapses whitespace, and truncates the
    result to ``settings.SCRAPER_MAX_CONTENT_CHARS`` (truncate, don't crash).

    Returns the cleaned text (possibly empty). Network/HTTP errors propagate to
    the caller as :class:`requests.exceptions.RequestException` subclasses so the
    caller decides how to fall back.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"Refusing non-http(s) URL scheme: {parsed.scheme!r}")

    response = requests.get(
        url,
        timeout=settings.HTTP_TIMEOUT_SECONDS,
        headers={"User-Agent": settings.PROJECT_USER_AGENT},
    )
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "lxml")
    for tag in soup(_STRIP_TAGS):
        tag.decompose()

    text = soup.get_text(separator=" ")
    text = _WS_RE.sub(" ", text).strip()

    max_chars = settings.SCRAPER_MAX_CONTENT_CHARS
    if len(text) > max_chars:
        logger.info("scrape_url: truncating %d chars to %d", len(text), max_chars)
        text = text[:max_chars]

    return text
