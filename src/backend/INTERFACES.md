# Scene backend — LOCKED INTERFACES (coordinator lock, post agreement round)

This file is the single source of truth for module boundaries. All 6 plan
files in `_plans/` fed into it. Where a plan disagreed with another, the
resolution below wins. Builders: build to this file exactly. If an
interface does not fit your module, flag it in your report AND build to
the locked version anyway. Do not silently deviate. Do not edit another
module's files.

## File layout

```
scene-backend/
  server.py              # entrypoint (routes builder owns it)
  README.md              # coordinator writes at integration
  INTERFACES.md          # this file
  app/
    __init__.py          # routes builder owns it (empty)
    routes.py            # (1) REST + WS live + error envelope
    ingest.py            # (2) ingest pipeline orchestration
    services.py          # (2) service interfaces + mock implementations
    store.py             # (3) Store interface + InMemoryStore + projections
    seed.py              # (3) canned seed data (from the old mock, verbatim)
    ask.py               # (4) Ask + facts
    followthrough.py     # (5) Follow-Through approval gate
    critic.py            # (5) Critic pure functions
    mcp.py               # (6) MCP tools (functions over the store)
```

Python, stdlib only. No paid services, no real API keys, mock data only.

## Wiring style (locked)

Constructor injection everywhere. One shared store instance, created once
in `server.py`, passed to every service. No globals, no model imports in
routes.

```python
store = InMemoryStore()
seed(store)
transcriber, analyzer, attributor, embedder = make_mock_services()
ingest = IngestPipeline(store, broadcaster, transcriber, analyzer,
                        attributor, embedder)
ask = AskService(store, MockReasoning())
followthrough = FollowThroughService(store)
handler = create_handler(store, ingest, ask, followthrough)
```

`broadcaster` is the routes module's broadcast object (see Routes). The
real swap changes only the injected implementations, never call sites.

## Store (module 3 owns `store.py`)

Class `InMemoryStore`. All timestamps ISO 8601 with offset, all ids UUID
v4 strings. One `threading.Lock` guards all mutation. Getters return
`None` on missing id (routes map to 404). Mutations on missing ids raise
`KeyError` (routes map to 404). `approve_followup` on a `needs_review`
draft raises `ValueError` (routes map to 400 `not_approvable`).

```python
# sessions
create_session() -> dict
get_session(session_id) -> dict | None
get_live_session() -> dict | None
end_session(session_id, ended_at=None) -> dict  # ended_at defaults to now
current_session_id() -> str  # live id, else today's seed session id
# chunks (bookkeeping only; blobs stay out of the store)
create_chunk(session_id, start_ts, end_ts, storage_path=None) -> dict
update_chunk_status(chunk_id, status) -> dict  # received|processing|indexed|failed
# scenes (full dicts always; projection is separate, see below)
add_scene(scene) -> dict  # STORE assigns the id; inserts newest-first
get_scene(scene_id) -> dict | None
list_scenes_today(limit=50, before=None) -> (list[dict], str | None)
list_scenes_for_session(session_id) -> list[dict]  # oldest-first, for Ask
list_scenes_by_person(name, limit=10) -> list[dict]  # newest-first
update_scene(scene_id, **fields) -> dict  # critique/confidence/pinned updates
# facts
add_fact(fact) -> dict
list_facts(actor=None, query=None, limit=20, session_id=None) -> list[dict]
# people
enroll_person(name, photo_thumb=None) -> dict
list_people() -> list[dict]
get_person_by_name(name) -> dict | None
record_appearance(name, last_seen, quote=False) -> None
# pins
create_pin(scene_id, note=None) -> dict  # also sets scene pinned
list_pins() -> list[dict]
# followups
create_followup_run(session_id) -> dict
get_followup_run(run_id) -> dict | None
update_followup_run_status(run_id, status) -> dict
add_followup(followup) -> dict
get_followup(followup_id) -> dict | None
list_followups(run_id=None, status=None) -> list[dict]
approve_followup(followup_id) -> dict  # ValueError if needs_review
dismiss_followup(followup_id) -> dict  # any status -> dismissed (mock parity)
# spend + status
add_spend(amount_usd) -> float
get_spend() -> float
status_snapshot() -> dict  # recording, session_id, scene_count, last_scene_ts, spend_usd (2dp)
```

