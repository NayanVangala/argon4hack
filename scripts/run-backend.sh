#!/bin/bash
# Run the Scene backend from this repo (SQLite default, port 8000).
# Live Argon needs GEMINI_API_KEY exported in this terminal; without
# it the backend degrades to mocks with a clear log line.
# Run with: bash scripts/run-backend.sh
set -e
cd "$(dirname "$0")/../src/backend"
exec python3 server.py
