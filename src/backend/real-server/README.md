# Scene real demo backend

Built on October 25, 2026. This is a separate implementation from `../mock-server`; it does not replace that server or change the iPhone/bridge source files.

## What works

- An authenticated FastAPI API and a browser demo at `/`.
- SQLite persistence for sessions, transcripts, extracted scenes, people profiles, speaker mappings, follow-ups and to-dos.
- Real `gemini-4-argon` calls for media transcription, visible text observations, task extraction and evidence selection for questions.
- Transcript-only input for testing, and MP4/WebM/WAV/MP3 upload (15 MB combined). Media bytes are transient and are not retained as downloadable recordings.
- Human-confirmed, **chunk-specific** speaker labels. No claim of voice or face recognition.
- Session-wide reconciliation when multiple chunks contain later corrections.
- Every action requires explicit review. Approval either saves a server-side to-do, produces a Gmail compose URL, or produces a Google Calendar event form URL.
- Idempotent approval, media-upload retry deduplication, bounded provider concurrency, safe failure states, authenticated WebSocket events and a full data purge endpoint.

## Important boundaries

This is a single-user hackathon server, not a production multi-tenant service. One token grants access to the whole database. Run only one instance and one worker.

- A prepared Gmail URL is **not** an email sent or a Gmail draft saved by API. The user opens it and clicks Send.
- A prepared Calendar URL is **not** an event already created. The user opens it and clicks Save. No attendees are invited automatically.
- Calendly booking, Google OAuth/API writes and autonomous email delivery are **not implemented**.
- There is no biometric wearer identification or voice enrollment. Unknown speakers remain unknown until a person maps them. Mapping one chunk does not identify a voice in another chunk.
- `quote_verified` means only that the quoted text occurs in a saved transcript. It does not verify the recording's truth, speaker identity, or model-derived deadline. `physical_truth_verified` is always false. Facts are model interpretations linked to transcript evidence.
- Visual text is a model observation, not independently verified. Visual-only notes cannot create automatically approvable tasks.
- Uploads made through the browser use the current session date unless the caller supplies the true recording timestamps. Relative dates depend on that timestamp and the session timezone.
- The background queue is in-process, not durable. On restart, interrupted jobs become failed; submit again. No automatic paid model retries.
- API spend is **not measured**; `spend_usd` is null rather than a fake number.
- Recent in-flight model calls cannot be recalled from Google's servers by deleting local data. The local purge prevents their results being written back.

## Start locally

Python 3.11 to 3.13 is supported by these pinned dependencies. Prefer Python 3.13 (also used by Docker).

```sh
cd src/backend/real-server
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export GEMINI_API_KEY='YOUR_KEY'  # set privately; do not commit it
export SCENE_ALLOW_LOCAL_NO_AUTH=1
uvicorn app:app --host 127.0.0.1 --port 8000 --workers 1 --loop asyncio --http h11 --no-access-log
```

Open `http://127.0.0.1:8000`. Start a session, paste a labelled transcript or upload a consensual recording, confirm speaker labels, then generate and review actions.

If macOS blocks an optional compiled Pydantic module, **do not disable Gatekeeper or remove quarantine globally**. This code uses Pydantic v1, which includes a pure-Python implementation. A source-only install can be built with `SKIP_CYTHON=1 pip install --no-binary=pydantic --force-reinstall pydantic==1.10.24`. The local build was tested with the bundled pure-Python implementation, excluding optional compiled accelerators. Use `--loop asyncio --http h11` to avoid optional uvloop/httptools binaries. Never bypass a warning on an unverified binary.

## Deploy on a host

Use the included Dockerfile with a persistent volume mounted at `/data`, one process, and HTTPS in front of it. Create a host service from this repository, with `src/backend/real-server` as its build directory. Do not deploy with local no-auth mode enabled.

Set these **server secrets**, not frontend variables:

- `GEMINI_API_KEY`: the event/API credential with Argon access.
- `SCENE_API_TOKEN`: a new, long, random bearer token for this private demo.
- `SCENE_DB_PATH=/data/scene.sqlite3`: mount durable disk at `/data`.
- `SCENE_CORS_ORIGINS`: exact allowed frontend origins, comma separated. Empty is appropriate for the included same-origin UI.
- `SCENE_ALLOW_LOCAL_NO_AUTH=0` (or omit it).

Paste the server token into the browser UI's connection settings. It stays in memory for that tab, not localStorage. Do not put it in a public demo URL. Host provisioning, billing, and production deployment have not been performed by adding this code.

## iPhone and bridge integration

The existing `/api/v1` response shapes remain readable by the Swift models, but **the unchanged iPhone UI is not a complete action client**:

1. The phone starts sessions with `{}`. To approve actions, it must supply `wearer_person_id` from a person profile and a timezone, or use a session created by the browser console.
2. The bridge must upload to that same session ID. There is no automatic browser-to-bridge session pairing.
3. Speaker mappings and review corrections currently live in the browser UI; the iPhone has no controls for them.
4. The phone should poll `run.status`, including completed-empty and failed states, rather than stopping at the first nonempty follow-up list.
5. Approve must send `{reviewed:true, ...corrections}`. For email/calendar, the client must open the returned `action_url` and show `execution_status`. Existing iOS `{}` approvals intentionally remain blocked.
6. The existing iOS approval draft edit is local-only. It must be submitted to the backend if the client wants the edit in the action form. The browser shows the server's draft.
7. Raw media URLs / thumbnail receipts are not provided. Use saved transcript quotes as evidence, not a claimed video playback receipt.

Read-only scenes, Ask and status routes can be used after configuring the API base URL and bearer token. `ws_url` is relative; clients should resolve it against the server origin and use HTTPS/WSS off-device.

## Endpoint quick reference

All data routes below are under `/api/v1` and require `Authorization: Bearer <SCENE_API_TOKEN>` unless explicitly running loopback-only local mode.

- `POST /sessions {timezone, wearer_person_id}` / `POST /sessions/{id}/end`
- `POST /people` multipart `name` (manual profile only)
- `POST /transcripts {session_id,start_ts,end_ts,transcript:[{speaker,text,start_ts,end_ts}]}`
- `POST /chunks` multipart `session_id,start_ts,end_ts,video?,audio?`
- `GET /chunks/{id}`: received, processing, indexed or failed
- `GET /scenes/today?session_id=...` / `GET /scenes/{id}`
- `POST /sessions/{id}/speakers {chunk_id,speaker,person_id}`
- `POST /followups/generate {session_id}` then `GET /followups?run_id=...`
- `POST /followups/{id}/approve {reviewed:true,owner?,due_at?,recipient?}`
- `POST /followups/{id}/dismiss`
- `GET /todos`, `GET /people`, `GET /facts`, `POST /pin`
- `POST /ask {query,session_id,top_k?}`: returns literal source quotes, not an unsupported free-form answer
- `GET /status`, `WS /live`
- `DELETE /data`: deletes **all** locally stored sessions, transcripts, people, mappings, tasks and follow-ups

ISO date-times must have an offset, e.g. `2026-10-25T14:00:00-07:00`. Names alone do not establish identity; the caller must confirm the mapping.

## Tests

```sh
pytest -q
```

The suite injects a fake model transport to test server behavior without spending API credits. Those tests are not proof of model accuracy. Real-provider and browser smoke-test results are recorded separately in `VERIFICATION.md`.
