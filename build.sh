#!/usr/bin/env bash
# Render build script for the Fact-Checking Engine.
# Runs at deploy time: install deps, build Tailwind CSS, collect static, migrate.
set -o errexit

# 1. Python dependencies
pip install -r requirements.txt

# 2. Tailwind CSS build (Render's build image provides Node + npm).
#    A pre-built tailwind_output.css is also committed, so collectstatic still
#    has output even if this step is skipped.
npm ci
npm run build:css

# 3. Static files (WhiteNoise) + database schema
python manage.py collectstatic --no-input
python manage.py migrate
