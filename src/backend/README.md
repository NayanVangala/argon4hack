# Scene backend (mock shaped like the real backend)

Python. The mock core is stdlib only; the real services layer adds third-party deps (see requirements.txt) and degrades to the mocks when keys or models are absent. No real API keys are stored in this repo.
Restructured from the single-file mock at `~/workspace/scene-mock-server/`
(same endpoints, same canned data, same spend rates). That mock is untouched
and still works; this is its replacement once the real services land.

## Run

```sh
cd ~/workspace/scene-backend
python3 server.py          # port 8000, PORT env overrides
```

REST at `http://localhost:8000/api/v1`, live WS at
`ws://localhost:8000/api/v1/live`. From the iPhone bridge, point the base URL
at the Mac's LAN IP on port 8000 (the phone cannot reach the Mac's localhost).

## Module map

| File | Owns | Real replacement (swap only this) |
|---|---|---|
| `app/routes.py` | All 16 contract REST routes, WS `/live`, error envelope, multipart parsing, CORS open, auth hook unenforced | Real Bearer check in `check_auth()`, tighten CORS |
| `app/store.py` | `InMemoryStore`: sessions, chunks, scenes + today pagination, facts, people, pins, followups + runs, spend, status snapshot | Postgres tables + ChromaDB collections, same method names |
| `app/seed.py` | Canned demo data (8 scenes, 3 facts, 1 pin, Maya + Unknown) | Real ingest output; delete when live |
| `app/ingest.py` | `IngestPipeline`: chunk in, transcribe, analyze, attribute, embed, critique, store, WS push | Same pipeline, real services injected |
| `app/services.py` | `Transcriber` / `SceneAnalyzer` / `Attributor` / `Embedder` interfaces + deterministic mocks + `make_mock_services()` | whisperX (+ diarization), Argon (1 call per chunk over ~6 keyframes), ArcFace + ECAPA fusion, text + CLIP embeddings |
| `app/ask.py` | `AskService`, `ReasoningBackend` + `MockReasoning`, `FactExtractor` + `MockFactExtractor` | Argon whole-session reasoning via Interactions API; Argon fact extraction per scene |
| `app/followthrough.py` | `FollowThroughService`: promise discovery, `verify_quote()` code check, verified drafts only, approve/dismiss gate | Managed Agents sandbox running the same steps; Resend delivery |
| `app/critic.py` | `critique_scene` / `critique_answer` / day-level scans, `decide_fix` | Argon re-pass on keyframes + CLIP annotations |
| `app/mcp.py` | 5 read-only MCP tools (`search_scenes`, `get_scene`, `list_people`, `list_interactions_with_person`, `get_facts`) over the store | Embedding search inside `search_scenes`; stdio/SSE transport |
| `server.py` | Wiring only: one shared store, seed it, build services, create handler | Env config, real service constructors |

Wiring style: constructor injection everywhere, one shared store instance,
no globals, no model imports in routes. `INTERFACES.md` is the locked
contract between modules; on conflict it wins over the `_plans/` drafts.

## Behavior notes (mock parity, locked)

- Spend: +0.07 per chunk (ingest owns it), +0.12 per ask (ask owns it,
  including no-record answers). Routes never add spend. Seed spend is 1.84.
- Ask loads the whole session, no retrieval step. `top_k` is accepted and
  ignored. No-record answers carry empty receipts and sources.
- Follow-Through: drafts with `quote_verified=false` never reach approval;
  they surface as `needs_review`, and approving one returns 400
  `not_approvable`. Nothing sends; approve-shows-sent is the demo floor.
- WS pushes fire only on real events (indexed scene, session start/end,
  status change). No synthetic 30s push, unlike the old mock.
- "Today" = current session for the demo; `list_scenes_today` returns all
  scenes in this phase (calendar-day PDT filter later).
- Transcripts live inside scene dicts; there is no separate transcript store.
- Mock embeddings are computed but NOT persisted (`embedding_refs` is None).
- Unknown session end returns 404 (old mock returned 200 unconditionally).
- Unparsable `limit` returns 400, not a crash (old mock crashed on `int()`).

## Known quirks

- Follow-up generation scopes to the current session. If you create a fresh
  session first and then generate, drafts verify against that empty session
  and all land in `needs_review`. Generate against the seeded/day session
  for the 2 pending + 1 needs_review demo set.
