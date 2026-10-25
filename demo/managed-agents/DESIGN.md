# Managed Agents execution design: Scene Follow-Through Agent

Standalone prototype for Isabella to integrate. It changes nothing in the
existing backend. It is a *client* of the contract API, plus a
clearly-marked seam for the one Managed Agents SDK call.

Sources verified against (read-only, 2026-10-25):

- `~/workspace/your_files/scene-final-spec/SCENE-API-CONTRACT.md`
  (follow-ups surface, MCP tools, auth, error envelope)
- `~/workspace/scene-backend/app/followthrough.py`
  (`FollowThroughService`, `verify_quote`, `STEPS`, `CANNED_DRAFTS`,
  approval-gate rules)
- `~/workspace/scene-backend/app/routes.py`
  (HTTP routing, status codes, `check_auth` Bearer rules)
- `~/workspace/your_files/scene-final-spec/SCENE-FINAL-SPEC.md` §4.7
  (Follow-Through Agent loop, Managed Agents framing, demo floor)

Everything in this design that is NOT in one of those sources is marked
`[UNVERIFIED]` or `[PROTOTYPE POLICY]`. Do not present it as verified.

## 1. Where the wrapper plugs in (without changing existing behavior)

```
Phone app / demo driver
  │  POST /api/v1/followups/generate {session_id?}  →  202 {run_id, status, steps}
  │  GET  /api/v1/followups?run_id=<id>             →  drafts + needs_review items
  │  POST /api/v1/followups/{id}/approve            →  human tap only
  │  POST /api/v1/followups/{id}/dismiss            →  human tap only
  ▼
Existing server (untouched): FollowThroughService.generate_run()
  find_promises → verify_quotes → draft_followups
```

The prototype sits *outside* the server, on the client side of the REST
API. It does three things the server already does, independently, so the
demo can show the Managed Agents loop working:

1. Re-runs the find → verify → draft loop against the public API
   (`GET /facts`, `GET /scenes/{id}`, then its own code checker) and
   compares its verdicts with the server's stored `quote_verified` /
   `status` fields. Agreement is demo evidence; disagreement is a bug
   report, never a silent override.
2. Triggers the server run with `POST /followups/generate` and polls
   `GET /followups?run_id=` for results.
3. Waits for the human approval state. It never approves, dismisses,
   edits, or sends anything itself.

Plug-in point, stated exactly: **the prototype never writes a draft to
the server.** There is no draft-creation endpoint to write to (see §6).
The server's `generate_run` remains the sole source of stored drafts.
A future step in which agent-produced drafts replace the server's canned
drafts would be a server change owned by Isabella; it is deliberately
out of scope here, and this prototype must not be described as doing it.

## 2. Managed Agents execution

- Agent: `antigravity-preview-09-2026` (Google Managed Agents /
  Antigravity agent in the Gemini API).
- Execution: remote sandbox (`environment="remote"` in the reported
  call shape), a hosted Linux environment where the agent reasons,
  executes code, and manages files until the task finishes or hits a
  configured limit.
- Model: the 09-2026 preview's reported default is Gemini 3.8 Flash;
  Scene's Argon reasoning is a separate layer and is NOT routed through
  this agent. This prototype makes no Argon call.
- `[UNVERIFIED]` The exact SDK call shape
  (`client.interactions.create(agent=..., input=..., environment="remote")`)
  was corroborated only by secondary write-ups found by web search on
  2026-10-25, not by official Google documentation read in this task.
  It is therefore implemented in `managed_followthrough.py` only as a
  guarded seam (`launch_managed_agent`) that refuses to run until
  Isabella confirms it against the official Antigravity agent guide.
  The prompt text the agent receives (`MANAGED_AGENT_PROMPT`) IS final
  and is independent of the SDK shape: any runner that can execute the
  prompt's instructions in a sandbox satisfies the design.
- `[UNVERIFIED]` `agent_config` model-selection keys were not verified
  and are not used. Do not guess them. If the demo needs Argon as the
  agent's model, confirm the key from the official guide first.
