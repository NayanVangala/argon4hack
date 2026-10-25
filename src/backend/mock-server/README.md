# Scene mock API server

Mock for the Scene hackathon backend. Serves `SCENE-API-CONTRACT.md`
field-for-field with canned data so the phone app, dashboard, and lens teams
build without waiting for the real pipeline. Python stdlib only, no install.

## Run

```bash
python3 server.py
```

Listens on `:8000`. Override with `PORT`:

```bash
PORT=9000 python3 server.py
```

- REST base: `http://localhost:8000/api/v1`
- WS live: `ws://localhost:8000/api/v1/live`

## Endpoints (all under `/api/v1`)

| Method | Route | Notes |
|---|---|---|
| POST | `/sessions` | 201, starts a live session |
| POST | `/sessions/{id}/end` | 200, ends it, returns scene count |
| POST | `/chunks` | 202, multipart video+audio accepted; also indexes one mock scene and broadcasts it over WS |
| GET | `/status` | recording flag, session id, scene count, last scene ts, `spend_usd` |
| GET | `/scenes/today?limit=50&before=<id>` | newest first, paginated via `next_before` |
| GET | `/scenes/{id}` | full detail incl. `critique` array |
| POST | `/ask` | keyword match: query containing "promise" returns the Maya Q3 receipt; anything else returns `"I don't have a record of that."` with empty receipts |
| POST | `/pin` | 201; `scene_id` optional (pins latest scene), `note` optional |
| GET | `/people` | Maya + Unknown |
| POST | `/people` | 201, multipart photo+voice accepted, adds an enrolled speaker |
| GET | `/facts?actor=Maya&limit=20` | 3 canned facts |
| POST | `/followups/generate` | 202, creates a run with 2 pending verified drafts + 1 `needs_review` draft |
| GET | `/followups?run_id=&status=` | filterable drafts |
| POST | `/followups/{id}/approve` | 200; approving a `needs_review` draft returns 400 (never approvable) |
| POST | `/followups/{id}/dismiss` | 200 |
| WS | `/live` | scene/status/error pushes; client `{"event":"ping"}` gets `{"event":"pong"}` |

Errors use the contract envelope: `{"error": {"code": "...", "message": "..."}}`.
Unknown scenes, follow-ups, and routes return 404 with that envelope.

## Canned data

8 scenes across 2 people (Maya, Unknown), 3 facts, 1 pinned scene (the Q3
numbers promise). One scene carries a failing `visual_grounding` critique so
clients can exercise the fail path.

## Mock behavior to know about

- **Auth is not enforced.** Any or no Bearer token is accepted.
- **CORS is wide open** (`*`) so browser clients on any origin can call it.
- **Spend ticker:** `spend_usd` starts at 1.84, +0.07 per chunk, +0.12 per ask.
- **Live pushes:** a background thread sends one synthetic scene + status
  event over WS every 30s, but only while a WS client is connected.
- **No persistence.** Restarting the server resets everything to the seed data.