- Ingest does not call `record_appearance`, so live chunks do not bump
  person counters. No observable difference in mock (the mock attributor
  only returns Unknown); wire it when the real attributor lands.
- Ingest retries a failing chunk 3x, then marks it `failed` and sends a WS
  `{event: "error", code: "chunk_failed"}` only. There is no poll route for
  chunk failure in this phase.

## Real services: landed in the services + API layer (2026-10-25)

- `app/services.py`: `FasterWhisperTranscriber` (real word timestamps, speaker always Unknown, mock fallback), `ArgonSceneAnalyzer` (one Interactions call per chunk over up to 6 keyframes, thinking low), `ArgonReasoning` (whole-session Ask, thinking medium; lives in services.py, `ask.py` untouched, `AskService` accepts it via constructor injection), `FaceVoiceAttributor` (documented never-guess stub; real fusion needs ArcFace + ECAPA). `MockEmbedder` untouched. All third-party imports are lazy/guarded: importing services.py with no third-party packages installed still works.
- `app/routes.py`: real Bearer auth in `check_auth()` only (nothing else in routes.py changed). `AUTH_ENABLED` off by default; on requires `Authorization: Bearer <token>` matching `SCENE_API_TOKEN`; on with no token env fails closed.
- `app/mcp_stdio.py` (new): JSON-RPC 2.0 over stdio: `initialize`, `tools/list` (TOOL_SCHEMAS), `tools/call` (dispatches `call_tool`). Run: `python3 -m app.mcp_stdio` from the backend dir. Uses the same store selection as server.py.
- `requirements.txt` (new): `google-genai>=2.3.0` (verified 2.33.0), `faster-whisper` (unpinned, see below).

## Real services setup (Mac)

```sh
cd ~/scene-backend   # or wherever the backend is staged on the Mac
pip install -r requirements.txt
# faster-whisper: pin the version that installs and record it in
# requirements.txt. The model downloads on first transcribe.
# WHISPER_MODEL default "base", WHISPER_DEVICE "cpu",
# WHISPER_COMPUTE_TYPE "int8".
```

Env (server-side backend env only, gitignored backend.env; never in the
repo, never in the bridge app, never in chat):

```sh
GEMINI_API_KEY=...        # or GOOGLE_API_KEY; no key = Argon services
                          # degrade to the existing mocks with a clear log
AUTH_ENABLED=1            # off by default; on requires the next line
SCENE_API_TOKEN=...       # on with no token env = all requests refused
```

Wired 2026-10-25: server.py now constructs the real services
(`FasterWhisperTranscriber()`, `ArgonSceneAnalyzer()`,
`FaceVoiceAttributor()`, `MockEmbedder()` into `IngestPipeline`, and
`ArgonReasoning()` into `AskService`). Without deps or key installed,
each service degrades to its mock behavior with a clear log line, so
the wired server behaves exactly like the mock until deps + key land.

Mac verification checklist (still open): one live Argon analyzer call
over real JPEGs (now testable via ingest: frames come from
`_extract_keyframes`, no longer the mock placeholder); one live
ArgonReasoning call with the provisioned key; one real faster-whisper
transcribe (model download + word timestamps).
If `genai.Client()` fails at construction, check for a malformed proxy
env var first (that broke client construction in the Linux VM).

Keyframe extraction (landed 2026-10-25): `ingest._extract_keyframes`
now extracts ~6 real JPEG frames per chunk via ffmpeg (evenly spaced
at 10%/25%/40%/55%/70%/85% of the ffprobe duration, 30s fallback if
ffprobe is missing/unparseable), and ingest deletes those temp frames
after analysis (try/finally in `_run_once`, per attempt, so retries
never leak). If ffmpeg is missing or the video is unreadable, it logs
`[ingest] keyframe extraction failed (...)` and falls back to the
`mock://` placeholder, so a chunk never crashes on extraction failure.
ffmpeg is now a Mac requirement: `brew install ffmpeg`.

WS note: `?token=` on the WS upgrade is still ignored; the HTTP dispatch
gate covers REST only.

## Still unbuilt (out of this phase, by design)

SSE transport, Resend delivery, real ArcFace / ECAPA fusion (stub only),
chunk-failure poll route, auto-run of Follow-Through at session end,
keyframe annotations on scenes, per-session spend, calendar-day "today"
filter.
