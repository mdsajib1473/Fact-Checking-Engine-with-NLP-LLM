# Fact-Checking Engine with NLP-AI

An AI-powered fact-checking system that extracts verifiable claims from text or
URLs, cross-references trusted sources, and returns a transparent, source-cited
verdict. See [AGENT.md](Agent.md) for the locked tech stack, rules, structure,
and database schema.

> **Phase status:** Phase 1 (Foundation) complete — Django + Neon + scaffold.
> No AI/NLP/LLM logic yet; those arrive in later phases.

## Tech stack (Phase 1)

- **Backend:** Django 5.2 + Django REST Framework
- **Database:** Neon (serverless Postgres) via `dj-database-url`, with pgvector
- **Frontend:** Django templates + Tailwind CSS (manual Tailwind CLI build)
- **Auth:** Django's built-in `django.contrib.auth`
- **Deployment:** Render.com (free tier) + WhiteNoise for static files

### Why manual Tailwind CLI (not django-tailwind)?

The locked project structure (AGENT.md Section 4) puts `package.json` and
`tailwind.config.js` at the repo root and outputs to
`factcheck/static/factcheck/css/tailwind_output.css`. The manual Tailwind CLI
matches this exactly, keeps Python dependencies lean, and avoids the extra
`theme` app that `django-tailwind` would introduce (which isn't in the locked
structure).

## Local setup

1. **Create a virtualenv and install dependencies**

   ```bash
   python -m venv venv
   venv/Scripts/python -m pip install -r requirements.txt   # Windows
   # source venv/bin/activate && pip install -r requirements.txt  # macOS/Linux
   ```

2. **Configure environment**

   ```bash
   cp .env.example .env
   ```

   Fill in `DJANGO_SECRET_KEY`. Leave `NEON_DATABASE_URL` blank to use local
   SQLite, or set it to your Neon connection string (must end with
   `?sslmode=require`) to use Neon.

3. **Build Tailwind CSS**

   ```bash
   npm install
   npm run build:css        # one-off build
   # npm run watch:css      # rebuild on change during development
   ```

4. **Run migrations and start the server**

   ```bash
   venv/Scripts/python manage.py migrate
   venv/Scripts/python manage.py runserver
   ```

## Neon + pgvector (required before migrating against Neon)

The `ClaimEmbedding` model uses a pgvector column. **Before running migrations
against a Neon database**, enable the extension once in the Neon SQL editor:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

This is intentionally **not** a Django migration so the local SQLite fallback
keeps working. Neon requires SSL — the connection string must include
`?sslmode=require` (enforced in `settings.py` via `ssl_require=True`).

## Deployment (Render)

`render.yaml` defines the web service. `build.sh` installs dependencies, builds
Tailwind CSS, runs `collectstatic`, and applies migrations. Set the secrets
(`NEON_DATABASE_URL`, `DJANGO_SECRET_KEY`, API keys, `DJANGO_ALLOWED_HOSTS`,
`DJANGO_CSRF_TRUSTED_ORIGINS`) as environment variables in the Render dashboard.

## Project layout

See [AGENT.md](Agent.md) Section 4 for the full, locked structure.
