# AGENT.md — Fact-Checking Engine with NLP-AI


---

## 1. Project Overview

An AI-powered fact-checking system that accepts any text, URL, or social media post, extracts its verifiable factual claims, cross-references them against trusted knowledge sources, and returns a transparent, source-cited verdict (Supported / Disputed / False / Unverifiable). Built entirely on free-tier tools to remain zero-cost during development and early deployment.

---

## 2. Locked Tech Stack

| Layer | Choice |
|---|---|
| Backend | Django + Django REST Framework |
| Frontend | Django templates + Tailwind CSS + pure Tailwind (no component library) + vanilla JS where interactivity is needed |
| Database | Neon (serverless hosted Postgres, free tier — no project-count cap, unlike Supabase) |
| Auth | Django's built-in auth system (`django.contrib.auth`), since Neon doesn't bundle an auth layer |
| Vector storage | pgvector (Neon extension — enabled per-database via `CREATE EXTENSION vector;`) |
| NLP (claim extraction) | spaCy + HuggingFace transformers (both — spaCy for speed, HuggingFace as fallback for harder cases) |
| LLM (verdict reasoning) | Groq free tier (openai/gpt-oss-120b) |
| Evidence sources | Wikipedia API, Wikidata SPARQL, Google Fact Check Tools API |
| Async tasks | Django BackgroundTasks (no Celery/Redis — keep infra minimal) |
| Caching | Postgres table-based cache with TTL (no Redis) |
| Deployment | Render.com (free tier) |
| UI interaction | Tab switcher — paste text OR enter URL |
| Verdict display | Full report view — claim-by-claim breakdown with expandable evidence panels, plus a simple-view toggle for non-technical users |
| Theming | Dark mode supported (Tailwind `dark:` classes) |
| Language support | English + Bangla (বাংলা) from the start, auto-detected |

---

## 3. Rules

1. Never build beyond the current step.
2. Always respond in the same language the user typed (Bangla → Bangla).
3. Every verdict result MUST include the disclaimer:
   "This is an AI-generated assessment, not a final ruling on truth. Verify with the cited sources."
4. Don't Commit and push code (I wil do it manually after testing manual testing). (Ask if pushing is mandatory)
5. Write clean, well-commented code — every function and class must have a docstring.
6. Follow secure coding practices — never expose secrets, always use CSRF protection, validate and sanitize all user inputs before processing.
7. Write scalable code — keep business logic in services, keep views thin, never hardcode values that belong in settings or .env.
8. Do not over-comment — only comment where the code is not self-explanatory. Avoid stating the obvious (e.g. `# increment counter` above `i += 1`).
9. Never let the LLM output a verdict without at least one source citation attached — if no evidence is retrieved, the verdict must default to "Unverifiable", never "False" or "True".
10. Always show the user the raw evidence snippet and source link behind a verdict — no black-box scoring. Transparency is a core requirement, not a nice-to-have.
11. Respect free-tier API limits — implement caching (Postgres table) for every external API call (Groq, Google Fact Check, Wikipedia, Wikidata) so repeated claims don't burn quota. Always check cache before calling an external API.
12. Treat all scraped or user-submitted text as untrusted — never pass raw HTML or unsanitized scraped content directly into an LLM prompt; strip and clean it first.
13. Keep claim extraction, evidence retrieval, and verdict scoring as separate, independently testable service functions — never merge pipeline stages into one function, even for speed.
14. Log every verdict decision (claim, sources used, score, timestamp) to the database for auditability — fact-checking systems must be able to explain past decisions.
15. Never silently fail on a failed external API call — catch the error, fall back to the next available free source in priority order, and only return "Unverifiable" if all sources are exhausted.

---

## 4. Project Structure

