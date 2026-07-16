"""Tests for the verdict engine (Phase 4).

All Groq HTTP calls are mocked — the automated suite must never burn free-tier
quota (the live model is exercised only in manual verification). Covers the
Rule 9 empty-evidence short-circuit, the happy parse path, the Rule 15 failure
fallback, and the Rule 3 disclaimer in both languages.
"""

import json
from unittest import mock

import requests
from django.test import TestCase, override_settings

from factcheck.services import verdict_engine as ve

_EVIDENCE = [
    {
        "source_name": "wikipedia",
        "source_url": "https://en.wikipedia.org/wiki/Eiffel_Tower",
        "evidence_snippet": "The Eiffel Tower is a lattice tower in Paris, France.",
        "relevance_score": 0.85,
    }
]


def _groq_response(payload: dict):
    """Build a mock Groq chat-completions HTTP response carrying ``payload``."""
    resp = mock.Mock()
    resp.raise_for_status = mock.Mock()
    resp.json.return_value = {
        "choices": [{"message": {"content": json.dumps(payload)}}]
    }
    return resp


@override_settings(GROQ_API_KEY="test-key")
class GenerateVerdictTests(TestCase):
    """Behaviour of :func:`verdict_engine.generate_verdict`."""

    def test_empty_evidence_returns_unverifiable_without_llm_call(self):
        """No evidence short-circuits to UNVERIFIABLE — the LLM is never called."""
        with mock.patch.object(ve.requests, "post") as mock_post:
            verdict = ve.generate_verdict("Some claim", [], "en")
        mock_post.assert_not_called()
        self.assertEqual(verdict["label"], "UNVERIFIABLE")
        self.assertEqual(verdict["confidence_score"], 0)
        self.assertEqual(verdict["disclaimer"], ve.DISCLAIMER_EN)

    def test_supporting_evidence_returns_supported(self):
        """A clear supporting reply parses into SUPPORTED with score + explanation."""
        reply = {
            "label": "SUPPORTED",
            "confidence_score": 9,
            "explanation": "Wikipedia confirms the tower is in Paris.",
        }
        with mock.patch.object(ve.requests, "post", return_value=_groq_response(reply)):
            verdict = ve.generate_verdict(
                "The Eiffel Tower is located in Paris", _EVIDENCE, "en"
            )
        self.assertEqual(verdict["label"], "SUPPORTED")
        self.assertEqual(verdict["confidence_score"], 9)
        self.assertIn("Wikipedia", verdict["explanation"])
        self.assertEqual(verdict["disclaimer"], ve.DISCLAIMER_EN)

    def test_groq_timeout_returns_unverifiable_not_crash(self):
        """A Groq timeout is caught and mapped to UNVERIFIABLE (Rule 15)."""
        with mock.patch.object(
            ve.requests, "post", side_effect=requests.exceptions.Timeout("slow")
        ):
            verdict = ve.generate_verdict("Some claim", _EVIDENCE, "en")
        self.assertEqual(verdict["label"], "UNVERIFIABLE")
        self.assertIn("unavailable", verdict["explanation"])

    def test_malformed_reply_returns_unverifiable(self):
        """A reply without parseable JSON/label falls back to UNVERIFIABLE."""
        resp = mock.Mock()
        resp.raise_for_status = mock.Mock()
        resp.json.return_value = {"choices": [{"message": {"content": "not json"}}]}
        with mock.patch.object(ve.requests, "post", return_value=resp):
            verdict = ve.generate_verdict("Some claim", _EVIDENCE, "en")
        self.assertEqual(verdict["label"], "UNVERIFIABLE")

    def test_missing_api_key_returns_unverifiable(self):
        """An unconfigured key disables the engine gracefully (no HTTP call)."""
        with override_settings(GROQ_API_KEY=""):
            with mock.patch.object(ve.requests, "post") as mock_post:
                verdict = ve.generate_verdict("Some claim", _EVIDENCE, "en")
        mock_post.assert_not_called()
        self.assertEqual(verdict["label"], "UNVERIFIABLE")

    def test_disclaimer_english(self):
        """English verdicts carry the exact English disclaimer (Rule 3)."""
        reply = {"label": "SUPPORTED", "confidence_score": 8, "explanation": "Backed."}
        with mock.patch.object(ve.requests, "post", return_value=_groq_response(reply)):
            verdict = ve.generate_verdict("Claim", _EVIDENCE, "en")
        self.assertEqual(
            verdict["disclaimer"],
            "This is an AI-generated assessment, not a final ruling on truth. "
            "Verify with the cited sources.",
        )

    def test_disclaimer_bangla(self):
        """Bangla verdicts carry the Bangla disclaimer — never mixed (Rule 3)."""
        reply = {"label": "SUPPORTED", "confidence_score": 8, "explanation": "সমর্থিত।"}
        with mock.patch.object(ve.requests, "post", return_value=_groq_response(reply)):
            verdict = ve.generate_verdict("দাবি", _EVIDENCE, "bn")
        self.assertEqual(verdict["disclaimer"], ve.DISCLAIMER_BN)
        # Fallback paths carry it too.
        self.assertEqual(ve.generate_verdict("দাবি", [], "bn")["disclaimer"], ve.DISCLAIMER_BN)

    def test_confidence_clamped_to_bounds(self):
        """Out-of-range confidence values are clamped into 0-10."""
        reply = {"label": "FALSE", "confidence_score": 42, "explanation": "Contradicted."}
        with mock.patch.object(ve.requests, "post", return_value=_groq_response(reply)):
            verdict = ve.generate_verdict("Claim", _EVIDENCE, "en")
        self.assertEqual(verdict["confidence_score"], 10)

    def test_invalid_label_rejected(self):
        """A label outside the four allowed values falls back to UNVERIFIABLE."""
        reply = {"label": "PROBABLY_TRUE", "confidence_score": 5, "explanation": "Hmm."}
        with mock.patch.object(ve.requests, "post", return_value=_groq_response(reply)):
            verdict = ve.generate_verdict("Claim", _EVIDENCE, "en")
        self.assertEqual(verdict["label"], "UNVERIFIABLE")
