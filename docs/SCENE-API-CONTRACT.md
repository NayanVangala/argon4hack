# SCENE — API + MCP Contract
## The exact schemas both builders code against from hour one

**Base URL:** `https://api.helloscene.xyz/api/v1` (replace with the hackathon deploy URL; the paths and shapes do not change).
**Auth:** `Authorization: Bearer <token>`. Short-lived tokens provisioned by the phone app; Scene Lens pairs via QR. No passwords. `401` = token expired, re-pair.
**Timestamps:** ISO 8601 with offset, always. **IDs:** UUID v4 strings. **Errors:** `{"error": {"code": "string", "message": "human readable"}}`.

Shared types used below:

```json
{
  "SceneSummary": {
    "id": "uuid",
    "start_ts": "2026-10-22T14:00:00-07:00",
    "end_ts": "2026-10-22T14:00:30-07:00",
    "summary": "Maya explaining Q3 numbers at the whiteboard",
    "quote": "I'll send the Q3 numbers by Friday",
    "thumb_url": "https://cdn.helloscene.xyz/t/<id>.jpg",
    "type": "conversation | person | action | quote | location | alert",
    "verified": true,
    "confidence": "verified | review | silence"
  },
  "Receipt": {
    "scene_id": "uuid",
    "timestamp": "2026-10-22T14:02:14-07:00",
    "quote": "I'll send the Q3 numbers by Friday",
    "thumb_url": "https://cdn.helloscene.xyz/t/<id>.jpg"
  }
}
```

---

## REST

### POST /sessions — start a recording session
Request: `{}` (empty body; device identified by token).
Response `201`:
```json
{ "id": "uuid", "started_at": "2026-10-22T14:00:00-07:00", "status": "live",
  "ws_url": "wss://api.helloscene.xyz/api/v1/live?token=<token>" }
```

### POST /sessions/{id}/end
Response `200`: `{ "id": "uuid", "ended_at": "...", "status": "ended", "scene_count": 23 }`

### POST /chunks — upload a 30s capture chunk
Multipart form: `video` (mp4), `audio` (wav), `session_id` (text), `start_ts` (text), `end_ts` (text).
Response `202`:
```json
{ "chunk_id": "uuid", "session_id": "uuid", "start_ts": "...", "end_ts": "...", "status": "received" }
```
Chunk statuses: `received → processing → indexed | failed`. Failed chunks return `{"error": {"code": "chunk_failed", "message": "..."}}` on status poll and are retried server-side 3x before surfacing.

### GET /status
Response `200`:
```json
{ "recording": true, "session_id": "uuid", "scene_count": 12,
  "last_scene_ts": "2026-10-22T14:06:00-07:00", "spend_usd": 1.84 }
```
`spend_usd` is the live Argon burn for the session — the spend ticker reads this.

### GET /scenes/today
Query: `?limit=50&before=<scene_id>` (pagination, newest first).
Response `200`:
```json
{ "scenes": [ { "SceneSummary" } ], "next_before": "uuid | null" }
```

### GET /scenes/{id} — full scene detail
Response `200`:
```json
{
  "id": "uuid", "session_id": "uuid",
  "start_ts": "...", "end_ts": "...",
  "summary": "Maya explaining Q3 numbers at the whiteboard",
  "objects": ["whiteboard", "laptop", "coffee cup"],
  "people": [{ "name": "Maya", "confidence": "verified" }],
  "actions": ["pointing", "talking"],
  "visible_text": ["Q3 revenue $4.2M"],
  "type": "conversation", "confidence": "verified",
  "critique": [
    { "check": "transcript_alignment", "result": "pass", "note": "Key claims appear in transcript" },
    { "check": "visual_grounding", "result": "pass", "note": "Whiteboard text matches keyframe" }
  ],
  "transcript": [
    { "speaker": "Maya", "text": "I'll send the Q3 numbers by Friday",
      "start_ts": "...", "end_ts": "..." }
  ],
  "keyframes": ["https://cdn.helloscene.xyz/k/<id>/0.jpg"],
  "pinned": false
}
```

