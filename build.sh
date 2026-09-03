#!/usr/bin/env bash
# Build step for the hosted demo. Render runs this on every deploy.
set -o errexit

pip install -r requirements.txt

# Collect static files for WhiteNoise to serve.
python manage.py collectstatic --no-input

# The free tier has an ephemeral disk, so the SQLite file is gone on every
# restart. Rebuilding it here is what keeps the demo populated - seed_demo is
# idempotent, so running it repeatedly is safe.
python manage.py migrate
python manage.py seed_demo
