#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
  echo "→ Erstelle virtuelle Umgebung (.venv)…"
  python3 -m venv .venv
fi

source .venv/bin/activate

# Installiere Abhängigkeiten neu, wenn requirements.txt neuer ist als unser Marker.
if [ ! -f ".venv/.deps_installed" ] || [ "requirements.txt" -nt ".venv/.deps_installed" ]; then
  echo "→ Installiere Abhängigkeiten…"
  pip install --upgrade pip >/dev/null
  pip install -r requirements.txt
  touch .venv/.deps_installed
fi

if [ ! -f ".env" ] && [ -f ".env.example" ]; then
  echo "→ Lege .env aus .env.example an"
  cp .env.example .env
fi

exec python -m murml