Record shapes are contract-exact plain dicts (see plan 03 §b): session,
chunk (`status: received|processing|indexed|failed`), scene (incl.
`critique`, `transcript` lines, `keyframes`, `pinned`, `embedding_refs`
which is `None` in memory), fact, person, pin (`pin_id`, not `id`),
followup_run, followup (`pending|approved|dismissed|sent|needs_review`).

Projection helpers live in `store.py` as pure functions, used by routes:
`scene_summary(scene)` and `scene_detail(scene)` with the mock's field
lists. REST detail omits `quote`/`verified` (contract shape); the stored
record keeps them.

Pagination: `list_scenes_today` finds `before` in the newest-first list,
returns the slice after it; `next_before` = last returned id iff more
remain, else `None` (old-mock semantics exactly).

## Store persistence (Phase 1 advance, 2026-10-25)

The store interface above is unchanged, but the default implementation
is now durable. `app/sqlite_store.py` provides `SQLiteStore` with the
same method names and signatures as `InMemoryStore` (plus the same
seed-only helpers `_seed_session` / `_seed_person` and the
`set_scene_pinned` alias, so `seed.py` runs unchanged), backed by
SQLite via stdlib `sqlite3` only. Records are stored as JSON rows with
an insertion-order sequence; list methods run the same Python
filter/slice logic as the in-memory store, so pagination and filter
semantics match exactly.

- Default store: SQLite. Database file:
  `~/workspace/scene-backend/scene.db` (next to `server.py`, resolved
  from the server file location, not the working directory).
- Opt-out: `SCENE_STORE=memory` selects `InMemoryStore` instead. Any
  other value (including unset) selects SQLite.
- Seed-on-empty rule: `server.py` calls `seed(store)` for SQLite only
  when `store.is_empty()` is true, meaning every record table is empty.
  Restarting the server against a non-empty database never re-seeds,
  so canned demo data is never duplicated. The memory store is fresh
  per process, so it is still seeded once on every start.
- Everything else about running the server is identical: port from
  `PORT` (default 8000), REST base `/api/v1`, WS `/live`. No routes,
  ask, ingest, follow-through, critic, or MCP behavior changed.

## Ingest (module 2 owns `ingest.py`, `services.py`)

```python
class IngestPipeline:
    def __init__(self, store, broadcaster, transcriber, analyzer,
                 attributor, embedder): ...
    def process_chunk(self, session_id, start_ts, end_ts, video_path,
                      audio_path) -> dict  # ChunkResult: chunk_id, session_id,
                      # start_ts, end_ts, status, scene
```

Steps, in order: chunk in (`create_chunk` as `received`, then
`processing`) → store raw (paths kept; mock ignores contents) →
keyframes (~1fps; mock: one placeholder path) → transcribe →
analyze → attribute → embed → facts (mock extracts none) →
critique (`critic.critique_scene`, mock shim yields all-pass for mock
analyzer scenes) → store (`add_scene`, loop `add_fact`, `add_spend(0.07)`
once per chunk, `update_chunk_status` to `indexed`) → WS push
(`broadcast_scene(summary)`, then `broadcast_status()`), only after the
scene row is stored. Transcribe-first so a quote exists even if analysis
degrades. On failure retry 3x, then `failed` (surfaces as WS error only,
no poll route in this phase). Synchronous in this phase.

Service interfaces (plain dicts, no SDK types):

```python
Transcriber.transcribe(audio_path) -> list[Segment]
  # Segment: {speaker_label, text, start_ts, end_ts,
  #           word_timestamps: [{word, start_ts, end_ts}]}
SceneAnalyzer.analyze(keyframe_paths) -> SceneDraft
  # SceneDraft: {summary, objects[], people[{count, description}],
  #              actions[], visible_text[], type, confidence}
Attributor.attribute(segments, keyframe_paths, scene_people)
  -> list[AttributedSegment]  # {segment, speaker_name, confidence}
  # face+voice agree -> verified, one signal -> review, no speech -> silence
  # never guess a name
Embedder.embed(text) -> list[float]
Embedder.embed_image(keyframe_path) -> list[float]
Embedder.collection_names() -> ("text_memories", "visual_memories")
make_mock_services() -> (Transcriber, SceneAnalyzer, Attributor, Embedder)
```

