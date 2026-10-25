# INTEGRATION.md: wiring this prototype into Isabella's agent + approval screens

Audience: Isabella (owns the Follow-Through Agent pipeline and the
approval screens). This prototype is standalone on purpose: nothing
here edits her code, and she integrates it by copying the pieces she
wants, in the order below. Stop at any step and the previous state
still works; no step is load-bearing on the next.

## 0. What you are getting (and what you are not)

Getting:

- A Managed Agents execution design (DESIGN.md) with the exact agent
  loop, verification rule, approval guarantee, failure routing, and
  auth rules, all verified against the contract doc and the server code.
- A runnable reference implementation
  (`managed_followthrough.py`, stdlib only) that runs the loop in
  dry-run mode with zero network, zero token, and zero sends.
- The exact prompt text (`MANAGED_AGENT_PROMPT`) to hand to a Managed
  Agents run, independent of which SDK call launches it.

NOT getting, by design:

- No change to `FollowThroughService`, `routes.py`, the store, the
  API contract, the phone app, or the lens. No commit, no push.
- No per-draft submit endpoint, no edit endpoint, no run-status
  endpoint, no send/delivery path. None of those exist in the verified
  server code, and this prototype does not invent them (see DESIGN.md
  §6 for the full absent-endpoint list).
- No live Managed Agents run. The SDK call shape is a guarded,
  explicitly unverified seam (step 4 below).

## 1. Step-by-step wiring

### Step 1 — Run the prototype untouched (5 minutes, no risk)

From this folder:

```bash
python3 managed_followthrough.py --self-test
python3 managed_followthrough.py --dry-run
```

Expected output: self-test passes; dry-run reports 3 promises,
2 `pending` (verified, ratio 1.0), 1 `needs_review` (ratio ~0.35,
empty draft), `sent: []`, and all local-vs-stored verdicts agreeing.
If any of that differs, stop: the prototype disagrees with the server
rule, and that disagreement is the bug to fix first.

### Step 2 — Point it at the real server (read + generate only)

```bash
export SCENE_API_BASE="http://<mac-lan-ip>:8000/api/v1"
export SCENE_API_TOKEN="<token from the phone app pairing>"
python3 managed_followthrough.py --live
```

What this does: `GET /facts`, `POST /followups/generate`,
`GET /followups?run_id=`. What it does NOT do: approve, dismiss,
edit, or send anything — the client has no such methods, so it cannot
do those things even by accident. Live mode refuses to start without
`SCENE_API_TOKEN` unless `--allow-no-token` is passed (for a local
server known to run with `AUTH_ENABLED` off).

Compare its stored results with the phone app's list for the same
`run_id`. They must match field-for-field; the stored drafts are the
server's, and the prototype's local verdicts are an audit of them.

### Step 3 — Give the Managed Agent its prompt

Copy `MANAGED_AGENT_PROMPT` verbatim into the Managed Agents run's
input. It encodes the non-negotiable clauses: `get_facts` first, then
`get_scene` per promise, code verification in the sandbox (normalized
difflib >= 0.80 + timestamp-window overlap), unverified ⇒
`needs_review` with empty draft, never `pending`, and nothing sends.

The agent's output is a JSON list in the stored follow-up shape plus
a run report with per-item `(verified, best_ratio)` verdicts. That
report is the audit trail: keep it, show it, do not summarize it away.

### Step 4 — Confirm the SDK seam before any live agent run

`launch_managed_agent()` refuses to run by default, on purpose. Before
calling it with `confirm_sdk_shape=True`:

1. Confirm `client.interactions.create(agent="antigravity-preview-09-2026",
   input=..., environment="remote")` against the official Antigravity
   agent guide. The shape in this prototype comes from secondary
   write-ups only and is marked `[UNVERIFIED]` everywhere it appears.
2. Confirm the `google-genai` package version the guide requires.
3. Confirm whether a model-selection key is needed at all. The 09-2026
   preview's reported default is Gemini 3.8 Flash; Scene's Argon
   reasoning is a separate layer and is not routed through this agent.
   Do not guess an `agent_config` key.

