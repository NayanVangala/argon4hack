#!/bin/bash
# upload-chunk.sh - POST a video + audio chunk to the Scene backend.
#
# Usage:
#   BASE_URL=http://localhost:8000 ./upload-chunk.sh [video] [audio]
#
# Defaults:
#   video   chunk-test.mp4   (the "video" multipart field)
#   audio   chunk-test.wav   (the "audio" multipart field)
#   BASE_URL http://localhost:8000
#
# LAN use: set BASE_URL to the Mac's LAN address, e.g.
#   BASE_URL=http://10.1.63.33:8000 ./upload-chunk.sh
#
# Auth: the server only enforces a token when it was started with
# AUTH_ENABLED=1. In that case set SCENE_API_TOKEN to the same token
# the server was started with and this script sends it as
# "Authorization: Bearer <token>". NEVER put a real token in this
# file; pass it via the environment only. When auth is off, the
# header is harmless (the server ignores it).
#
# Optional fields (all optional on the server):
#   SESSION_ID  - sent as the "session_id" form field. If omitted, the
#                 server uses the live session, else its current
#                 session id (app/routes.py, _handle_chunks).
#   START_TS / END_TS - sent as "start_ts" / "end_ts". If omitted,
#                 this script generates now and now+30 s (UTC, ISO
#                 8601) via python3. If python3 is also missing, the
#                 fields are omitted and the server defaults
#                 start_ts to now and end_ts to start_ts (a zero-length
#                 window, which does NOT block the upload).
#
# Success is HTTP 202 with a JSON body like:
#   {"chunk_id": "...", "session_id": "...",
#    "start_ts": "...", "end_ts": "...", "status": "received"}
# Anything else exits non-zero.
set -eu

BASE_URL="${BASE_URL:-http://localhost:8000}"
VIDEO="${1:-chunk-test.mp4}"
AUDIO="${2:-chunk-test.wav}"

for f in "$VIDEO" "$AUDIO"; do
  if [ ! -f "$f" ]; then
    echo "ERROR: file not found: $f" >&2
    echo "Generate it first with ./make-chunk.sh (or see README.md phone fallback)." >&2
    exit 1
  fi
done

# Build the curl arguments.
CURL_ARGS=(-s -F "video=@$VIDEO" -F "audio=@$AUDIO")

if [ -n "${SESSION_ID:-}" ]; then
  CURL_ARGS+=(-F "session_id=$SESSION_ID")
fi

if [ -n "${START_TS:-}" ] && [ -n "${END_TS:-}" ]; then
  CURL_ARGS+=(-F "start_ts=$START_TS" -F "end_ts=$END_TS")
elif command -v python3 >/dev/null 2>&1; then
  read -r START_TS END_TS <<EOF
$(python3 -c 'from datetime import datetime, timezone, timedelta; now = datetime.now(timezone.utc); print(now.isoformat(timespec="seconds"), (now + timedelta(seconds=30)).isoformat(timespec="seconds"))')
EOF
  CURL_ARGS+=(-F "start_ts=$START_TS" -F "end_ts=$END_TS")
else
  echo "NOTE: python3 not found; omitting start_ts/end_ts (server defaults apply)." >&2
fi

if [ -n "${SCENE_API_TOKEN:-}" ]; then
  CURL_ARGS+=(-H "Authorization: Bearer $SCENE_API_TOKEN")
fi

echo "POST $BASE_URL/api/v1/chunks"
echo "  video=$VIDEO audio=$AUDIO"
RESPONSE="$(curl -w "\n%{http_code}" "${CURL_ARGS[@]}" "$BASE_URL/api/v1/chunks")"
CODE="${RESPONSE##*$'\n'}"
BODY="${RESPONSE%$'\n'*}"
echo "$BODY"
echo "HTTP status: $CODE"

if [ "$CODE" != "202" ]; then
  echo "ERROR: expected HTTP 202. See README.md failure branches." >&2
  exit 1
fi
echo "OK: chunk accepted (status received)."