Mock behavior (deterministic): one segment, speaker `Unknown`, text
`"Live segment (mock transcript)."`; scene summary `"Live chunk indexed
(mock scene)"`, type `conversation`, confidence `review`, people
`[{name: "Unknown", confidence: "review"}]`, actions `["talking"]`;
embeddings are sha256 pseudo-vectors, computed but NOT persisted in this
phase (`embedding_refs` stays `None`; the real store persists them).
Observable behavior matches the old mock: one chunk upload → one new
scene prepended newest-first, thumb/keyframe URLs in the
`cdn.helloscene.xyz/t/<id>.jpg` / `/k/<id>/0.jpg` pattern, WS scene +
status pushes, spend +0.07, route replies 202 `received` (sync indexing
before the reply). Transcripts live INSIDE the scene dict; there is no
separate transcript store method. The store assigns scene ids; ingest
reads the id back from `add_scene`'s return for fact linkage. Routes
write uploaded bytes to temp files and pass paths; mock discards the
files after the reply (documented; real phase moves them to durable
storage).

## Ask (module 4 owns `ask.py`)

```python
class AskService:
    def __init__(self, store, backend): ...
    def ask(query, session_id, top_k=8) -> dict
      # returns POST /ask contract dict: {answer, receipts, sources}
    def list_facts(actor=None, limit=20) -> dict
      # returns GET /facts contract dict: {facts: [...]}
    def build_session_context(session_id) -> dict
      # {facts, scenes, transcripts}; exposed for tests/debugging
```

Context order (spec §4.4, no retrieval, no top-K): facts first, then
scenes chronological (`list_scenes_for_session`, oldest-first), then
transcripts in the same order, each line attached to its scene_id and
timestamps. Session resolution: routes pass the body's `session_id` when
present, else `store.current_session_id()`. `top_k` is accepted and
ignored.

```python
class ReasoningBackend(Protocol):
    def reason(self, context, query) -> dict
      # {answer, receipts: [{scene_id, timestamp, quote, thumb_url}],
      #  sources: ["fact:<id>" | "scene:<id>"], spend_usd? (optional)}
```

`ask()` enforces cite-or-say-no-record AFTER `reason()`: empty receipts
and sources force `"I don't have a record of that."`; a receipt whose
quote does not match its scene's transcript (verbatim or 0.80 fuzzy,
same rule as the per-answer Critic) is dropped; if none remain, fall
back to no-record. Spend: `ask()` adds `reason()`'s `spend_usd` when
present, else 0.12 flat (mock returns 0.12), on EVERY /ask call including
no-record answers. `MockReasoning` preserves the old mock exactly:
`"promise" in query.lower()` → Maya Q3 answer with the promise-scene
receipt and `fact:`/`scene:` sources; anything else → no-record with
empty receipts/sources. No other query gets a canned answer.

```python
class FactExtractor(Protocol):
    def extract_facts(self, scene) -> list[dict]
      # {id, text, scene_id, actors[], extracted_at}
```

Mock extractor returns the canned fact set unchanged; real (later) is
Argon extraction over each indexed scene, same shape, stored via Store.

## Follow-Through (module 5 owns `followthrough.py`)

```python
class FollowThroughService:
    def __init__(self, store): ...
    def generate_run(self, session_id=None) -> dict
      # returns {run_id, status: "running", steps: [find_promises,
      #   verify_quotes, draft_followups]} with 202 semantics; the stored
      #   run becomes "done" after synchronous completion
    def list_followups(self, run_id=None, status=None) -> dict
    def approve_followup(self, followup_id) -> dict  # raises KeyError/ValueError
    def dismiss_followup(self, followup_id) -> dict  # raises KeyError
```

Flow: find promises via `store.list_facts(query="promise",
session_id=...)` plus commitment/decision facts → verify quotes with
code (normalize + `difflib.SequenceMatcher` ≥ 0.80 against each
transcript line and the joined segment; best-matching line must overlap
the scene window; both pass → `quote_verified=True`,
`verified_at=now`, else `False`/`None`) → drafts from a template for
verified promises; unverified promises get `draft=""`,
`status="needs_review"`, never a sendable draft. Gate: approve only from
`pending` with `quote_verified=True`; `needs_review` approve raises
`ValueError` (routes → 400 `not_approvable`); approve from any other
status sets `approved` (mock parity, idempotent). Dismiss from any
status sets `dismissed` (mock parity; the plan's tightening is rejected
at lock). Unknown ids raise `KeyError` (routes → 404
`followup_not_found`). Nothing sends: approve only flips status; Resend
delivery is a stretch goal owned elsewhere. Mock parity: `generate_run`
seeds exactly the old mock's 3 canned drafts (2 pending verified: Maya
Q3-numbers promise, Maya demo-leads-with-glasses decision; 1
needs_review: Unknown speaker, unverified quote, empty draft). Real
later: fact-driven discovery replaces seeding; verification code stays.
No auto-run at session end in this phase (on-demand only; hook later).

