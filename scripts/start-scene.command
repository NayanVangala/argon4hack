#!/bin/bash
# start-scene.command - Double-click starter for the Scene demo (Finder).
#
# NOTE: macOS requires one chmod +x on this file first before double-click works:
#   chmod +x start-scene.command
# The bash path (bash scripts/start-scene.sh) needs no chmod and is the primary path.
#
# This wrapper cds to its own directory and runs start-scene.sh with bash.
# It works whether it sits next to start-scene.sh (in scripts/) or at the
# repo root (with start-scene.sh in scripts/).

cd "$(dirname "$0")"
if [ -f ./start-scene.sh ]; then
  exec bash ./start-scene.sh
elif [ -f ./scripts/start-scene.sh ]; then
  exec bash ./scripts/start-scene.sh
else
  echo "ERROR: start-scene.sh not found next to this file or in scripts/."
  echo "Put this file in scripts/ next to start-scene.sh, or at the repo root."
  echo "Press Enter to close this window."
  read -r
fi