- The sandbox runs the *verifier code*, not just the LLM's opinion.
  That is the prize-lane point: real computation in the sandbox, with a
  human gate after it (see §4.7 framing in the spec: "it computes, it
  acts, and it respects a human gate").

## 3. The agent loop

One run, in order. Step names match `STEPS` in `followthrough.py`
exactly: `find_promises`, `verify_quotes`, `draft_followups`.

### Step 1 — find_promises: `get_facts` for today's promises

- REST: `GET /api/v1/facts?limit=50` (optional `?actor=<name>`).
  Contract default limit is 20; the prototype passes an explicit limit.
- MCP equivalent (for the Managed Agent's tool surface):
  `get_facts` with `{actor?, query?, limit?}`. MCP is read-only by
  contract; it never writes.
- Filter, client-side, to promises/commitments/decisions. The prototype
  mirrors the server's rule from `followthrough.py`:
  text matching `\b(promis|commit|decid)` (case-insensitive), applied
  to the fact text. The server additionally queries per keyword
  (`promise`, `commitment`, `decision`) and dedupes by fact id; the
  prototype dedupes the same way.
- Each candidate keeps its `scene_id`. A fact without a `scene_id`
  cannot be verified (no transcript to check against) and routes to
  `needs_review` (§5).

### Step 2 — verify_quotes: LLM proposes, code disposes

This is the load-bearing rule. The LLM (or the agent) proposes a quote
for each promise. Deterministic code, running in the sandbox, disposes:

1. Fetch the source scene: `GET /api/v1/scenes/{scene_id}` (REST) or
   `get_scene` (MCP). Use its `transcript` array of
   `{speaker, text, start_ts, end_ts}` lines.
2. Normalize both quote and transcript text: lowercase, replace every
   run of non-`[a-z0-9]` characters with a single space, strip
   (the `_normalize` rule in `followthrough.py`).
3. Score with `difflib.SequenceMatcher.ratio` against (a) each
   transcript line and (b) the joined transcript segment. Take the best.
4. Pass threshold: **ratio >= 0.80**.
5. Timestamp alignment: the best-matching line must overlap the scene
   window (`line_start <= scene_end and scene_start <= line_end`).
   Lines or scenes without parseable ISO 8601 timestamps cannot
   disprove overlap, so they pass this check; the fuzzy check must
   still pass. The joined-segment match spans the whole scene window
   by definition, so it skips the overlap check.
6. Result: `(verified: bool, best_ratio: float)`.

Important correction to the task brief: the brief said "exact string
match". The verified code does NOT use exact match; it uses the fuzzy
rule above (threshold 0.80). An exact match is a special case of it
(normalized equality gives ratio 1.0, which passes), but an
exact-match-only checker would be *stricter* than the server and would
diverge from it on seeded data. The prototype therefore ports the
server's fuzzy rule verbatim (`verify_quote` in
`managed_followthrough.py` is a line-for-line port of
`followthrough.verify_quote`, minus the store dependency). Any change
to the threshold or the normalization must be made in both places or
the two verdicts will disagree.

On seeded data this rule reproduces the server's flags:
verified, verified, unverified (the third canned draft's quote,
"I'll drop the link somewhere", matches no transcript line at >= 0.80).

### Step 3 — draft_followups: build drafts, submit via generate

- For each verified promise, build a draft object in the exact stored
  follow-up shape (field list in §6). Draft text is addressed to the
  person, references the promise, and carries the verified quote.
- For each unverified promise, build NO draft text (empty string in
  the server's stored form) and mark it for `needs_review` (§5).
- "Submit" means exactly one thing in this prototype:
  `POST /api/v1/followups/generate` with `{"session_id": "<uuid>"}`,
  or `{}` (empty object; omitted `session_id` = today's session).
  There is no per-draft submit endpoint. The prototype's own draft
  objects are its working output for the agent log and for Isabella's
  integration; the stored drafts it polls are the server's.
- Response is `202` with `{run_id, status: "running", steps}`. Note the
  quirk: the server runs synchronously and marks the stored run
  `done`, but still returns `status: "running"` in the 202 body.
  Clients must NOT wait for a run-status transition.
- Poll `GET /api/v1/followups?run_id=<run_id>` (no `status` filter, so
  `needs_review` items are visible too) until the list is non-empty
  or the poll timeout expires. Recommended: 2s interval, 30s timeout.
  `[UNVERIFIED / ABSENT]` There is no run-status endpoint
  (no `GET /followups/runs/{id}` or similar in the contract or routes).
  Do not poll for one.

### Step 4 — wait for approve / edit / dismiss

- Poll `GET /api/v1/followups?run_id=<run_id>` until every item the
  demo cares about reaches `approved` or `dismissed`, or the wait
  timeout expires. Pending items that never get a tap stay pending;
  the prototype reports them as "awaiting human decision" and exits
  without changing them.
- `[ABSENT — DO NOT INVENT]` There is NO edit endpoint in the
  contract or in `routes.py`. The approve/dismiss routes discard the
  request body. "Edit" therefore means: the user edits draft text in
  the phone UI *before* tapping approve, and that edited text is a
  client-side concern. If edited text must persist server-side,
  Isabella needs a new endpoint; this prototype does not invent one
  and the demo must not claim edit persistence.
- The prototype itself never calls approve or dismiss. Those calls
  belong to the phone approval screens, i.e. to a human tap.

## 4. The never-sends-without-a-tap guarantee

Enforced in three independent places, so no single layer failing
sends anything:

1. **In code (server, verified):** `FollowThroughService` has no send
   path at all. `approve_followup` only flips `status` to `approved`.
   Delivery via Resend is a stretch goal owned elsewhere and is not
   wired. The prototype likewise contains no send, email, or Resend
   code, and its fake transport asserts nothing was ever sent.
2. **In the API (verified):** there is no send endpoint. The only
   follow-up mutations are approve and dismiss, both `POST` with no
   body semantics, and approve is gated (§5). The contract states it
   directly: "Nothing sends without this tap. Delivery (Resend) is a
   stretch goal; demo floor is the approved state."
3. **In the prototype (policy):** the prototype's HTTP client exposes
   only `GET /facts`, `GET /scenes/{id}`,
   `POST /followups/generate`, and `GET /followups`. It has no
   approve/dismiss/send methods at all, so prototype code cannot
   approve even by accident. The demo script path is:
   agent run → verification log → stored drafts → human tap in the
   phone app → approved state shown. If a judge asks "what sent?",
   the honest answer is "nothing; approve only flips status."

## 5. Failure routing

| Situation | Prototype behavior | Server behavior (verified) |
|---|---|---|
| Quote verifies (>= 0.80 + window) | Draft built, shown for approval | Stored `status: pending`, `quote_verified: true`, `verified_at` set, draft text present |
| Quote fails verification | NO draft text; item reported as `needs_review` | Stored `status: needs_review`, `quote_verified: false`, `verified_at: null`, `draft: ""` |
| Fact has no `scene_id` / scene fetch 404 | `needs_review` (nothing to verify against) | Same outcome via the `scene is None → (False, 0.0)` path |
| Scene has empty transcript | `needs_review` | Same (`not lines → (False, 0.0)`) |
| Approve called on `needs_review` | Prototype never calls it; if the UI does, expect failure | `ValueError` → HTTP `400` with error code `not_approvable` and message "Unverified drafts are never approved; they stay under needs_review." |
| Approve called on pending with unverified quote | N/A (prototype never calls it) | Also `ValueError` → `400 not_approvable` |
| Approve called from any other status | N/A | Sets `approved` (mock parity, idempotent; NOT a pending-only gate — do not describe it as one) |
| Dismiss from any status | N/A (human tap) | Sets `dismissed` |
| Unknown follow-up id | N/A | `KeyError` → HTTP `404` with code `followup_not_found` |
| Expired / wrong token (auth on) | Abort with 401, no retry with a different token | HTTP `401` code `unauthorized`, message "Token expired, re-pair." |

Rules that must never be weakened, in either codebase:

- A verification failure NEVER becomes a draft. It surfaces as
  `needs_review`, never as `pending`.
- A `needs_review` item is NEVER shown for approval and NEVER
  approvable (400, not a silent skip).
- A draft with an empty `draft` field is not a draft; it is the
  server's marker for an unverified item.

Note a contract-vs-code discrepancy the demo must not paper over:
the contract's `GET /followups` status list reads
`pending | approved | dismissed | sent`, but the server actually
stores and returns `needs_review` as well, and the contract's own
prose says `quote_verified: false` drafts "surface under
`status: needs_review` instead". Treat `needs_review` as a real,
fifth status. `sent` is listed in the contract but no code path in
`followthrough.py` or `routes.py` ever sets it (delivery is a stretch
goal); do not demo a `sent` state unless Resend lands.

## 6. Contract surface used (verified field-for-field)

Base: contract says `https://api.helloscene.xyz/api/v1` ("replace with
the hackathon deploy URL; the paths and shapes do not change"). The
prototype takes the base from `SCENE_API_BASE` and defaults to that
contract URL. On LAN demo day the deploy URL is the Mac's address
with the same `/api/v1` prefix.

| Call | Request | Response (verified) |
|---|---|---|
| `GET /api/v1/facts?actor=&limit=` | Query params only | `200 {"facts": [{"id", "text", "scene_id", "actors", "extracted_at"}]}`. REST has NO `query` param (MCP `get_facts` does); filter keywords client-side. |
| `GET /api/v1/scenes/{id}` | Path id | `200` scene detail incl. `transcript: [{speaker, text, start_ts, end_ts}]`, `people`, `start_ts`, `end_ts`. Unknown id → `404 scene_not_found`. |
| `POST /api/v1/followups/generate` | `{"session_id": "uuid"}` or `{}` | `202 {"run_id", "status": "running", "steps": ["find_promises", "verify_quotes", "draft_followups"]}`. Bad JSON body → `400 bad_request`. |
| `GET /api/v1/followups?run_id=&status=` | Both params optional | `200 {"followups": [{"id", "run_id", "promise", "person", "quote", "quote_verified", "verified_at", "draft", "status", "scene_id"}]}`. `status` filters server-side; omit it to see `needs_review` items too. |
| `POST /api/v1/followups/{id}/approve` | Empty body (body discarded) | `200 {"id", "status": "approved"}`; `needs_review` or unverified pending → `400 not_approvable`; unknown id → `404 followup_not_found`. Human tap only. |
| `POST /api/v1/followups/{id}/dismiss` | Empty body | `200 {"id", "status": "dismissed"}`; unknown id → `404 followup_not_found`. Human tap only. |

Error envelope everywhere (verified): `{"error": {"code": "...",
"message": "..."}}`. Unknown route → `404 not_found`.

Endpoints that do NOT exist (verified by reading `routes.py`; do not
invent them): `POST /followups` (create a draft), `PATCH /followups/{id}`
(edit a draft), `GET /followups/runs/{id}` (run status), any send /
deliver endpoint. The prototype's design works around all four
absences instead of assuming them.

## 7. Bearer auth

Server rules, verified in `routes.check_auth`:

- Auth is behind the `AUTH_ENABLED` env flag, default OFF. OFF means
  every request passes (dev behavior, keeps existing tests green).
- ON means: require `Authorization: Bearer <token>` exactly matching
  the `SCENE_API_TOKEN` env var. The `Bearer ` prefix match is
  case-insensitive and surrounding whitespace is stripped; the token
  itself is compared exactly.
- Fail-closed: if `AUTH_ENABLED` is on but `SCENE_API_TOKEN` is
  unset/empty, the server refuses ALL requests (with a warning) rather
  than falling back to open. Missing or wrong header → `401
  unauthorized`, "Token expired, re-pair."
- The WebSocket `?token=` query param is deliberately NOT checked by
  this function; it is out of scope here and the prototype does not
  use the socket.

Prototype token rules `[PROTOTYPE POLICY]`:

- The token comes from exactly one place: the `SCENE_API_TOKEN`
  environment variable, read at process start. It is never hardcoded,
  never committed, never printed, never logged, and never embedded in
  the Managed Agents prompt or in sandbox files. The prompt tells the
  agent the API base URL only; authentication happens in the
  prototype's HTTP layer, outside the sandbox.
- The prototype redacts the `Authorization` header in every log line
  and error message (it logs the presence of a token, never its
  value). Token comparison, if ever done client-side, is exact and
  constant-adjacent; in practice the server is the comparator.
- Live mode (non-dry-run) refuses to start without
  `SCENE_API_TOKEN` set, unless `--allow-no-token` is passed
  explicitly for a local server known to run with `AUTH_ENABLED` off.
  This is stricter than the server default, on purpose: a demo-day
  mistake should fail loudly before the run, not mid-demo with a 401.
- On a 401 the prototype aborts the run, reports "token expired,
  re-pair" (the server's wording), and does NOT retry, rotate, or
  fetch a replacement token. Re-pairing is a phone-app action.
- `[UNVERIFIED — DO NOT CLAIM]` Secondary write-ups describe a
  Managed Agents credentials/egress-proxy model in which secrets never
  enter the sandbox. That was not verified against official docs in
  this task, so this design does not rely on it: the prototype keeps
  the token out of the sandbox by construction (the sandbox never
  makes an authenticated call; the prototype does), regardless of
  what the platform may additionally guarantee.

## 8. What the Managed Agent's prompt must contain

`MANAGED_AGENT_PROMPT` in `managed_followthrough.py` is the
copy-paste prompt for the live Managed Agents run. Its non-negotiable
clauses:

1. Tool order: `get_facts` first, then `get_scene` per promise, then
   code verification, then drafts. No step may be skipped.
2. Verification is code, not judgment: run the provided verifier
   (normalized difflib >= 0.80 + timestamp-window overlap) inside the
   sandbox and report `(verified, best_ratio)` per quote.
3. Unverified ⇒ `needs_review`, empty draft, never `pending`.
4. Nothing sends. The agent produces drafts and a run report; the
   human approves in the phone app. The agent must not call approve,
   dismiss, or any delivery tool (none exists, and it must not invent
   one).
5. Output is a JSON list in the stored follow-up shape, plus a run
   report with per-item verdicts and ratios, so judges can audit
   every decision.

## 9. Open items for Isabella (not blockers for the prototype)

1. Confirm the Managed Agents SDK call shape against the official
   Antigravity agent guide before any live run (see §2).
2. Decide whether edited draft text must persist server-side; if yes,
   that needs a new endpoint (see §3 step 4). The demo works without
   it.
3. Reconcile the contract's status list with the real `needs_review`
   status (see §5), and decide whether `sent` stays in the contract
   or is cut until Resend lands.
4. Decide whether agent-produced drafts should ever replace the
   server's canned drafts inside `generate_run`. That is a server
   change with its own review; this prototype neither requires nor
   performs it.