## Critic (module 5 owns `critic.py`, pure functions, no I/O)

```python
critique_scene(scene) -> [{check, result, note}]  # transcript_alignment,
  # visual_grounding, people_consistency, temporal_sanity
critique_answer(query, answer, receipts, scenes) -> [{check, result, note}]
  # receipt_coverage, verbatim_quotes, relevance
scan_day(scenes, facts, followups) -> dict  # contradiction + open_loop entries
decide_fix(critique, kind="scene"|"answer") -> dict
  # {action: keep|downgrade|needs_review, constraints, regenerate_once}
```

Rules: all pass → `keep`. Any fail → `downgrade` (scene confidence →
`review`; answer → verified subset only) plus `constraints` = failed
checks with notes for a re-run prompt. Re-run still failing, or an
unfixable fail → `needs_review` (scene routed out of memory; answer
falls back to no-record). Per-answer: at most one regenerate; still
failing → verified subset / no-record fallback, never an unverified
answer. Mock shim: when keyframe/face annotations are absent (all mock
data), `visual_grounding` and `people_consistency` preserve the scene's
seeded critique entry instead of inventing a pass. Seeded critique is
preserved for seeded scenes; newly ingested mock scenes get all-pass
from the shim. Real visual grounding source (locked): Argon re-pass on
keyframes; Store carries keyframe annotations later via an additive
`keyframe_annotations` field on the scene dict.

## MCP (module 6 owns `mcp.py`, functions over the store)

```python
search_scenes(store, query, top_k=8, person=None, since=None) -> dict
get_scene(store, scene_id) -> dict
list_people(store) -> dict
list_interactions_with_person(store, name, limit=10) -> dict
get_facts(store, actor=None, query=None, limit=20) -> dict
TOOLS = {"search_scenes": ..., "get_scene": ..., "list_people": ...,
         "list_interactions_with_person": ..., "get_facts": ...}
TOOL_SCHEMAS = {...}  # inputSchema verbatim from the contract
call_tool(store, name, arguments) -> dict
```

Signatures, inputs, and outputs are contract field-for-field (see plan
06). Every result carries `scene_id` + `timestamp` (scenes: id/start_ts;
facts: scene_id/extracted_at; people: newest scene id or null /
last_seen). Error dicts are the only exception (no scene to cite):
unknown `get_scene` id → `{"error": {"code": "scene_not_found",
...}}`; bad input → `{"error": {"code": "invalid_argument", ...}}`;
unknown tool → `{"error": {"code": "unknown_tool", ...}}`. Tools never
raise for bad input. Read-only: tools use only `get_scene`,
`list_scenes_today` (paged to exhaustion for search), `list_scenes_by_person`,
`list_people`, `list_facts`; every return is a `copy.deepcopy` of store
data; no writes, no files, no network. Keyword/token ranking stands in
for embedding retrieval in this phase (signature/output unchanged when
embeddings swap in inside `search_scenes` only). REST routes must never
import or call these tools; they serve the same data through REST.
Transport (later: stdio/SSE) only lists `TOOL_SCHEMAS` and dispatches
`TOOLS[name](store, **arguments)`.

## Routes (module 1 owns `routes.py`, `server.py`, `app/__init__.py`)

Thin layer: parse, validate, call one store/service method, serialize
to the contract shape. No Argon, embedding, or verification logic here.

