#!/bin/bash
# make-chunk.sh - Generate a 30 second synthetic test clip for the
# Scene chunk-upload test.
#
# Outputs (in OUTDIR, default: current directory):
#   chunk-test.mp4  - testsrc2 video, 640x360, 30 fps, 30 s, no audio
#   chunk-test.wav  - 440 Hz sine tone, 16 kHz mono, 30 s
#
# These match what POST /api/v1/chunks expects: the route writes the
# "video" part to a temp file with a .mp4 suffix and the "audio" part
# to a temp file with a .wav suffix (app/routes.py, _handle_chunks).
# The route does NOT validate codecs, so any readable mp4/wav works;
# mp4 + wav are simply the shapes the route assumes.
#
# Usage:
#   ./make-chunk.sh [outdir]
#
# Requires ffmpeg + ffprobe. If either is missing, this script prints
# install instructions and stops (exit 1) instead of failing silently.
set -eu

OUTDIR="${1:-.}"
VIDEO="$OUTDIR/chunk-test.mp4"
AUDIO="$OUTDIR/chunk-test.wav"

if ! command -v ffmpeg >/dev/null 2>&1 || ! command -v ffprobe >/dev/null 2>&1; then
  cat >&2 <<'EOF'
ffmpeg and/or ffprobe not found on PATH. Install ffmpeg (ffprobe ships with it), then re-run this script.

  macOS (Homebrew):
    brew install ffmpeg

  Ubuntu / Debian:
    sudo apt update && sudo apt install ffmpeg

  Then verify with:
    ffmpeg -version && ffprobe -version
EOF
  exit 1
fi

mkdir -p "$OUTDIR"

echo "Generating 30 s test video: $VIDEO"
ffmpeg -y -v error \
  -f lavfi -i "testsrc2=size=640x360:rate=30:duration=30" \
  -an -c:v libx264 -pix_fmt yuv420p "$VIDEO"

echo "Generating 30 s test audio (440 Hz tone): $AUDIO"
ffmpeg -y -v error \
  -f lavfi -i "sine=frequency=440:sample_rate=16000:duration=30" \
  -ac 1 "$AUDIO"

# --- ffprobe duration check (both files must be ~30 s) -------------------
check_duration() {
  local file="$1"
  local dur
  dur="$(ffprobe -v error -show_entries format=duration \
    -of default=noprint_wrappers=1:nokey=1 "$file")"
  echo "$file duration: ${dur}s"
  # Accept 29.5-30.5 s; anything else means the generation went wrong.
  if ! awk -v d="$dur" 'BEGIN { exit !(d >= 29.5 && d <= 30.5) }'; then
    echo "ERROR: $file is not ~30 s (got ${dur}s). Delete it and re-run." >&2
    exit 1
  fi
}

check_duration "$VIDEO"
check_duration "$AUDIO"

echo "OK: $VIDEO and $AUDIO are both ~30 s. Upload with ./upload-chunk.sh"
