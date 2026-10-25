# Failure branches (page 2; the one-page runbook stands alone without this)

Rule for every branch: stop at the failing step, fix or roll back that step only, re-prove the previous green state. Never push forward into the next wire-up step on a red test.

## Baseline (Step 1) failures
- **Mock scenes / spend `$--`:** "Use mock data" still ON. Turn it OFF, tap Reload. Empty screen right after the flip is expected; Reload fills it with real scenes.
- **Red error, HTTP 404:** double `/api/v1` in the base URL (app strips one, appends its own). Delete the whole field, retype bare `http://<Mac-LAN-IP>:8000`, Reload.
- **"Couldn't reach the backend":** phone on cellular or a different network, backend down, or wrong IP/port. Confirm the Mac server is running, confirm the phone is on the same venue Wi-Fi name as the Mac, re-verify the IP with `ipconfig getifaddr en0`, retype the bare URL, Reload. Do not keep retyping if the server itself is not reachable from the Mac.
- **401 unauthorized:** auth is on and the token is missing, mistyped, or typed with a `Bearer ` prefix (the app adds it). If auth is off on the Mac server and a 401 still appears, the phone is pointed at the wrong server; fix the URL, not the token.
- **Mock fallback lines in the server log** (`no GEMINI_API_KEY/GOOGLE_API_KEY`): the key was exported in the wrong window or after the server started. Stop the server with Ctrl-C in its window, re-export the key in that same window, restart, re-test Ask. Never paste the key into a file.
- **Port already in use:** `lsof -ti:8000 | xargs kill`, confirm `lsof -i:8000` prints nothing, restart. Do not switch ports; phone and lens assume 8000.
- **Counts look wrong:** judge by deltas from today's baseline, not by the fresh-seed 1.84 / 8 scenes. Each Ask adds $0.12 unless Argon returns an explicit cost; each chunk adds $0.07 (or $0.00 if skipped under Step 2). `SCENE_STORE=memory` or `postgres` in the server window means the wrong store; unset it and restart from `~/scene-backend`.

## Autodetect (Step 2) failures
- **Plug point does not match the running copy:** stop. Do not guess an edit location and do not import the repo backend's shape. Escalate; autodetect stays out.
- **A chunk crashes or disappears:** the guarded import / try-except failed. Roll back to the pre-Step-2 backup and restart; a detector exception must never reach the retry loop as a chunk failure.
- **Skipped chunk leaves a timeline gap or a wrong spend figure:** the minimal-scene builder or the `add_spend(0.00)` branch is wrong. Roll back; the analyze-everything path is the fallback.
- **Conversation wrongly skipped:** this is the costly failure (lost content beats $0.019 saved). Roll back and re-tune thresholds in `autodetect.py` only, off the demo path.

## Managed Agents (Step 3) failures
- **Dry-run / live verdicts disagree with the server:** stop; the disagreement is the bug. Do not demo past it.
- **SDK shape unconfirmed:** do not run it live and do not describe it as live. Demo the prompt + dry-run loop honestly.
- **An unverified item appears in the pending queue, or approving needs_review returns anything but 400:** the approval gate is broken. This is a stop condition. Roll back to the server path and re-run the 200 / 400 / 404 gate test.
- **401:** token expired or wrong; re-pair via the phone app. The client must not retry with a different token, and no token value goes in any log.

## Glasses + band (Step 4) failures
- **Dev Mode toggle will not stay ON:** stop and escalate. Do not proceed to registration.
- **Bridge shows no glasses:** check Meta AI was force-quit before the bridge, registration completed, and camera permission reads granted. Meta AI relaunched in the background is the first suspect.
- **State says streaming, preview says "No frame yet" after 10s:** not streaming. Stop, count to 3, retry (max 3 attempts), then the stuck-broadcast ladder. Never start recording on no frames; it makes empty 30s windows.
- **Band Back tap ends the session:** known firmware 129 behavior despite consumeBack. Use the non-Back path for that beat; never make Back the only navigation.
- **More than 30 minutes on glasses:** stop the track entirely. Fall back to seeded + chunk-upload demo.

## Dashboard / Cloud SQL (Steps 5-6) failures
- **Audit flags the backend files:** running backend stays untouched, whatever the dashboard decision is. A dashboard "yes" never justifies a backend restage.
- **Cloud cutover test fails at any point, or 6:30 PM arrives without end-to-end proof:** NO-GO. Point phone and lens back at the Mac LAN address, restart the Mac backend if needed, re-run Step 1. LAN + SQLite is the proven demo, not a degraded one.