| Route | Call | Result |
|---|---|---|
| GET `/`, `/api/v1` | none | 200 `{service, rest, ws}` |
| POST `/sessions` | `store.create_session()` | 201 `{id, started_at, status:"live", ws_url}`; `ws_url` from request `Host` |
| POST `/sessions/{id}/end` | `store.end_session(id)` | 200 `{id, ended_at, status:"ended", scene_count}`; unknown id → 404 (deviation from old mock's unconditional 200, sane for real shape) |
| POST `/chunks` (multipart) | `ingest.process_chunk(...)` | 202 `{chunk_id, session_id, start_ts, end_ts, status:"received"}`; missing `session_id` → live session, else today's; missing file parts → 400 |
| GET `/status` | `store.status_snapshot()` | 200 `{recording, session_id, scene_count, last_scene_ts, spend_usd}` (2dp) |
| GET `/scenes/today?limit=50&before=<id>` | `store.list_scenes_today(limit, before)` | 200 `{scenes:[SceneSummary...], next_before}`; newest-first, null if no more |
| GET `/scenes/{id}` | `store.get_scene(id)` | 200 full detail, else 404 `scene_not_found` |
| POST `/ask` | `ask.ask(query, session_id, top_k)` | 200 `{answer, receipts, sources}`; session_id resolved by routes (body, else `current_session_id()`); routes never touch spend |
| POST `/pin` | `store.create_pin(scene_id, note)` | 201 `{pinned:true, pin_id, scene_id}`; omitted id → latest scene; unknown id → 404 `scene_not_found` |
| GET `/people` | `store.list_people()` | 200 `{people:[...]}` |
| POST `/people` (multipart) | `store.enroll_person(name, photo_thumb)` | 201 `{id, name, verified:true}`; name from multipart if present else `"Enrolled Speaker"`; photo_thumb placeholder cdn URL; voice_sample accepted, ignored in mock |
| GET `/facts?actor=&limit=20` | `ask.list_facts(actor, limit)` | 200 `{facts:[...]}` |
| POST `/followups/generate` | `followthrough.generate_run(session_id)` | 202 `{run_id, status:"running", steps:[...]}` |
| GET `/followups?run_id=&status=` | `followthrough.list_followups(run_id, status)` | 200 `{followups:[...]}` |
| POST `/followups/{id}/approve` | `followthrough.approve_followup(id)` | 200 approved; `needs_review` → 400 `not_approvable`; unknown → 404 `followup_not_found` |
| POST `/followups/{id}/dismiss` | `followthrough.dismiss_followup(id)` | 200 dismissed; unknown → 404 |
| WS `/live` | WS handler | 101, else 400 `websocket_upgrade_required` |
| Other path | none | 404 `not_found` (`"Unknown route: <path>"`, old-mock wording) |

`create_handler(store, ingest, ask, followthrough)` returns the
`BaseHTTPRequestHandler` subclass for `ThreadingHTTPServer`; constructor
injection is the wiring seam. Routes own the WS client set, framing
(RFC 6455 helpers ported from the old mock), and `broadcast(obj)` /
`broadcast_scene(summary)` / `broadcast_status()`; ingest calls
broadcasts after storing, routes call `broadcast_status()` after session
start/end. On WS connect: `{event:"status", ...}`, then latest scene as
`{event:"scene", scene}` if one exists. Client text `{"event":"ping"}` →
`{"event":"pong"}`; opcode 0x9 → 0xA pong; 0x8 → echo close, drop; other
text ignored. Broken sends prune the client set. No synthetic 30s push
(deliberate deviation from the old mock; real pushes fire only on
indexed scene, session start/end, or status change). Chunk failure
surfaces as WS `{event:"error"}` only (no poll route in this phase).
`pipeline_stalled` is reported by ingest, never by a routes timer.

Error envelope (one helper for every failure):
`{"error": {"code": ..., "message": ...}}` with JSON type + CORS headers.
400 `bad_request` (malformed/non-dict JSON, bad `limit`, bad multipart),
400 `not_approvable`, 400 `websocket_upgrade_required`, 404
`not_found`/`scene_not_found`/`followup_not_found`. Service exceptions
map: `KeyError` → 404 (code by context), `ValueError` from approve →
400 `not_approvable`, other `ValueError` → 400 `bad_request`.
Unexpected errors → 500 `internal_error`, generic message, no traceback.
Success: GET 200, session/pin/enroll 201, chunk/followup-generate 202,
OPTIONS 204. 401 reserved for real auth later, never emitted here.

Parsing: JSON reads exactly `Content-Length` bytes; empty body → `{}`;
malformed/non-dict → 400 (old-mock behavior). `limit` int-parsed with
defaults (50 scenes, 20 facts); unparsable → 400, not a crash (deliberate
fix over the old mock's `int()` crash). Multipart (`/chunks`: `video`,
`audio`, `session_id`, `start_ts`, `end_ts`; `/people`: `photo`,
`voice_sample`, `name`): raw bytes split on boundary manually (stdlib
only, `cgi` is gone); text parts UTF-8; file parts passed as bytes,
written to temp files, paths handed to ingest; no codec validation here.

CORS/auth, exactly like the old mock: every response (success, error,
OPTIONS) carries `Access-Control-Allow-Origin: *`, `Allow-Headers:
Authorization, Content-Type`, `Allow-Methods: GET, POST, OPTIONS`;
OPTIONS on any route → 204. Auth NOT enforced: any/missing/expired
Bearer accepted, WS `?token=` ignored. Contract auth (401 = expired,
re-pair) is a later swap in this module only, behind a `check_auth()`
hook that currently returns OK.

`server.py` (routes builder): `ThreadingHTTPServer(("0.0.0.0", PORT),
handler)` with `PORT` from env (default 8000), `seed(store)` once,
`make_mock_services()` + `MockReasoning()` wiring, prints the REST and
WS URLs, serves forever.

## Seed (module 3 owns `seed.py`)

`seed(store)` builds one today session, then the old mock's 8 scenes in
chronological order, inserted newest-first: 09:15 Maya Q3 promise
(`pinned=True`, quote "I'll send the Q3 numbers by Friday"); 09:42
Unknown demo-flow question (the 1 failing critique: `visual_grounding`
fail, "Face partially occluded in keyframe", other 3 checks pass); 10:05
Maya Ask-flow napkin; 10:31 hallway silence (`confidence: silence`,
empty everything); 11:02 Maya pitch rubric; 11:20 Maya pipeline
whiteboard; 11:48 Unknown dashboard question; 12:10 Maya Friday
confirmation. All other scenes get all-pass critiques. Facts (3): Q3
promise → promise scene, demo-leads-with-glasses decision → 11:20
scene, demo-is-50% → 11:02 scene. People (2): Maya (`verified=True`,
`last_seen` 12:10, 5 scenes, 6 quotes), Unknown (`verified=False`,
`last_seen` 11:48, 2 scenes, 0 quotes). Spend starts 1.84, live session
`None`, pins/followups empty (the pinned flag on the promise scene is
seed state, not a pin record). Ids generated once inside `seed()` and
shared across fact references. `seed()` runs exactly once per store.

## Global rules (locked)

- Spend: one global counter for the demo (per-session column in
  Postgres later). Rates: chunk +0.07 (ingest owns it), ask +0.12 (ask
  owns it, including no-record answers). Routes never call `add_spend`.
- "Today": current session = today for the demo; `list_scenes_today`
  returns all scenes in this phase (calendar-day PDT filter later).
- Person counters: stored in memory via `record_appearance` (derived in
  Postgres later).
- Deliberate deviations from the old mock (all documented here, not
  accidents): no synthetic 30s WS push; unknown session end → 404;
  unparsable `limit` → 400 instead of crashing; mock embeddings computed
  but not persisted; mock followup generation seeds canned drafts while
  verification code itself is real.
- Still unbuilt in this phase (later): MCP stdio/SSE transport, Resend
  delivery, auth enforcement, Postgres/ChromaDB stores, real whisperX /
  Argon / ArcFace / ECAPA implementations, chunk-failure poll route,
  auto-run of Follow-Through at session end, keyframe annotations on
  scenes, per-session spend, calendar-day "today" filter.

## Real replacements (what each mock becomes)

| Module | Mock now | Real later |
|---|---|---|
| services.Transcriber | fixed Unknown segment | whisperX (+ diarization) |
| services.SceneAnalyzer | fixed mock scene | Argon, one call per chunk over ~6 keyframes |
| services.Attributor | always Unknown/review | ArcFace face print + ECAPA voice print fusion |
| services.Embedder | sha256 pseudo-vector, discarded | text + CLIP embeddings into ChromaDB |
| store.InMemoryStore | dicts + lists + one lock | Postgres tables + ChromaDB collections, same method names |
| ask.MockReasoning | keyword rule | Argon whole-session reasoning via Interactions API |
| ask.FactExtractor (mock) | canned facts | Argon fact extraction per scene |
| followthrough (mock) | canned drafts + real verify code | Managed Agents sandbox running the same steps |
| critic (mock shim) | seeded/all-pass critiques | Argon re-pass + CLIP annotations |
| mcp tools | keyword search, store reads | same functions; embedding search inside search_scenes; stdio/SSE transport added |
| routes | unenforced auth, CORS * | real Bearer check via check_auth(), CORS tightened |