```
fact-checking-engine/
├── manage.py
├── requirements.txt
├── .env.example
├── render.yaml
├── core/                      # Django project settings
│   ├── settings.py
│   ├── urls.py
│   └── wsgi.py
├── factcheck/                 # Main Django app
│   ├── models.py              # Claim, Verdict, Source, CacheEntry
│   ├── views.py                # thin views only
│   ├── urls.py
│   ├── serializers.py
│   ├── services/
│   │   ├── claim_extraction.py   # spaCy + HuggingFace pipeline
│   │   ├── evidence_retrieval.py # Wikipedia, Wikidata, Google Fact Check
│   │   ├── verdict_engine.py     # Groq LLM scoring logic
│   │   ├── cache_service.py      # Postgres cache read/write + TTL (Neon)
│   │   ├── language_service.py   # Bangla/English detection
│   │   └── scraper_service.py    # URL → clean text, sanitization
│   ├── templates/factcheck/
│   │   ├── base.html
│   │   ├── home.html              # tab switcher: text / URL input
│   │   └── report.html            # claim-by-claim verdict report
│   ├── static/factcheck/
│   │   ├── css/tailwind_output.css
│   │   └── js/report_interactions.js
│   └── tests/
├── tailwind.config.js
└── AGENT.md                   # this file — living document, updated each phase
```

---

## 5. Database Schema (Neon / Postgres)

**claims**
- id (uuid, pk)
- raw_text (text)
- extracted_claim (text)
- source_input_type (enum: text / url)
- source_url (text, nullable)
- language (enum: en / bn)
- created_at (timestamp)

**verdicts**
- id (uuid, pk)
- claim_id (fk → claims)
- label (enum: supported / disputed / false / unverifiable)
- confidence_score (integer, 0–10)
- explanation (text)
- created_at (timestamp)

**sources**
- id (uuid, pk)
- verdict_id (fk → verdicts)
- source_name (text)
- source_url (text)
- evidence_snippet (text)
- relevance_score (float)

**cache_entries**
- id (uuid, pk)
- cache_key (text, indexed, unique)
- api_name (text)
- response_payload (jsonb)
- expires_at (timestamp)

**claim_embeddings** (pgvector)
- id (uuid, pk)
- claim_id (fk → claims)
- embedding (vector)

---

## 6. Five-Phase Build Plan

### Phase 1 — Foundation: Django + Neon + Project Scaffold
Set up Django project, connect to Neon Postgres, define models and migrations, configure environment variables, set up Tailwind build pipeline, create base template with dark mode toggle and language switcher shell. No AI logic yet — pure scaffolding.

### Phase 2 — Claim Extraction Pipeline (NLP)
Build the `claim_extraction.py` service using spaCy for fast dependency-parse extraction, with HuggingFace transformers as a fallback for ambiguous cases. Output clean, searchable claim strings. Unit test against sample English and Bangla text.

### Phase 3 — Evidence Retrieval
Build `evidence_retrieval.py` integrating Wikipedia API, Wikidata SPARQL, and Google Fact Check Tools API, each wrapped with the Postgres-based cache (Neon) layer and TTL. Implement the fallback chain (rule 15) so a failed source doesn't break the pipeline.

### Phase 4 — Verdict Engine + UI
Build `verdict_engine.py` using the Groq free-tier LLM for chain-of-thought verdict reasoning with mandatory source citation (rule 9). Build the Tailwind UI: tab switcher (text/URL input), full report view with expandable evidence panels, simple-view toggle, dark mode, and Bangla/English rendering.

### Phase 5 — Security, Logging & Deployment
Harden CSRF protection, input sanitization, rate limiting via Django middleware, add the verdict audit log (rule 14), write final tests, and deploy to Render with environment variables configured securely.

---

## 7. Open Items / Notes
*(Update this section as decisions are made during development)*

**Phase 1 — Completed:** Django (`core`) + `factcheck` app scaffolded; 5 models with UUID PKs + initial migration; Neon wired via `dj-database-url` (SSL-required, SQLite local fallback); env-driven secrets via python-dotenv; Tailwind CLI pipeline (dark mode `class`); base/home templates with dark-mode toggle + language switcher shell; built-in auth URLs; Render `render.yaml` + `build.sh`. `check` passes, Tailwind + collectstatic verified, and migrations apply cleanly against the live Neon database (Postgres 18.4, pgvector 0.8.1) — all 5 tables created, `claim_embeddings.embedding` confirmed as a real `vector` column.

