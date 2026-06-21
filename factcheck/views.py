"""Views for the fact-checking app.

Views stay thin (AGENT.md Rule 7): they render templates and, in later phases,
delegate to ``factcheck/services/``. No business logic lives here.
"""

from django.views.generic import TemplateView


class HomeView(TemplateView):
    """Render the home page: the text/URL tab switcher shell.

    Phase 1 is visual scaffolding only — there is no submit handling yet.
    """

    template_name = "factcheck/home.html"
