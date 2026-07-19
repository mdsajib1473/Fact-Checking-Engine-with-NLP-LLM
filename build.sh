#!/usr/bin/env bash
# Render build script for the Fact-Checking Engine.
# Runs at deploy time: install deps, fetch NLP models, build Tailwind CSS,
# collect static, migrate.
set -o errexit

# 1. Python dependencies
pip install -r requirements.txt

# 2. NLP models (not in requirements.txt — see README "NLP model setup").
#    spaCy English pipeline for Pass-1 claim extraction (~12 MB).
python -m spacy download en_core_web_sm

#    Pre-download the sentence-transformers relevance model (~90 MB) into the
#    HuggingFace cache so the first live request doesn't pay the download.
#    Skipped when embedding relevance is disabled. The Bangla zero-shot
#    fallback model (mDeBERTa) is intentionally NOT fetched: it needs more RAM
#    than Render's free tier has, so ENABLE_HF_FALLBACK=0 in production.
if [ "${ENABLE_EMBEDDING_RELEVANCE:-1}" != "0" ]; then
  python - <<'PY'
from sentence_transformers import SentenceTransformer
import os
SentenceTransformer(os.environ.get("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2"))
print("embedding model cached")
PY
fi

# 3. Tailwind CSS build (Render's build image provides Node + npm).
#    A pre-built tailwind_output.css is also committed, so collectstatic still
#    has output even if this step is skipped.
npm ci
npm run build:css

# 4. Static files (WhiteNoise) + database schema
python manage.py collectstatic --no-input
python manage.py migrate