**Phase 2 — Completed:** Claim extraction pipeline (NLP). `language_service.detect_language()` (script-aware + langdetect) returns `en`/`bn`/`unknown`. `claim_extraction.extract_claims()` is the sole public entry point: sanitizes input (strips HTML/scripts, collapses whitespace — Rule 12), then runs **Pass 1** (spaCy `en_core_web_sm` dependency parse → per-clause SVO claims, splitting coordinated compound sentences, skipping questions/imperatives, scoring opinions/hedges low) and **Pass 2** (HuggingFace multilingual zero-shot fallback for Bangla / when spaCy is unavailable). Only claims at/above `settings.CLAIM_CONFIDENCE_THRESHOLD` (default 0.5, Rule 7) are returned. `claim_service.process_text_input()` is the thin orchestration layer that persists each claim to the `Claim` model (all DB writes live here, none in extraction — Rule 13). Dev testing harness `POST /api/v1/extract/` (validated 10–5000 chars, Rule 6) returns `{claims, language, count}`. 24 unit tests across language/extraction/service/API all pass; `manage.py check` clean.

**Phase 2 decisions / notes:**

- **No spaCy Bangla pipeline exists.** spaCy ships no pretrained Bangla model (there is no `bn_core_news_*`; only a rule-based `Bengali` language class with no parser/tagger). **Decision:** Bangla text routes entirely through the HuggingFace Pass-2 fallback rather than spaCy, exactly as Phase 2 anticipated. spaCy is English-only here.
- **HF fallback model:** `MoritzLaurer/mDeBERTa-v3-base-mnli-xnli` (multilingual, supports Bangla) used as a zero-shot classifier with labels `factual claim` / `opinion` / `question`; a sentence is kept only when its top label is `factual claim`.
- **Free-tier memory (Render 512 MB):** `torch` + a multilingual transformer + Django cannot coexist in 512 MB, so the model is **lazy-loaded** as a module-level singleton (loaded once on first use — never per request, never at Django startup, so boot stays fast) and `torch` is pinned to the **CPU-only build** (`torch==2.12.1+cpu` via the PyTorch CPU index). If the model cannot load (no transformers/torch, or out of memory), extraction **degrades gracefully** to a heuristic sentence pass instead of crashing, and the suite stays runnable offline. Set `ENABLE_HF_FALLBACK=0` to force heuristic-only. Models are **not** in `requirements.txt` — `en_core_web_sm` is a one-time `python -m spacy download`, and the HF model auto-downloads to `~/.cache/huggingface` on first use (documented in README → "NLP model setup").
- **English uses spaCy only** when it is loaded: an empty spaCy result is treated as a confident "no claims" (question/opinion), so the transformer never loads for ordinary English input (saving free-tier RAM); the fallback is reserved for Bangla and for when spaCy is unavailable.

**Phase 3 — Completed:** Evidence retrieval. `evidence_retrieval.retrieve_evidence(claim, lang)` is the sole public entry point: it queries three free sources **in parallel** via `concurrent.futures.ThreadPoolExecutor` — Wikipedia API, Wikidata SPARQL, and the Google Fact Check Tools API. Each source is independently wrapped in try/except so one failure never sinks the others, and if all return nothing the result is `[]` (Phase 4 maps that to "Unverifiable" — Rules 9/15). `cache_service` provides `get_cached_response` / `set_cached_response` over the `CacheEntry` table with a deterministic **SHA-256 key over the normalized (trimmed/lowercased/whitespace-collapsed) query**; every source checks the cache before any HTTP call and writes back on a miss, with per-source TTLs from settings (Rule 11/7). All retrieved text is HTML-stripped + whitespace-collapsed + length-capped before leaving the module (Rule 12); all HTTP calls use a 10s timeout and a descriptive `User-Agent` (both from settings). `scraper_service.scrape_url()` fetches a URL with requests + BeautifulSoup (lxml), strips scripts/styles/nav/footer, rejects non-http(s) schemes, and caps content at 50 000 chars (exists + tested, not yet UI-wired — Phase 4). Each evidence dict is `{source_name, source_url, evidence_snippet, relevance_score}`. `claim_service` gained `gather_evidence()` (saves each evidence dict to the `Source` model with `verdict=None`) and `process_text_input_with_evidence()` (orchestrates extract→persist→retrieve); **all DB writes stay in `claim_service`, none in `evidence_retrieval`** (Rule 13). `POST /api/v1/extract/` now returns `evidence` + `confidence` per claim. 18 new unit tests (cache/evidence/scraper) added — **47 total pass**, `manage.py check` clean. Manually verified against live APIs + Neon: Eiffel/Marie-Curie return Wikipedia + Wikidata evidence with cosine relevance scores; a Bangla claim hits `bn.wikipedia.org` first; "The Earth is flat" returns Google fact-checks.