### POST /ask
Request:
```json
{ "query": "What did Maya promise me?", "top_k": 8 }
```
Response `200`:
```json
{
  "answer": "Maya promised to send the Q3 numbers by Friday.",
  "receipts": [
    { "scene_id": "uuid", "timestamp": "2026-10-22T14:02:14-07:00",
      "quote": "I'll send the Q3 numbers by Friday",
      "thumb_url": "https://cdn.helloscene.xyz/t/<id>.jpg" }
  ],
  "sources": ["fact:uuid", "scene:uuid"]
}
```
Rules: `sources` prefixes every claim — `fact:` = structured fact store hit, `scene:` = retrieved chunk. The answer text must be answerable from the receipts; if nothing matches, answer is `"I don't have a record of that."` with empty receipts (recallai's cite-or-say-no-record rule).

### POST /pin
Request: `{ "scene_id": "uuid", "note": "Q3 numbers promise" }` (`scene_id` optional — omitted pins the current live scene; `note` optional).
Response `201`: `{ "pinned": true, "pin_id": "uuid", "scene_id": "uuid" }`

### GET /people
Response `200`: `{ "people": [ { "id": "uuid", "name": "Maya", "photo_thumb": "https://...", "last_seen": "...", "scene_count": 14, "quote_count": 6, "verified": true } ] }`

### POST /people — enroll a speaker
Multipart: `photo` (jpg), `voice_sample` (wav, ~20s), `name` (text).
Response `201`: `{ "id": "uuid", "name": "Maya", "verified": true }`
Enrollment stores ArcFace + ECAPA prints in ChromaDB; the person's block assembles on the client.

### GET /facts
Query: `?actor=Maya&limit=20`.
Response `200`: `{ "facts": [ { "id": "uuid", "text": "Maya promised Q3 numbers by Friday", "scene_id": "uuid", "actors": ["Maya"], "extracted_at": "..." } ] }`

### WS /live — real-time scene pushes
Connect: `wss://api.helloscene.xyz/api/v1/live?token=<token>`.
Server → client messages:
```json
{ "event": "scene", "scene": { "SceneSummary" } }
{ "event": "status", "recording": true, "scene_count": 13 }
{ "event": "error", "code": "pipeline_stalled", "message": "No scenes indexed in 120s" }
```
Client → server: `{ "event": "ping" }` (keepalive; server replies `pong`). No other client messages — the lens never writes over the socket.

### POST /followups/generate — run the Follow-Through Agent
Request: `{ "session_id": "uuid" }` (omitted = today's session).
Response `202`:
```json
{ "run_id": "uuid", "status": "running",
  "steps": ["find_promises", "verify_quotes", "draft_followups"] }
```
The agent runs on Managed Agents: `get_facts` → promises; `get_scene` → transcripts; sandbox code fuzzy-matches each quote against its transcript segment and checks timestamp alignment; verified promises become drafts. Poll `GET /followups?run_id=` for results.

### GET /followups — list follow-up drafts
Query: `?run_id=<uuid>&status=pending`.
Response `200`:
```json
{ "followups": [
  { "id": "uuid", "run_id": "uuid",
    "promise": "Maya promised Q3 numbers by Friday",
    "person": "Maya",
    "quote": "I'll send the Q3 numbers by Friday",
    "quote_verified": true, "verified_at": "...",
    "draft": "Hi Maya — following up on the Q3 numbers you mentioned today...",
    "status": "pending | approved | dismissed | sent",
    "scene_id": "uuid" }
] }
```
`quote_verified: false` drafts are never shown for approval — they surface under `status: needs_review` instead.

### POST /followups/{id}/approve
Response `200`: `{ "id": "uuid", "status": "approved" }`. Nothing sends without this tap. Delivery (Resend) is a stretch goal; demo floor is the approved state.

### POST /followups/{id}/dismiss
Response `200`: `{ "id": "uuid", "status": "dismissed" }`

---

## MCP server (5 read-only tools)

Transport: MCP over stdio/SSE per the MCP spec. Server name: `scene-memory`. Publish open-source at the hackathon.

### search_scenes
```json
{ "name": "search_scenes",
  "description": "Search the wearer's recorded scenes by natural language. Returns scenes with timestamps. Always cite scene_id and timestamp for any claim.",
  "inputSchema": { "type": "object",
    "properties": {
      "query": { "type": "string", "description": "Natural language question, e.g. 'what did Maya promise'" },
      "top_k": { "type": "integer", "default": 8, "minimum": 1, "maximum": 25 },
      "person": { "type": "string", "description": "Filter to scenes with this person" },
      "since": { "type": "string", "description": "ISO 8601 lower bound" }
    },
    "required": ["query"] } }
```

### get_scene
```json
{ "name": "get_scene",
  "description": "Full detail for one scene: summary, transcript with speakers, keyframes, objects, confidence.",
  "inputSchema": { "type": "object",
    "properties": { "scene_id": { "type": "string" } },
    "required": ["scene_id"] } }
```

### list_people
```json
{ "name": "list_people",
  "description": "Enrolled speakers with interaction counts and last-seen timestamps.",
  "inputSchema": { "type": "object", "properties": {} } }
```

### list_interactions_with_person
```json
{ "name": "list_interactions_with_person",
  "description": "Scenes featuring a person, newest first, each with a one-line summary and timestamp.",
  "inputSchema": { "type": "object",
    "properties": {
      "name": { "type": "string" },
      "limit": { "type": "integer", "default": 10, "minimum": 1, "maximum": 50 }
    },
    "required": ["name"] } }
```

### get_facts
```json
{ "name": "get_facts",
  "description": "Durable extracted facts (promises, commitments, decisions) with source scenes. Check this first for 'what did X promise/decide' questions.",
  "inputSchema": { "type": "object",
    "properties": {
      "actor": { "type": "string", "description": "Filter by person" },
      "query": { "type": "string", "description": "Keyword filter over fact text" },
      "limit": { "type": "integer", "default": 20, "minimum": 1, "maximum": 50 }
    } } }
```

MCP rules (from the InSight lesson): two tools beat twenty — these five are the whole surface. Every tool result includes `scene_id` + `timestamp` so agents cite sources. The MCP server never writes: no pin, no enroll, no delete. Reads only.

---

## Mock server (build-day hour one)

Until the real pipeline is live, serve these exact shapes with canned data. The contract above is frozen — mocks must match it field-for-field so the phone app, dashboard, and lens teams build without waiting. Canned set: 8 scenes across 2 fake people ("Maya", "Unknown"), 3 facts, 1 pinned scene. `POST /ask` matches keywords ("promise" → the Maya receipt; anything else → "I don't have a record of that.").
