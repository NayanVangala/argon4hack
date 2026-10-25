# Scene one-command startup (Mac side only)

## What it does

`start-scene.sh` starts everything the demo needs on the Mac, in one run:

1. Kills anything already on ports 8000 (backend) and 8001 (lens), so a stale server never blocks startup.
2. Starts the backend from `$HOME/scene-backend` (the working copy, NOT the repo `src/backend/`, which has unreviewed teammate changes on main). Backend log: `/tmp/scene-backend.log`.
3. Serves the lens page from the repo at `src/frontend/lens` on port 8001, bound to all interfaces so the phone can reach it over LAN. Lens log: `/tmp/scene-lens.log`.
4. Detects this Mac's LAN IP at runtime with `ipconfig getifaddr en0` (never hardcoded) and prints one clear block:
   - Mac checks use `http://localhost:8000/api/v1`
   - The phone app uses `http://<LAN IP>:8000` as its base URL (no `/api/v1` on the end)
   - The lens page is `http://<LAN IP>:8001/?api=http://<LAN IP>:8000`
5. Tails the backend log in the foreground, so request lines and Argon errors stay visible. Press Ctrl+C to stop both servers cleanly.

The backend needs `GEMINI_API_KEY`. The script reads it from the environment if set, otherwise prompts with hidden input. The key is never echoed, never written to any file, and never included in any log.

## The one command

From the repo root:

```bash
bash scripts/start-scene.sh
```

## Optional double-click path

`start-scene.command` is a Finder double-click wrapper for the same script. It needs one chmod first (macOS will not run it on double-click without the execute bit):

```bash
chmod +x start-scene.command
```

Then double-click it in Finder. The bash command above needs no chmod and is the primary path.

## What it does NOT do

This script covers the Mac side only. It does not:

- Tap anything on the phone (mock OFF, base URL, pull to refresh, Ask, follow-ups still happen in the app).
- Install the bridge app or pair the glasses (still happens on the demo phone).
- Pair the Neural Band or test gestures (still happens on the phone and glasses).
- Provision Cloud SQL or change any backend code (the backend runs from the working copy as-is).

## Troubleshooting

- Backend did not start: check `/tmp/scene-backend.log`. Common causes: a previous server still holding port 8000 (this script kills it first, but check the log), a missing key (the backend falls back to mocks, it does not crash), or a bad working copy at `$HOME/scene-backend`.
- Phone cannot reach backend: confirm the phone is on the same Wi-Fi as this Mac, and use the printed phone URL (`http://<LAN IP>:8000`), not localhost. Localhost on the phone means the phone itself, not your Mac.
- Lens page does not load on the phone: same Wi-Fi check, then use the printed lens URL. Check `/tmp/scene-lens.log`.
- LAN IP changed: just re-run the script. It detects the IP fresh every run, so the printed URLs are always current. Never hardcode an IP into the app.
- Stuck or stale servers: re-running the script kills anything on ports 8000 and 8001 first, then starts fresh.

## Note on the existing script

The repo already has `scripts/run-backend.sh` on main. The available repo clone did not include a `scripts/` directory, so that script could not be read during this build. `start-scene.sh` is a NEW file with a different name, so it does not conflict with or overwrite `run-backend.sh`. It intentionally runs the backend from `$HOME/scene-backend` (working copy), not from the repo backend.