**Phase 3 decisions / notes:**

- **`Source.verdict` made nullable** (`null=True, blank=True`, migration `0002_alter_source_verdict`). Phase 3 retrieves and persists evidence *before* any verdict exists; rows are saved with `verdict=None` and linked during Phase 4 scoring. No `claim_id` was added to `sources` — the locked schema (Section 5) keys evidence off `verdict_id` only, so Phase-3 `Source` rows are intentionally unlinked until Phase 4; the endpoint returns per-claim evidence from the in-memory retrieval result, not from a `Source`↔`Claim` join.
- **Relevance scoring** = cosine similarity between claim and snippet embeddings via **`sentence-transformers/all-MiniLM-L6-v2`** (added to `requirements.txt`; the task's "already installed" was inaccurate — it was installed this phase). Lazy-loaded singleton like the Phase 2 NLP models; if it can't load it **degrades to a lexical Jaccard token-overlap score** rather than crashing (`ENABLE_EMBEDDING_RELEVANCE=0` forces lexical). Results are sorted by descending relevance.
- **Wikidata entity resolution.** `wbsearchentities` matches entity *labels*, not full sentences, so a raw claim almost never resolves. A light, dependency-free heuristic (`_main_entity_query`) takes the first capitalized proper-noun span (the SVO subject, e.g. "Eiffel Tower", "Marie Curie"), article-stripped, as the search term; Bangla (no capitalization) falls back to the full claim. The SPARQL itself is the simple label + description lookup the phase called for. Wikipedia keeps using the full claim (its full-text search handles sentences well).
- **Bangla Wikipedia** is queried first for `lang="bn"` claims (`bn.wikipedia.org`), falling back to the English edition on an empty result (the Rule 15 chain, applied within the source).
- **SQLite + parallel writes.** The local SQLite fallback now sets `OPTIONS={"timeout": 20}` so parallel cache writes from the ThreadPool wait for the lock instead of erroring ("database is locked"). The in-memory test DB still logs locks under heavy thread contention, but they're caught (Rule 15) and harmless — production runs on Neon/Postgres, which handles concurrency natively. New settings (`requirements.txt` adds `beautifulsoup4`, `lxml`, `sentence-transformers`).

**Phase 4 — Completed:** Verdict engine + UI. `verdict_engine.generate_verdict(claim, evidence, lang)` is the sole public entry point: sends claim + numbered evidence to the **Groq chat-completions API (`openai/gpt-oss-120b` — `llama-3.3-70b-versatile` is deprecated)** with a chain-of-thought judge prompt and a strict JSON output contract, then parses/validates the reply (label whitelist, confidence clamped 0–10). **Empty evidence short-circuits to UNVERIFIABLE without any LLM call** (Rule 9 + saves quota); the prompt additionally forbids outside knowledge and mandates UNVERIFIABLE when evidence is off-point. Every failure path (missing key, timeout, rate limit, malformed reply) returns the UNVERIFIABLE fallback — never a crash (Rule 15). The exact Rule 3 disclaimer is appended to every verdict, with a Bangla translation for `bn` claims (never mixed). `claim_service.score_claim()` persists the `Verdict` row (label stored lowercase per model choices) and links the Phase-3 `Source` rows to it (`verdict_id` updated from NULL); Verdict+Source rows with `created_at` form the Rule 14 audit trail. `POST /api/v1/extract/` now returns `verdict` per claim; new `POST /api/v1/check-url/` scrapes a page (Phase 3 `scrape_url`) and runs the same pipeline with `source_type="url"` + `source_url` recorded. **UI:** home tab switcher wired (vanilla `fetch`, client-side validation mirroring API bounds, CSRF header, loading spinner); report page renders client-side from `sessionStorage` (`report_interactions.js`) — color-coded verdict badges (green/yellow/red/gray), confidence bar, explanation, always-visible disclaimer, expandable per-claim evidence panels (`<details>`) with clickable source links + relevance scores (Rule 10), simple-view toggle (hides explanation+evidence only), dark mode works, all DOM built via `textContent` (no innerHTML injection). Language switcher now functional: a small per-language string dictionary in `base.html` (`data-i18n` attributes + `window.FC_I18N`), EN/বাংলা, chrome-only (content keeps its detected language). 15 new tests (9 verdict engine, all Groq HTTP mocked; 6 API integration/URL) — **62 total pass** via `manage.py test factcheck.tests --settings=core.settings_test`; `manage.py check` clean. Manually verified in the browser: English paragraph → 2 SUPPORTED claims (10/10, 9/10) with evidence panels; Bangla claim → Bangla explanation + exact Bangla disclaimer + `bn.wikipedia.org` evidence + Bangla chrome; dark mode and simple view both correct.

**Phase 4 decisions / notes:**

- **Groq via plain `requests`** against the OpenAI-compatible `chat/completions` endpoint — no new SDK dependency. `temperature=0`, `response_format={"type":"json_object"}`, model/key/URL/timeout/max-tokens all from settings (`GROQ_MODEL=openai/gpt-oss-120b`, `GROQ_TIMEOUT_SECONDS=30`).
- **UI i18n = tiny dictionary, not Django i18n.** Full `gettext` machinery (locale files, compilation, middleware) is meaningfully more work for ~30 chrome strings rendered client-side; a JS dict in `base.html` with `data-i18n` keys does the job and re-renders the report cards on switch (`fc:lang` event). Revisit only if UI strings multiply.
- **Report data flow:** the API response is stored in `sessionStorage` and rendered client-side on `/report/` — no server-side report persistence needed this phase (report-by-id permalinks can come later if wanted).
- **URL submissions are truncated to `EXTRACT_INPUT_MAX_CHARS`** (5000) after scraping so one long article can't fan out into dozens of Groq calls (free-tier limits).
- **`core/settings_test.py`** (user-created after Phase 3) now also blanks `GROQ_API_KEY` so the automated suite can never hit the live LLM; engine tests mock `requests.post` and override the key.
- **Observed:** the zero-shot Bangla extractor is conservative — "আইফেল টাওয়ার ফ্রান্সের রাজধানী প্যারিসে অবস্থিত।" scored below the claim threshold and produced an empty (graceful) report, while "ঢাকা বাংলাদেশের রাজধানী।" passed and verified end-to-end. Phase 2 tuning question, out of Phase 4 scope.
- Browser verification wrote a handful of Eiffel/Curie/ঢাকা rows (claims/verdicts/sources) to Neon — left in place, same as the Phase 3 test rows.

- [x] Confirm Neon Postgres project created and connection string added to `.env`
      *(Connected to Neon Postgres 18.4; `migrate` applied cleanly.)*
- [x] Confirm `pgvector` extension enabled on the Neon database (`CREATE EXTENSION vector;`)
      *(Enabled on Neon, version 0.8.1. Kept out of migrations so the local SQLite fallback still works.)*
- [x] Confirm Google Fact Check Tools API key obtained and added to `.env`
- [x] Confirm Groq API key obtained and added to `.env`
- [ ] Decide on rate-limit thresholds per IP (placeholder: 10 requests/hour for unauthenticated users) *(Phase 5)*
- [x] Decide on Bangla NLP model specifics if spaCy's Bangla support proves insufficient *(Phase 2)*
      *(No pretrained spaCy Bangla pipeline exists; Bangla routes through the HuggingFace `mDeBERTa-v3-base-mnli-xnli` zero-shot fallback. See "Phase 2 decisions" above.)*