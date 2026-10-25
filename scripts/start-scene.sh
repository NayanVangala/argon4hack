#!/bin/bash
# start-scene.sh - One-command startup for the Scene hackathon demo (Mac side).
#
# Run from the repo root:
#   bash scripts/start-scene.sh
# Or double-click start-scene.command (same folder as this script, or repo root).
#
# What it does:
#   1. Kills anything already on ports 8000 (backend) and 8001 (lens).
#   2. Starts the backend from $HOME/scene-backend (the working copy, NOT the
#      repo src/backend/, which has unreviewed teammate changes on main).
#   3. Serves the lens page from the repo at src/frontend/lens on port 8001.
#   4. Detects this Mac's LAN IP at runtime and prints the exact URLs:
#      Mac checks use localhost, the phone app uses the LAN IP.
#   5. Tails the backend log in the foreground so request lines and Argon
#      errors stay visible. Press Ctrl+C to stop everything cleanly.
#
# The backend needs GEMINI_API_KEY. It is read from the environment if set,
# otherwise you are prompted with hidden input. The key is never echoed,
# never written to any file, and never included in any log.
#
# This script contains no API key, no hardcoded LAN IP, and no hardcoded
# username. The backend path uses $HOME. The lens path resolves from this
# script's own location.

# Resolve the repo root from this script's location.
# If this script lives in scripts/, the repo root is its parent.
# If it lives at the repo root, the repo root is its own directory.
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
if [ -d "$SCRIPT_DIR/src/frontend/lens" ]; then
  REPO_ROOT="$SCRIPT_DIR"
elif [ -d "$SCRIPT_DIR/../src/frontend/lens" ]; then
  REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
else
  echo "WARNING: could not find src/frontend/lens under $SCRIPT_DIR or its parent."
  echo "The backend will still start, but the lens server will be skipped."
  echo "Check that this script lives in the repo (scripts/ or repo root)."
  REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
fi

BACKEND_DIR="$HOME/scene-backend"
LENS_DIR="$REPO_ROOT/src/frontend/lens"
BACKEND_LOG="/tmp/scene-backend.log"
LENS_LOG="/tmp/scene-lens.log"

BACKEND_PID=""
LENS_PID=""
CLEANED=0

cleanup() {
  if [ "$CLEANED" = "1" ]; then
    return
  fi
  CLEANED=1
  echo ""
  echo "Stopping Scene servers..."
  for pid in $BACKEND_PID $LENS_PID; do
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
    fi
  done
  sleep 1
  for pid in $BACKEND_PID $LENS_PID; do
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
      kill -9 "$pid" 2>/dev/null || true
    fi
  done
  echo "Stopped."
}
trap cleanup INT TERM EXIT

# Sanity checks.
if ! command -v python3 >/dev/null 2>&1; then
  echo "ERROR: python3 not found. Install Python 3, then run this script again."
  exit 1
fi
if [ ! -f "$BACKEND_DIR/server.py" ]; then
  echo "ERROR: backend not found at $BACKEND_DIR/server.py"
  echo "This script runs the working copy at \$HOME/scene-backend, not the repo backend."
  exit 1
fi

# 1. Free ports 8000 and 8001 so a stale server never blocks startup.
echo "Freeing ports 8000 and 8001..."
if command -v lsof >/dev/null 2>&1; then
  lsof -ti:8000 | xargs kill 2>/dev/null || true
  lsof -ti:8001 | xargs kill 2>/dev/null || true
  sleep 1
else
  echo "WARNING: lsof not found, skipping port cleanup. If a server is already"
  echo "running on port 8000 or 8001, this script may fail to bind."
fi

# 2. Backend key: environment first, else hidden prompt. Never echoed, never stored.
if [ -z "${GEMINI_API_KEY:-}" ]; then
  printf "GEMINI_API_KEY is not set. Paste your key (input hidden): "
  read -r -s GEMINI_API_KEY
  echo ""
  if [ -z "$GEMINI_API_KEY" ]; then
    echo "WARNING: no key entered. The backend will start, but Argon calls will"
    echo "fall back to mocks. Restart with a key for live Argon answers."
  fi
  export GEMINI_API_KEY
else
  export GEMINI_API_KEY
fi

# 3. Start the backend from the working copy. Log goes to /tmp, never the repo.
echo "Starting backend from $BACKEND_DIR (port 8000)..."
(cd "$BACKEND_DIR" && python3 server.py > "$BACKEND_LOG" 2>&1) &
BACKEND_PID=$!

# 4. Start the lens server, bound to all interfaces so the phone can reach it.
if [ -d "$LENS_DIR" ]; then
  echo "Starting lens server from $LENS_DIR (port 8001)..."
  (cd "$LENS_DIR" && python3 -m http.server 8001 --bind 0.0.0.0 > "$LENS_LOG" 2>&1) &
  LENS_PID=$!
else
  echo "WARNING: lens directory not found at $LENS_DIR, skipping lens server."
fi

# 5. Detect this Mac's LAN IP at runtime. Never hardcoded.
LAN_IP="$(ipconfig getifaddr en0 2>/dev/null || true)"
if [ -z "$LAN_IP" ]; then
  echo "WARNING: could not detect LAN IP with: ipconfig getifaddr en0"
  echo "The backend still runs on localhost, but the phone URLs below cannot"
  echo "be printed. Check Wi-Fi, then run: ipconfig getifaddr en0"
fi

# 6. Wait briefly, then check backend health. Warn, do not crash, on failure.
sleep 2
if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
  echo "WARNING: backend process exited quickly. See $BACKEND_LOG for the error."
elif command -v curl >/dev/null 2>&1; then
  STATUS="$(curl -s http://localhost:8000/api/v1/status || true)"
  if [ -n "$STATUS" ]; then
    echo "Backend health check OK:"
    echo "$STATUS"
  else
    echo "WARNING: backend health check failed (no response on localhost:8000)."
    echo "See $BACKEND_LOG for details. The script keeps running so you can read it."
  fi
else
  echo "WARNING: curl not found, skipping backend health check."
  echo "Check $BACKEND_LOG to confirm the backend started."
fi

# 7. Print one clear block. No guessing between localhost and LAN IP.
echo ""
echo "================ Scene is up ================"
echo "Mac backend:   http://localhost:8000/api/v1"
if [ -n "$LAN_IP" ]; then
  echo "Phone app:     http://$LAN_IP:8000"
  echo "               (enter this as base URL in the app, no /api/v1 on the end)"
  echo "Lens page:     http://$LAN_IP:8001/?api=http://$LAN_IP:8000"
else
  echo "Phone app:     (LAN IP unknown, see warning above)"
  echo "               Run: ipconfig getifaddr en0"
  echo "               Then use: http://<that IP>:8000 as the app base URL"
  echo "Lens page:     (LAN IP unknown, see warning above)"
fi
echo "Backend log:   $BACKEND_LOG"
echo "Lens log:      $LENS_LOG"
echo "Phone must be on the same Wi-Fi as this Mac."
echo "Press Ctrl+C to stop everything."
echo "============================================="
echo ""

# 8. Stay in the foreground tailing the backend log, so request lines and
#    Argon errors stay visible. Ctrl+C triggers cleanup via the trap.
tail -f "$BACKEND_LOG"