Until step 4 is done, the honest demo framing is: "Managed Agents
prompt + sandbox verifier design, running locally as a prototype;
live SDK launch pending official-shape confirmation." Do not demo the
seam as a live run before then.

### Step 5 — Connect the approval screens (no server change)

The phone screens already own approve/dismiss:

- `POST /api/v1/followups/{id}/approve` → `200 {id, status: approved}`
- `POST /api/v1/followups/{id}/dismiss` → `200 {id, status: dismissed}`

Wire the screens to poll `GET /api/v1/followups?run_id=<id>` with NO
`status` filter for the agent's own view (so `needs_review` items are
visible to the team), and with `?status=pending` for the user's
approval queue (so unverified items are never shown for approval).
The prototype's `--wait-for-human` path models exactly this wait: it
polls until pending items reach `approved`/`dismissed` and reports a
timeout as "still awaiting human tap" rather than deciding anything.

### Step 6 (optional, later, your call) — agent drafts into the server

If you ever want agent-produced drafts to replace the server's canned
drafts inside `generate_run`, that is a server change with its own
review, not part of this prototype. The seam is clean: the agent's
output JSON already matches the stored follow-up shape, so the server
change would be "accept agent output as the draft source" rather than
a shape migration. Do not do this during the demo window unless the
current server behavior is demonstrably blocking the demo; the
canned-plus-verified path already produces the right stored states.

## 2. What you must NOT change

These are verified server behaviors. Changing any of them breaks the
guarantee the prize lane is judged on, or breaks the phone app's
assumptions:

1. **The approval gate.** `needs_review` approve ⇒ HTTP `400`
   `not_approvable`. Pending-with-unverified-quote approve ⇒ also
   `400 not_approvable`. Do not "fix" this to a silent skip or to a
   success; the 400 IS the guarantee, and the demo shows it.
2. **The needs_review routing.** Verification failure ⇒ stored
   `status: needs_review`, `quote_verified: false`,
   `verified_at: null`, `draft: ""`. Never promote a failed item to
   `pending`, never fill in draft text for it, never show it in the
   approval queue.
3. **The draft shape.** Stored follow-up fields, exactly:
   `id, run_id, promise, person, quote, quote_verified, verified_at,
   draft, status, scene_id`. Do not rename, drop, or add required
   fields without updating the contract doc and every consumer.
4. **The verification rule.** Normalized difflib >= 0.80 plus
   timestamp-window overlap (DESIGN.md §3 step 2). In particular, do
   NOT tighten it to exact string match without changing the server
   too: the two verdicts must agree, and exact-only is stricter than
   the server on real data.
5. **The approve-from-other-statuses behavior.** Approve from a status
   other than `needs_review` sets `approved` (mock parity, idempotent).
   It is NOT a pending-only gate. Do not describe it as one to judges,
   and do not tighten it mid-demo without checking the phone app's
   retry behavior.
6. **Auth fail-closed.** `AUTH_ENABLED` on + `SCENE_API_TOKEN` unset
   ⇒ server refuses everything. Do not "fix" this to open access.
   On the client, the token lives only in `SCENE_API_TOKEN`, is never
   logged, never committed, never put in the agent prompt or sandbox
   files. A 401 means "token expired, re-pair" via the phone app; it
   is never retried with a different token by code.
7. **No send path.** Do not add Resend/delivery to this prototype or
   to the approval flow during the demo unless it is separately
   reviewed. Demo floor is the `approved` state, per the contract.

## 3. How to test without sending anything

Everything below sends nothing, because nothing in this stack can
send: there is no send endpoint and no send code.

### Test A — dry-run mode (no server, no token)

```bash
python3 managed_followthrough.py --self-test
python3 managed_followthrough.py --dry-run
```

Pass criteria: self-test passes; dry-run shows 2 pending / 1
needs_review, `sent: []`, all verdicts agreeing. This is the
zero-risk rehearsal: run it in front of judges if the network dies.

