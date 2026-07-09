#!/usr/bin/env bash
# ownchatbot — macOS / Linux launcher. First run sets up a venv + installs deps.
set -e
cd "$(dirname "$0")"
PY="$(command -v python3 || command -v python)"
[ -d .venv ] || "$PY" -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install -q --upgrade pip
python -m pip install -q -r requirements.txt
[ -f .env ] || { [ -f .env.example ] && cp .env.example .env && echo "Created .env (optional: add an LLM key)"; }
echo ""
echo "  ✅ ownchatbot running →  http://localhost:8200   (admin)"
echo "                          http://localhost:8200/demo (test the widget)"
echo "  Press Ctrl+C to stop."
echo ""
exec python -m uvicorn ownchatbot.server:app --host 127.0.0.1 --port 8200
