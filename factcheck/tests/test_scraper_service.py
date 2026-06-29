"""Tests for the URL scraper service (Phase 3).

Covers the safety contract: a valid page is reduced to clean text with markup
stripped (AGENT.md Rule 12), a non-http(s) scheme is rejected before any request
(Rule 6), the configured timeout is passed on every request, and oversized
content is truncated rather than crashing.
"""

from unittest import mock

from django.conf import settings
from django.test import TestCase

from factcheck.services import scraper_service


def _fake_response(html_text):
    """Build a stand-in ``requests.Response`` with ``text`` and a no-op raise."""
    resp = mock.Mock()
    resp.text = html_text
    resp.raise_for_status = mock.Mock()
    return resp


class ScraperServiceTests(TestCase):
    """Behaviour of :func:`scraper_service.scrape_url`."""

    _HTML = (
        "<html><head><style>.x{color:red}</style></head><body>"
        "<nav>Home About</nav>"
        "<script>evil()</script>"
        "<p>The Eiffel Tower is in Paris.</p>"
        "<footer>copyright</footer></body></html>"
    )

    @mock.patch("factcheck.services.scraper_service.requests.get")
    def test_valid_url_returns_clean_text(self, mock_get):
        """HTML is stripped to readable text; scripts/styles/nav/footer removed."""
        mock_get.return_value = _fake_response(self._HTML)
        text = scraper_service.scrape_url("https://example.com/page")
        self.assertIn("The Eiffel Tower is in Paris.", text)
        self.assertNotIn("evil()", text)
        self.assertNotIn("color:red", text)
        self.assertNotIn("Home About", text)
        self.assertNotIn("copyright", text)

    def test_non_http_scheme_raises_value_error(self):
        """A non-http(s) scheme is rejected before any network call."""
        for bad in ("ftp://example.com/x", "file:///etc/passwd", "javascript:alert(1)"):
            with self.assertRaises(ValueError):
                scraper_service.scrape_url(bad)

    @mock.patch("factcheck.services.scraper_service.requests.get")
    def test_timeout_is_enforced(self, mock_get):
        """Every request passes the configured timeout."""
        mock_get.return_value = _fake_response("<p>ok</p>")
        scraper_service.scrape_url("https://example.com")
        _, kwargs = mock_get.call_args
        self.assertEqual(kwargs["timeout"], settings.HTTP_TIMEOUT_SECONDS)

    @mock.patch("factcheck.services.scraper_service.requests.get")
    def test_oversized_content_is_truncated(self, mock_get):
        """Content beyond the max length is truncated, not crashed on."""
        big = "<p>" + ("word " * 40000) + "</p>"
        mock_get.return_value = _fake_response(big)
        text = scraper_service.scrape_url("https://example.com")
        self.assertLessEqual(len(text), settings.SCRAPER_MAX_CONTENT_CHARS)