### Test B — approve gate test (live server, human tap only)

1. Run `--live` to get a `run_id`.
2. In the phone app (or with a manual curl from the demo machine),
   approve a `pending` item → expect `200 {status: approved}`.
3. Attempt to approve a `needs_review` item → expect `400`
   `not_approvable` with the message "Unverified drafts are never
   approved; they stay under needs_review."
4. Attempt to approve a made-up id → expect `404 followup_not_found`.

Pass criteria: all three status codes, in that order, with no state
change on the `needs_review` item (re-poll it: still `needs_review`,
still empty draft). This test IS the guarantee, demonstrated.

### Test C — needs_review test (live server)

1. Trigger generate and poll `GET /followups?run_id=<id>` with no
   `status` filter.
2. Confirm every item with `quote_verified: false` has
   `status: needs_review` and `draft: ""`.
3. Confirm the approval queue (`?status=pending`) contains none of
   them.

Pass criteria: zero unverified items in the pending queue, zero
non-empty drafts on unverified items. If either check fails, the
failure routing is broken; do not demo past it.

### Test D — auth test (live server, auth on)

1. With `AUTH_ENABLED` on and a correct token, `--live` succeeds.
2. With a wrong or missing token, the run aborts on `401
   unauthorized` ("Token expired, re-pair") and does not retry.
3. With `AUTH_ENABLED` on and `SCENE_API_TOKEN` unset server-side,
   every request is refused (fail closed).

Pass criteria: 401 aborts cleanly with no token value in any log line
(check the output: only `token_present=true/false` is ever printed).

## 4. Prize-lane evidence: what to show judges

The $5,000 Best Use of Managed Agents lane is won on evidence, not
claims. Show these four artifacts, in this order, as one continuous
beat (the demo's closing beat, per spec §4.7):

1. **The agent run.** The Managed Agents job (prompt + sandbox) doing
   real work: `get_facts` → today's promises, `get_scene` →
   transcripts. If the live SDK launch is not yet confirmed (step 4),
   show the prompt + the dry-run loop and say so plainly; a claimed
   live run that is actually local is worse than an honest prototype.
2. **The verification.** The sandbox code verdicts, per item, with
   ratios: e.g. Q3 quote ratio 1.0 → verified; demo-leads quote
   ratio 1.0 → verified; demo-link quote ratio ~0.35 → fails the
   0.80 threshold → `needs_review`. The point to land: "the LLM
   proposed; the code disposed." Show a failing case, not just passes.
3. **The approval tap.** A `pending` draft in the phone app, the
   human tapping Approve, the state flipping to `approved` — and the
   `needs_review` item visibly NOT in the approval queue. Then the
   gate test (Test B, step 3): attempting to approve the
   `needs_review` item returns `400 not_approvable`. That 400 is the
   most persuasive 10 seconds of the demo.
4. **The nothing-sent line.** Close with it, verbatim: "Scene doesn't
   just remember what you promised. It makes sure you follow through
   — and nothing sends without a tap." Then, if asked what sent:
   "Nothing. Approve only flips status; delivery is a stretch goal."

Keep the run report (the prototype's JSON output) open during the
demo. It is the audit trail that turns "the agent did it" into "here
is every decision, with its evidence, and here is the human gate after
it."

## 5. Known gaps (say them before judges find them)

- The Managed Agents SDK call shape is unverified (secondary sources
  only); live launch needs official-guide confirmation.
- There is no edit-persistence endpoint: phone-side edits before
  approve do not persist server-side via any verified API.
- There is no run-status endpoint: poll the follow-ups list, not a
  run object (the 202 body says `running` even after synchronous
  completion).
- `sent` is a contract-listed status no code path ever sets; do not
  demo a sent state until delivery actually lands.
- The contract's status list omits `needs_review`, but the server
  really stores it. Treat `needs_review` as real (it is).
- Agent-produced drafts are not stored by the server today; the
  server's canned generation is the stored source of truth. The
  prototype audits it; it does not replace it.
