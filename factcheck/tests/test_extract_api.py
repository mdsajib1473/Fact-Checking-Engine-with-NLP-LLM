"""Tests for the POST /api/v1/extract/ and /api/v1/check-url/ endpoints.

Confirms the success-response shape (claims + evidence + verdict since
Phase 4), the input-validation rejections (AGENT.md Rule 6), and the
verdict/source persistence wiring (Rules 9/13/14). External stages are mocked
where determinism matters: evidence retrieval and the verdict engine are
patched at the ``claim_service`` seam.
"""

from unittest import mock

from django.test import TestCase
from django.urls import reverse

from factcheck.models import Claim, Source, Verdict

_FAKE_EVIDENCE = [
    {
        "source_name": "wikipedia",
        "source_url": "https://en.wikipedia.org/wiki/Earth",
        "evidence_snippet": "Earth orbits the Sun.",
        "relevance_score": 0.9,
    }
]

_FAKE_VERDICT = {
    "label": "SUPPORTED",
    "confidence_score": 9,
    "explanation": "Wikipedia confirms the claim.",
    "disclaimer": (
        "This is an AI-generated assessment, not a final ruling on truth. "
        "Verify with the cited sources."
    ),
}


class ExtractApiTests(TestCase):
    """Request/response contract of the claim-extraction endpoint."""

    def setUp(self):
        """Resolve the endpoint URL once for all tests."""
        self.url = reverse("factcheck:extract")

    def test_valid_request_returns_200_with_shape(self):
        """A valid English paragraph returns 200 with claims/language/count."""
        text = "The Earth orbits the Sun. Water boils at 100 degrees Celsius."
        response = self.client.post(
            self.url, data={"text": text, "source_type": "text"}, content_type="application/json"
        )
        self.assertEqual(response.status_code, 200)

        body = response.json()
        self.assertEqual(set(body), {"claims", "language", "count"})
        self.assertEqual(body["language"], "en")
        self.assertEqual(body["count"], len(body["claims"]))
        self.assertGreaterEqual(body["count"], 2)
        self.assertEqual(Claim.objects.count(), body["count"])

    def test_source_type_defaults_to_text(self):
        """``source_type`` is optional and defaults to ``"text"``."""
        response = self.client.post(
            self.url, data={"text": "The Earth orbits the Sun."}, content_type="application/json"
        )
        self.assertEqual(response.status_code, 200)

    def test_empty_text_returns_400(self):
        """Empty text fails validation with 400."""
        response = self.client.post(
            self.url, data={"text": "", "source_type": "text"}, content_type="application/json"
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Claim.objects.count(), 0)

    def test_too_short_text_returns_400(self):
        """Text below the minimum length fails validation with 400."""
        response = self.client.post(
            self.url, data={"text": "short", "source_type": "text"}, content_type="application/json"
        )
        self.assertEqual(response.status_code, 400)

    def test_oversized_text_returns_400(self):
        """Text above the maximum length fails validation with 400."""
        response = self.client.post(
            self.url,
            data={"text": "a" * 5001, "source_type": "text"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Claim.objects.count(), 0)

    def test_missing_text_returns_400(self):
        """A request body with no ``text`` field fails validation with 400."""
        response = self.client.post(
            self.url, data={"source_type": "text"}, content_type="application/json"
        )
        self.assertEqual(response.status_code, 400)


class ExtractApiVerdictShapeTests(TestCase):
    """Phase 4 response shape + persistence, with the external stages mocked."""

    def setUp(self):
        """Resolve the endpoint URL and patch retrieval + verdict at the seam."""
        self.url = reverse("factcheck:extract")
        retrieval = mock.patch(
            "factcheck.services.claim_service.retrieve_evidence",
            return_value=list(_FAKE_EVIDENCE),
        )
        verdict = mock.patch(
            "factcheck.services.claim_service.generate_verdict",
            return_value=dict(_FAKE_VERDICT),
        )
        retrieval.start()
        verdict.start()
        self.addCleanup(retrieval.stop)
        self.addCleanup(verdict.stop)

    def _post(self, text):
        return self.client.post(
            self.url,
            data={"text": text, "source_type": "text"},
            content_type="application/json",
        )

    def test_response_includes_evidence_and_verdict_per_claim(self):
        """Each claim carries evidence plus the full verdict dict (Rule 10)."""
        response = self._post("The Earth orbits the Sun.")
        self.assertEqual(response.status_code, 200)

        body = response.json()
        self.assertEqual(set(body), {"claims", "language", "count"})
        self.assertGreaterEqual(body["count"], 1)

        entry = body["claims"][0]
        self.assertLessEqual(
            {"claim", "language", "evidence", "verdict"}, set(entry)
        )
        self.assertEqual(entry["evidence"], _FAKE_EVIDENCE)
        self.assertEqual(
            set(entry["verdict"]),
            {"label", "confidence_score", "explanation", "disclaimer"},
        )
        self.assertEqual(entry["verdict"]["label"], "SUPPORTED")
        self.assertIn("AI-generated assessment", entry["verdict"]["disclaimer"])

    def test_verdict_persisted_and_sources_linked(self):
        """A Verdict row is saved per claim and its Source rows are linked (Rule 14)."""
        response = self._post("The Earth orbits the Sun.")
        self.assertEqual(response.status_code, 200)

        claim = Claim.objects.first()
        verdict = Verdict.objects.get(claim=claim)
        self.assertEqual(verdict.label, "supported")
        self.assertEqual(verdict.confidence_score, 9)
        self.assertIsNotNone(verdict.created_at)

        sources = Source.objects.filter(verdict=verdict)
        self.assertEqual(sources.count(), 1)
        self.assertEqual(sources.first().source_name, "wikipedia")
        self.assertFalse(Source.objects.filter(verdict=None).exists())


class CheckUrlApiTests(TestCase):
    """Request/response contract of the URL fact-check endpoint."""

    def setUp(self):
        """Resolve the endpoint URL once for all tests."""
        self.url = reverse("factcheck:check_url")

    def test_missing_url_returns_400(self):
        """A body without ``url`` fails validation."""
        response = self.client.post(self.url, data={}, content_type="application/json")
        self.assertEqual(response.status_code, 400)

    def test_invalid_url_returns_400(self):
        """A malformed URL fails validation before any fetch."""
        response = self.client.post(
            self.url, data={"url": "not-a-url"}, content_type="application/json"
        )
        self.assertEqual(response.status_code, 400)

    def test_scraped_page_runs_pipeline(self):
        """A scrapeable page feeds the same pipeline with source_type='url'."""
        with mock.patch(
            "factcheck.services.claim_service.scrape_url",
            return_value="The Earth orbits the Sun. Water boils at 100 degrees Celsius.",
        ), mock.patch(
            "factcheck.services.claim_service.retrieve_evidence",
            return_value=list(_FAKE_EVIDENCE),
        ), mock.patch(
            "factcheck.services.claim_service.generate_verdict",
            return_value=dict(_FAKE_VERDICT),
        ):
            response = self.client.post(
                self.url,
                data={"url": "https://example.com/article"},
                content_type="application/json",
            )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertGreaterEqual(body["count"], 1)
        claim = Claim.objects.first()
        self.assertEqual(claim.source_input_type, "url")
        self.assertEqual(claim.source_url, "https://example.com/article")

    def test_unreachable_page_returns_400(self):
        """A fetch failure surfaces as a 400 with a message, never a crash (Rule 15)."""
        import requests as _requests

        with mock.patch(
            "factcheck.services.claim_service.scrape_url",
            side_effect=_requests.exceptions.ConnectionError("down"),
        ):
            response = self.client.post(
                self.url,
                data={"url": "https://unreachable.example.com/"},
                content_type="application/json",
            )
        self.assertEqual(response.status_code, 400)
        self.assertIn("url", response.json())
