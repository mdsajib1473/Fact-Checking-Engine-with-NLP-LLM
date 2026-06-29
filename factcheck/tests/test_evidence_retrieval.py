"""Tests for the evidence retrieval service (Phase 3).

Mixes live API calls (Wikipedia English, Google Fact Check — exercising the real
free endpoints as the phase requires) with mocked tests for the fallback logic
(AGENT.md Rule 15): a Bangla claim must try Bangla Wikipedia first, one source
failing must not sink the others, and all sources failing must yield ``[]``.

Relevance scoring is mocked out where the embedding model is irrelevant, to keep
those tests fast and offline-friendly.
"""

from unittest import mock, skipUnless

import requests
from django.conf import settings
from django.test import TestCase

from factcheck.services import evidence_retrieval as er

_GOOD = {
    "source_name": "wikidata",
    "source_url": "https://www.wikidata.org/wiki/Q243",
    "evidence_snippet": "Eiffel Tower — tower in Paris, France",
    "relevance_score": 0.8,
}


class WikipediaSourceTests(TestCase):
    """Wikipedia source: live English lookup + Bangla-first fallback order."""

    @mock.patch.object(er, "_relevance", return_value=0.9)
    def test_english_claim_returns_snippet(self, _rel):
        """A known English claim returns a non-empty Wikipedia snippet (live call)."""
        results = er._wikipedia("The Eiffel Tower is located in Paris", "en")
        self.assertTrue(results, "expected a Wikipedia hit for the Eiffel Tower")
        ev = results[0]
        self.assertEqual(ev["source_name"], "wikipedia")
        self.assertTrue(ev["evidence_snippet"])
        self.assertIn("eiffel", ev["evidence_snippet"].lower())
        self.assertTrue(ev["source_url"].startswith("https://en.wikipedia.org/"))

    def test_bangla_claim_tries_bn_first_then_falls_back(self):
        """A Bangla claim queries bn.wikipedia first, then en on an empty result."""

        def fake_lang(claim, wiki_lang):
            return [] if wiki_lang == "bn" else [dict(_GOOD, source_name="wikipedia")]

        with mock.patch.object(
            er, "_wikipedia_for_lang", side_effect=fake_lang
        ) as m:
            results = er._wikipedia("আইফেল টাওয়ার প্যারিসে অবস্থিত", "bn")

        attempted = [call.args[1] for call in m.call_args_list]
        self.assertEqual(attempted[0], "bn")  # Bangla attempted first
        self.assertIn("en", attempted)        # then English fallback
        self.assertTrue(results)


class GoogleFactCheckSourceTests(TestCase):
    """Google Fact Check Tools source (live call, needs the API key)."""

    @skipUnless(
        settings.GOOGLE_FACTCHECK_API_KEY, "GOOGLE_FACTCHECK_API_KEY not configured"
    )
    @mock.patch.object(er, "_relevance", return_value=0.9)
    def test_returns_results_for_known_claim(self, _rel):
        """A heavily fact-checked claim returns at least one rated fact-check."""
        results = er._google_factcheck("The Earth is flat", "en")
        self.assertTrue(results, "expected fact-checks for 'The Earth is flat'")
        ev = results[0]
        self.assertEqual(ev["source_name"], "google_factcheck")
        self.assertTrue(ev["source_url"].startswith("http"))
        self.assertTrue(ev["evidence_snippet"])


class PipelineResilienceTests(TestCase):
    """Fallback-chain guarantees of :func:`retrieve_evidence` (Rule 15)."""

    def _boom(self, *_args, **_kwargs):
        raise requests.exceptions.Timeout("simulated source failure")

    def test_one_source_failure_does_not_crash_pipeline(self):
        """A timeout in one source still returns the others' evidence."""
        with mock.patch.object(er, "_wikipedia", side_effect=self._boom), mock.patch.object(
            er, "_wikidata", return_value=[_GOOD]
        ), mock.patch.object(er, "_google_factcheck", return_value=[]):
            results = er.retrieve_evidence("anything", "en")
        self.assertEqual(results, [_GOOD])

    def test_all_sources_failing_returns_empty_list(self):
        """When every source raises, the result is an empty list (Unverifiable)."""
        with mock.patch.object(er, "_wikipedia", side_effect=self._boom), mock.patch.object(
            er, "_wikidata", side_effect=self._boom
        ), mock.patch.object(er, "_google_factcheck", side_effect=self._boom):
            results = er.retrieve_evidence("anything", "en")
        self.assertEqual(results, [])

    def test_empty_claim_returns_empty_list(self):
        """A blank claim short-circuits to an empty list without calling sources."""
        self.assertEqual(er.retrieve_evidence("   ", "en"), [])


class RelevanceScoringTests(TestCase):
    """Lexical fallback scorer is bounded and sensible."""

    def test_lexical_relevance_bounds(self):
        """Identical text scores 1.0; disjoint text scores 0.0."""
        self.assertEqual(er._lexical_relevance("eiffel tower paris", "eiffel tower paris"), 1.0)
        self.assertEqual(er._lexical_relevance("eiffel tower", "banana smoothie"), 0.0)

    def test_relevance_without_model_uses_lexical(self):
        """With the embedder disabled, scoring falls back to lexical overlap in [0,1]."""
        with mock.patch.object(er, "_get_embedder", return_value=None):
            score = er._relevance("the eiffel tower in paris", "eiffel tower paris france")
        self.assertGreater(score, 0.0)
        self.assertLessEqual(score, 1.0)
