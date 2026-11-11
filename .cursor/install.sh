#!/usr/bin/env bash
# Cloud Agent install script for the Shepherd's Guild sermon pipeline.
# Idempotent: safe to re-run; already-satisfied packages are left untouched.
set -euo pipefail

cd "$(dirname "$0")/.."

# --- Python: pipeline runtime + page renderer + test suite ---------------
# requirements.txt declares only the core API clients. The pipeline, the
# sermon_page_renderer, and the helper scripts also import jinja2, bs4,
# requests, openpyxl and pdfplumber, and the tests need pytest. Install the
# full set so the code and tests actually run.
python3 -m pip install --user \
  -r requirements.txt \
  jinja2 \
  beautifulsoup4 \
  requests \
  openpyxl \
  pdfplumber \
  lxml \
  pytest

# --- corpus-mcp: Cloudflare Worker (MCP server) --------------------------
# npm ci installs the pinned dependencies used by `npm run typecheck` and
# `npm run dev`.
( cd corpus-mcp && npm ci )

echo "Install complete."
