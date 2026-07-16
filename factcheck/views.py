"""Views for the fact-checking app.

Views stay thin (AGENT.md Rule 7): they validate input, delegate to
``factcheck/services/``, and shape the response. No business logic lives here.
"""

import logging

import requests
from django.views.generic import TemplateView
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from .serializers import CheckUrlRequestSerializer, ExtractRequestSerializer
from .services import claim_service
from .services.language_service import detect_language

logger = logging.getLogger(__name__)


class HomeView(TemplateView):
    """Render the home page: the text/URL tab switcher (submits via fetch)."""

    template_name = "factcheck/home.html"


class ReportView(TemplateView):
    """Render the report shell; the claim cards are drawn client-side.

    The home page stores the pipeline JSON in ``sessionStorage`` and redirects
    here; ``report_interactions.js`` reads it and renders the claim-by-claim
    breakdown (verdict colors, evidence panels, simple-view toggle).
    """

    template_name = "factcheck/report.html"


class ExtractClaimsView(APIView):
    """POST ``/api/v1/extract/`` — full pipeline over pasted text.

    Accepts ``{"text": ..., "source_type": "text"}``, validates it (AGENT.md
    Rule 6), runs :func:`claim_service.process_text_input_with_evidence`
    (extract → persist → evidence → verdict), and returns each claim with its
    language, confidence, evidence, and verdict (label, confidence score,
    explanation, disclaimer — Rule 3). Invalid input yields 400.
    """

    def post(self, request):
        """Validate the request body, run the pipeline, and return the result JSON."""
        serializer = ExtractRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        text = serializer.validated_data["text"]
        source_type = serializer.validated_data["source_type"]

        claims = claim_service.process_text_input_with_evidence(text, source_type)
        return Response(
            {
                "claims": claims,
                "language": detect_language(text),
                "count": len(claims),
            },
            status=status.HTTP_200_OK,
        )


class CheckUrlView(APIView):
    """POST ``/api/v1/check-url/`` — full pipeline over a scraped page.

    Accepts ``{"url": ...}``, validates it, scrapes the page server-side
    (scheme check, timeout, content cap — Rules 6/12), then runs the same
    pipeline as the text endpoint with ``source_type="url"``. A page that can't
    be fetched or has no readable text yields 400 with a plain-language error
    (Rule 15 — the failure is reported, never silent).
    """

    def post(self, request):
        """Validate the URL, scrape it, run the pipeline, and return the JSON."""
        serializer = CheckUrlRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        url = serializer.validated_data["url"]
        try:
            claims = claim_service.process_url_input(url)
        except ValueError as exc:
            return Response({"url": [str(exc)]}, status=status.HTTP_400_BAD_REQUEST)
        except requests.exceptions.RequestException as exc:
            logger.warning("check-url: fetch failed for %s (%s)", url, exc)
            return Response(
                {"url": ["The page could not be fetched. Check the URL and try again."]},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Language is reported from the first claim (the scraped page text
        # itself is too long/noisy for a meaningful single detection).
        language = claims[0]["language"] if claims else detect_language(url)
        return Response(
            {"claims": claims, "language": language, "count": len(claims)},
            status=status.HTTP_200_OK,
        )
