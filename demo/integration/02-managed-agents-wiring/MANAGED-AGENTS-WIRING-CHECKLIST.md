# Managed Agents wiring checklist for Isabella: Scene Follow-Through Agent

Audience: Isabella, who owns the Follow-Through Agent plus its approval screens and does the integration herself.
Scope: this is a GUIDE only. It edits nothing. It does not touch the running backend, Isabella's files, the API contract, the bridge, or the repo.
Demo backend: Nayan's `src/backend/` on his Mac, reached over LAN. Demo phone: Isabella's. Feature freeze 7:30 PM PDT, submission 10:00 PM PDT, Sun Oct 25 2026.

Sources this guide is grounded in (read, not modified):
- `~/workspace/scene-fix-swarm/managed-agents/DESIGN.md`, `INTEGRATION.md`, `managed_followthrough.py` (the standalone prototype)
- `~/workspace/your_files/scene-final-spec/SCENE-API-CONTRACT.md` (the frozen API contract)

What the prototype is, in one paragraph: a standalone client of the contract API that re-runs find_promises -> verify_quotes -> draft_followups against the public API and audits the server's stored verdicts. It never writes a draft to the server, never approves, never dismisses, never sends. The server's `POST /followups/generate` remains the sole source of stored drafts. The Managed Agents piece is one guarded seam, `launch_managed_agent()` in `managed_followthrough.py`, whose SDK call shape is UNVERIFIED (secondary write-ups only, not official Google docs). Do not demo that seam as a live run until step 1 below is done.

LAN base URL for demo day (same `/api/v1` paths as the contract, different host):
- `http://10.1.63.33:8000/api/v1`
- Confirm the Mac IP is still 10.1.63.33 before you start. If it moved, use the current LAN IP and keep the `/api/v1` suffix unchanged.
- No token value appears anywhere in this guide. The token comes from the phone app pairing at runtime only, via the `SCENE_API_TOKEN` environment variable, and is never logged, printed, committed, or put in the agent prompt or sandbox files.

Verification rule, stated once so the rest of the guide is unambiguous: the server rule is FUZZY, not exact string match. Normalize (lowercase, collapse every non-alphanumeric run to one space), score with `difflib.SequenceMatcher.ratio` against each transcript line and the joined segment, pass at best ratio >= 0.80 plus timestamp-window overlap of the best line with the scene window. An exact normalized match scores 1.0 and passes, but an exact-only checker is stricter than the server and will diverge on real data. Do not tighten either side to exact match without changing both and telling the other owner first.

---

## 1. SDK shape confirmation FIRST: do this before writing any wiring code

This step gates everything after it. The prototype's Managed Agents call shape is unverified. Writing wiring code against an unconfirmed shape wastes the demo window and risks a claimed live run that is actually local.

### 1a. What exactly to confirm against the official Managed Agents guide

Open the official Managed Agents / Antigravity agent guide (Google's own docs for the Gemini API Managed Agents offering, not a blog post, tutorial, or secondary write-up) and confirm each item below, in writing, before proceeding:

1. The client and entry point: is the launch call really `client.interactions.create(...)` on a `google-genai` client, or is the entry point named differently (for example a sessions, agents, or runs resource)?
2. The agent identifier: is `antigravity-preview-09-2026` the correct agent value, and is it passed as `agent=`, or under a different parameter name?
3. The input parameter: is the prompt passed as `input=`, and does it accept a plain string (the prototype's `MANAGED_AGENT_PROMPT`) or a structured message list?
4. The sandbox parameter: is `environment="remote"` the correct value and parameter name for a hosted remote sandbox, and are there other required parameters (for example timeout, tool declarations, or workspace config)?
5. The `google-genai` package version the guide requires, and how the client is authenticated (API key source) without putting any secret in the prompt or sandbox files.
6. Whether a model-selection key exists at all (the prototype deliberately uses none). The 09-2026 preview's reported default is Gemini 3.8 Flash. Scene's Argon reasoning is a separate layer and is NOT routed through this agent. Do not guess an `agent_config` key.
7. How to read the run result back: what the returned object is called, what field holds the agent's output text (the prototype reads `output_text` as a fallback), how to poll or stream a run that has not finished, and how a run failure surfaces.
8. The tool surface the agent gets in the sandbox: how `get_facts` and `get_scene` (the contract's read-only MCP tools) are exposed to the agent, and confirmation that the agent has no approve, dismiss, edit, or send tool and cannot invent one.

### 1b. The guarded seam: what to do if the guide disagrees with the prototype

The prototype already implements the correct behavior: `launch_managed_agent()` refuses to run unless called with `confirm_sdk_shape=True` AND the `google-genai` package imports. Keep that guard. Do not remove it, bypass it, or set the flag from habit.

- If the guide CONFIRMS the prototype shape exactly: update the seam to the confirmed call, keep the flag as a deliberate opt-in for one more run, run `--self-test` first, then run the live launch once against the LAN backend and capture the output (see section 4).
- If the guide DISAGREES in any parameter name, value, or entry point: stop. Do not adapt the wiring steps below to the old shape. Rewrite only the seam function to the guide's shape, keep `MANAGED_AGENT_PROMPT` verbatim (the prompt is final and independent of the SDK shape), re-run `--self-test`, and re-verify the no-send tests in section 3 before any demo use. Record the confirmed shape (guide URL, package version, exact call) at the top of your integration notes so the next person does not re-derive it from secondary sources.
- If the guide is UNREACHABLE or ambiguous before feature freeze: do not launch. Fall back to the honest demo framing, verbatim: "Managed Agents prompt plus sandbox verifier design, running locally as a prototype; live SDK launch pending official-shape confirmation." Show the prompt, the dry-run loop, and the verification ratios (section 4, fallback path). A claimed live run that is actually local is worse than an honest prototype, and judges can tell.

### 1c. Gate checklist (all must be yes before section 2, step 4)

- [ ] Official guide opened and the 8 items in 1a confirmed or corrected in writing
- [ ] `google-genai` package version from the guide installed in the environment that will run the demo
- [ ] `launch_managed_agent()` still refuses without explicit confirmation (guard intact)
- [ ] `MANAGED_AGENT_PROMPT` copied verbatim, with no token, no secret, and no API base URL with credentials in it (base URL alone is fine; auth stays in the prototype HTTP layer, outside the sandbox)

---

## 2. Wiring steps, in order

Work in this order. Stop at any step and the previous state still works. No step depends on a later step. Do not wire blindly past a failing step: a failure here is the bug to fix, not something to demo around.

### Step 0: Rehearse with zero risk (5 minutes, no server, no token)

From the prototype folder (`~/workspace/scene-fix-swarm/managed-agents/`):

```bash
python3 managed_followthrough.py --self-test
python3 managed_followthrough.py --dry-run
```

Expected: self-test passes; dry-run reports 3 promises, 2 `pending` (verified, ratio 1.0), 1 `needs_review` (ratio about 0.35, empty draft), `sent: []`, and all local vs stored verdicts agreeing. If any of that differs, stop: the prototype disagrees with the server rule, and that disagreement is the bug to fix first. This dry-run is also your network-dead fallback for the demo.

### Step 1: Point the prototype at the real LAN backend (read plus generate only)

```bash
export SCENE_API_BASE="http://10.1.63.33:8000/api/v1"
export SCENE_API_TOKEN="<token from the phone app pairing>"
python3 managed_followthrough.py --live
```

What this does: `GET /facts`, `POST /followups/generate`, `GET /followups?run_id=`. What it does NOT do: approve, dismiss, edit, or send anything. The prototype client (`SceneClient`) exposes only those four methods, so it cannot approve even by accident. Live mode refuses to start without `SCENE_API_TOKEN` unless `--allow-no-token` is passed explicitly, and that flag is only for a local server known to run with auth off. Do not pass it on demo day unless you have confirmed auth is off on the running backend.

Compare the prototype report with the phone app's list for the same `run_id`. They must match field-for-field on `id, run_id, promise, person, quote, quote_verified, verified_at, draft, status, scene_id`. The stored drafts are the server's; the prototype's local verdicts are an audit of them. Agreement is demo evidence; disagreement is a bug report, never a silent override.

Bearer auth fail-closed rules (server behavior, verified from the prototype docs; do not weaken any of these):
- Auth is behind the server's `AUTH_ENABLED` flag, default OFF. OFF means every request passes (dev behavior).
- ON means: require `Authorization: Bearer <token>` exactly matching the server token. The `Bearer ` prefix match is case-insensitive and surrounding whitespace is stripped; the token itself is compared exactly.
- Fail-closed: if auth is ON but the server token is unset or empty, the server refuses ALL requests rather than falling back to open. Do not "fix" this to open access.
- Missing or wrong header: `401 unauthorized`, message "Token expired, re-pair." On a 401, abort the run, report that wording, and do NOT retry, rotate, or fetch a replacement token. Re-pairing is a phone-app action.
- Client-side token rules: token from `SCENE_API_TOKEN` only, read at process start, never hardcoded, never committed, never printed, never logged (log only `token_present=true/false`), never embedded in the Managed Agents prompt or sandbox files. The sandbox never makes an authenticated call; the prototype's HTTP layer does, outside the sandbox.

### Step 2: Give the Managed Agent its prompt (only after section 1 is done)

Copy `MANAGED_AGENT_PROMPT` verbatim into the Managed Agents run's input. Its non-negotiable clauses:
1. Tool order: `get_facts` first, then `get_scene` per promise, then code verification, then drafts. No step skipped.
2. Verification is code, not judgment: run the provided verifier in the sandbox (normalized difflib >= 0.80 plus timestamp-window overlap) and report `(verified, best_ratio)` per quote.
3. Unverified means `needs_review`, empty draft, never `pending`.
4. Nothing sends. The agent produces drafts and a run report; the human approves in the phone app. The agent must not call approve, dismiss, or any delivery tool (none exists, and it must not invent one).
5. Output is a JSON list in the stored follow-up shape, plus a run report with per-item verdicts and ratios, so judges can audit every decision.

Keep that run report. Do not summarize it away. It is the audit trail for section 4.

### Step 3: Wire the server run trigger and polling (the contract endpoints)

These are the only follow-up endpoints that exist. Wire exactly these, in this order:

1. Trigger: `POST /api/v1/followups/generate` with `{"session_id": "<uuid>"}` or `{}` (empty object; omitted `session_id` means today's session).
   - Response: `202 {"run_id": "<uuid>", "status": "running", "steps": ["find_promises", "verify_quotes", "draft_followups"]}`.
   - Quirk you must code around: the server runs synchronously and marks the stored run done, but still returns `status: "running"` in the 202 body. Clients must NOT wait for a run-status transition. There is no run-status endpoint to poll (see section 6).
   - Bad JSON body: `400 bad_request`.
2. Poll for results: `GET /api/v1/followups?run_id=<run_id>` with NO `status` filter for the agent/team view, so `needs_review` items are visible too. Recommended: 2 second interval, 30 second timeout, stop as soon as the list is non-empty. Poll the follow-ups list, not a run object.
3. Agent view vs approval queue (two different filters on the same endpoint):
   - Agent/team view: `GET /followups?run_id=<id>` (no status filter) so `needs_review` items are visible to the team.
   - User approval queue: `GET /followups?run_id=<id>&status=pending` so unverified items are never shown for approval.
4. Supporting reads the agent loop needs (read-only, no mutations):
   - `GET /api/v1/facts?limit=50` (optional `?actor=<name>`). Contract default limit is 20; pass an explicit limit. Note: REST `GET /facts` has NO `query` param (MCP `get_facts` does); filter keywords client-side. Filter to promises/commitments/decisions with the regex `\b(promis|commit|decid)` case-insensitive on fact text, dedupe by fact id. A fact without a `scene_id` cannot be verified and routes to `needs_review`.
   - `GET /api/v1/scenes/{id}` for the transcript (`transcript: [{speaker, text, start_ts, end_ts}]`, plus `start_ts`/`end_ts` for the scene window). Unknown id: `404 scene_not_found`.
5. Error envelope everywhere: `{"error": {"code": "...", "message": "..."}}`. Unknown route: `404 not_found`.

### Step 4: Connect the approval screens (no server change)

The phone screens already own approve/dismiss. Wire them to the contract endpoints, human tap only:

- Approve: `POST /api/v1/followups/{id}/approve`, empty body (body is discarded). Success: `200 {"id": "<uuid>", "status": "approved"}`. This only flips status. It sends nothing.
- Dismiss: `POST /api/v1/followups/{id}/dismiss`, empty body. Success: `200 {"id": "<uuid>", "status": "dismissed"}`.
- Unknown id on either: `404 followup_not_found`.
- The prototype itself must never call approve or dismiss. If your integration code gains an approve/dismiss method for any reason other than a direct human tap handler, remove it before the demo. The demo script path is: agent run, verification log, stored drafts, human tap in the phone app, approved state shown.
- After a tap, re-poll `GET /followups?run_id=<id>` (no status filter) and show the updated state. Pending items that never get a tap stay pending; report them as "awaiting human decision" and change nothing about them.
- Approve-from-other-statuses behavior (do not misdescribe it): approve from a status other than `needs_review` sets `approved` (mock parity, idempotent). It is NOT a pending-only gate. Do not describe it as one to judges, and do not tighten it mid-demo without checking the phone app's retry behavior.

### Step 5 (optional, later, your call only): agent drafts into the server

If you ever want agent-produced drafts to replace the server's canned drafts inside `generate_run`, that is a server change with its own review, not part of this prototype and not part of this wiring. The seam is clean (the agent's output JSON already matches the stored follow-up shape), but do not do this during the demo window unless the current server behavior is demonstrably blocking the demo. The canned-plus-verified path already produces the right stored states. Skip this step if anything else is still unproven; it is the first thing to cut under time pressure.

### Wiring order, condensed (the checklist to tick off in order)

- [ ] 0. `--self-test` passes, `--dry-run` shows 2 pending / 1 needs_review / `sent: []`
- [ ] 1. Section 1 SDK confirmation done in writing (gate for step 2 of this list, not an afterthought)
- [ ] 2. `--live` against the LAN backend returns a `run_id`; phone app list matches field-for-field for that `run_id`
- [ ] 3. `MANAGED_AGENT_PROMPT` copied verbatim into the Managed Agents run (after SDK confirmation)
- [ ] 4. `POST /followups/generate` then `GET /followups?run_id=` polling works; no waiting on a run-status transition
- [ ] 5. Approval queue uses `?status=pending`; agent view uses no status filter; approve/dismiss wired to human taps only
- [ ] 6. Section 3 no-send tests all pass (below)
- [ ] 7. Section 4 evidence captured in order (below)
- [ ] 8. (Optional, only if time remains) server change for agent drafts, separately reviewed; otherwise skipped

---

## 3. No-send tests: exact tests proving nothing sends without a tap

Everything below sends nothing, because nothing in this stack can send: there is no send endpoint and no send code. Run all four tests before the demo. If any fails, do not demo past it.

### Test A: dry-run mode (no server, no token, zero risk)

```bash
python3 managed_followthrough.py --self-test
python3 managed_followthrough.py --dry-run
```

Pass criteria, all required:
- Self-test passes (verifier, draft shape, fake loop, SDK seam guarded).
- Dry-run shows 3 promises, 2 `pending` (verified, ratio 1.0), 1 `needs_review` (ratio about 0.35, empty draft).
- `sent: []` in the report, and the fake transport's `sent` list is empty.
- All local vs stored verdicts agree.
- `launch_managed_agent()` with no confirmation raises the unverified-seam refusal (it must refuse by default).
- This is the zero-risk rehearsal: run it in front of judges if the network dies.

### Test B: approve gate test (live server, human tap only)

1. Run `--live` to get a `run_id`.
2. In the phone app (or with a manual request from the demo machine), approve a `pending` item. Expect `200 {"id": "<uuid>", "status": "approved"}`.
3. Attempt to approve a `needs_review` item. Expect `400` with error code `not_approvable` and message "Unverified drafts are never approved; they stay under needs_review."
4. Attempt to approve a made-up id. Expect `404 followup_not_found`.
5. Attempt to approve a pending item whose quote is unverified (if you can construct one). Expect the same `400 not_approvable` as step 3.

Pass criteria, all required, in that order: `200`, then `400 not_approvable`, then `404 followup_not_found`. After step 3, re-poll the `needs_review` item: it must still be `needs_review`, still `quote_verified: false`, still `verified_at: null`, still `draft: ""`. No state change on the failed approve. This test IS the guarantee, demonstrated. The 400 is not a bug to fix; do not "fix" it to a silent skip or a success.

### Test C: needs_review routing test (live server)

1. Trigger generate and poll `GET /followups?run_id=<id>` with NO `status` filter.
2. Confirm every item with `quote_verified: false` has `status: needs_review` and `draft: ""`.
3. Confirm the approval queue (`GET /followups?run_id=<id>&status=pending`) contains none of them: zero unverified items in the pending queue, zero non-empty drafts on unverified items.
4. Confirm the seeded failing case behaves as expected: the demo-link quote ("I'll drop the link somewhere") matches no transcript line at >= 0.80 and lands in `needs_review`, while the Q3 and demo-leads quotes verify at ratio 1.0 and land in `pending`.

Pass criteria: zero unverified items in the pending queue, zero non-empty drafts on unverified items, and the failing case visible as `needs_review` (not hidden). If either check fails, the failure routing is broken; do not demo past it.

### Test D: no approve/dismiss/send methods test (code inspection plus auth test)

Code inspection (do this by reading, not by trusting a summary):
- [ ] The prototype client (`SceneClient`) exposes only `GET /facts`, `GET /scenes/{id}`, `POST /followups/generate`, `GET /followups`. Confirm there is no approve, dismiss, edit, send, email, or Resend method anywhere in `managed_followthrough.py`.
- [ ] Your integration code adds no approve/dismiss/send call except a direct human tap handler in the approval screens. Search your diff for approve, dismiss, send, email, and Resend; every hit must trace to a tap handler or to a test expectation, never to an automatic path.
- [ ] No send endpoint exists in the contract or the server routes. The only follow-up mutations are approve and dismiss, both `POST` with no body semantics. Delivery via Resend is a stretch goal, not wired.

Auth test (live server, auth on):
- [ ] With auth ON and a correct token, `--live` succeeds.
- [ ] With a wrong or missing token, the run aborts on `401 unauthorized` ("Token expired, re-pair") and does not retry with a different token.
- [ ] With auth ON and the server token unset server-side, every request is refused (fail closed), not opened.
- [ ] No token value appears in any log line or error message from any of the above (check the output: only `token_present=true/false` is ever printed).

### Test E: draft-only behavior test (what "approved" does and does not do)

1. Approve a `pending` draft in the phone app, then re-poll. Expect only the status flip to `approved`. No message, email, or external delivery is triggered, because no delivery code path exists.
2. Confirm the honest answer to "what sent?" is "nothing; approve only flips status." If a judge asks, say exactly that, then add: "Delivery is a stretch goal; demo floor is the approved state."
3. Confirm no `sent` status appears in any polled list. `sent` is listed in the contract's status list but no code path ever sets it (see section 6). Do not demo a `sent` state.

Pass criteria: approved state shown, nothing delivered, no `sent` status anywhere, and the team can state the nothing-sent line without hedging.

---

## 4. Prize-lane evidence sequence: what proves Managed Agents usage to judges

Lane: $5,000 Best Use of Managed Agents. The lane is won on observable evidence, not claims. Show these four artifacts in this order, as one continuous beat, as the demo's closing beat. Keep the run report (the prototype's JSON output) open during the demo; it is the audit trail that turns "the agent did it" into "here is every decision, with its evidence, and here is the human gate after it."

### Beat 1: the agent run (show the agent doing real work)

Show, in order:
- The Managed Agents job itself: the prompt (`MANAGED_AGENT_PROMPT`) plus the remote sandbox session, if the live SDK launch is confirmed (section 1).
- The tool calls in order: `get_facts` returning today's promises, then `get_scene` per promise returning transcripts. Name the tools out loud; they are the contract's read-only MCP tools.
- Fallback path if the SDK shape is not yet confirmed: show the prompt plus the dry-run loop and say plainly, "Managed Agents prompt plus sandbox verifier design, running locally as a prototype; live SDK launch pending official-shape confirmation." Do not present the dry-run as a live run.

Capture: a screenshot or screen recording of the agent job and its tool calls, plus the saved run report JSON.

### Beat 2: the verification (show code disposing, including a failure)

Show the sandbox code verdicts, per item, with ratios. Use the seeded set because it contains a failing case, and the failing case is the persuasive part:
- Q3 quote: ratio 1.0, verified, becomes a `pending` draft.
- Demo-leads quote: ratio 1.0, verified, becomes a `pending` draft.
- Demo-link quote: ratio about 0.35, below the 0.80 threshold, fails verification, becomes `needs_review` with an empty draft.

Land this line: "The LLM proposed; the code disposed." Show the failing case, not just passes. A demo with only passes proves nothing about the gate.

Capture: the per-item `(verified, best_ratio)` lines from the run report, visible on screen, with the threshold 0.80 stated next to them.

### Beat 3: the approval tap (show the human gate, including the 400)

Show, in order:
- A `pending` draft in the phone app, the human tapping Approve, the state flipping to `approved` on re-poll.
- The `needs_review` item visibly NOT in the approval queue (show the `?status=pending` queue and the full unfiltered list side by side, so the absence is observable, not claimed).
- The gate test (Test B, step 3): attempting to approve the `needs_review` item returns `400 not_approvable` with the message "Unverified drafts are never approved; they stay under needs_review." That 400 is the most persuasive 10 seconds of the demo. Do not skip it, and do not apologize for it.

Capture: phone screen recording of the tap and the status flip, plus the 400 response visible on screen or in the log.

### Beat 4: the nothing-sent line (close with it, verbatim)

Close with this line, verbatim: "Scene doesn't just remember what you promised. It makes sure you follow through, and nothing sends without a tap."

Then, if asked what sent: "Nothing. Approve only flips status; delivery is a stretch goal."

Capture: the final polled follow-ups list showing `approved`, `dismissed` (if any), `pending` (if any still awaiting a tap), and `needs_review` items, with no `sent` status anywhere and `sent: []` in the prototype report.

### Evidence checklist (capture all of these before submission)

- [ ] Agent job screenshot or recording (or the honest prototype fallback, labeled as such)
- [ ] Run report JSON saved, with per-item verdicts and ratios
- [ ] Phone recording of the approve tap and the status flip
- [ ] Visible 400 `not_approvable` on the `needs_review` approve attempt
- [ ] Final follow-ups list with no `sent` status and `sent: []` in the report
- [ ] The nothing-sent closing line delivered

---

## 5. What Isabella must NOT change

### 5a. The API contract is frozen: flag mismatches, do not edit it

The contract at `~/workspace/your_files/scene-final-spec/SCENE-API-CONTRACT.md` is frozen. Do not edit it to match code, and do not edit code to silently match a misreading of it. If you find a mismatch, flag it to Nayan and keep both behaviors visible. Known contract-vs-code discrepancies to carry as flagged, not papered over:

- The contract's `GET /followups` status list reads `pending | approved | dismissed | sent`, but the server actually stores and returns `needs_review` as well, and the contract's own prose says `quote_verified: false` drafts "surface under `status: needs_review` instead". Treat `needs_review` as a real, fifth status.
- `sent` is listed in the contract but no code path ever sets it (delivery is a stretch goal). Do not demo a `sent` state, and do not edit the contract to remove it mid-demo without Nayan's say-so; flag it for the post-demo reconciliation instead.
- The contract's `POST /followups/generate` 202 body says `status: "running"` even though the server runs synchronously. Do not "fix" the server to return a different status mid-demo; code the client to poll the follow-ups list instead (section 2, step 3).

Other frozen behaviors (changing any of these breaks the guarantee or the phone app's assumptions):
- The approval gate: `needs_review` approve is `400 not_approvable`, and pending-with-unverified-quote approve is also `400 not_approvable`. Do not change either to a silent skip or a success.
- The `needs_review` routing: verification failure means stored `status: needs_review`, `quote_verified: false`, `verified_at: null`, `draft: ""`. Never promote a failed item to `pending`, never fill in draft text for it, never show it in the approval queue.
- The draft shape: stored follow-up fields, exactly, are `id, run_id, promise, person, quote, quote_verified, verified_at, draft, status, scene_id`. Do not rename, drop, or add required fields without updating the contract and every consumer.
- The verification rule: normalized difflib >= 0.80 plus timestamp-window overlap. Do not tighten it to exact match on one side only.
- Auth fail-closed: auth ON plus unset server token means the server refuses everything. Do not change this to open access.
- No send path: do not add Resend or delivery to this prototype or to the approval flow during the demo unless it is separately reviewed. Demo floor is the `approved` state.

### 5b. The SceneApp signing identity must not change

- Team: C9FJ8G22S9
- Bundle identifier: com.isabelladoan.sceneapp
- Do not change the team, the bundle id, or the provisioning setup to make a build work. If a build fails on signing, that is a problem to solve without changing identity: confirm who builds onto the demo phone (Isabella's device, Isabella's identity per the teammate review) and fix the build environment, not the identity. A changed identity breaks the demo phone install and wastes the window.

### 5c. Srijan's `src/backend/real-server/` is reference only

- Do NOT merge `src/backend/real-server/` into the demo backend.
- Do NOT treat it as the demo backend, do NOT run the demo from it, and do NOT copy its routes or store into Nayan's backend during the demo window.
- The demo backend is Nayan's `src/backend/`. Srijan's parallel real backend duplicates it, and which backend runs the demo was resolved in favor of Nayan's `src/backend/` (teammate review: run Nayan's `src/backend/` for the demo, real-server is reference only, no P0 against Nayan's backend).
- If you find something useful in real-server, note it as a post-demo review item. Do not pull it in mid-demo. The same rule applies to Srijan's unmerged phone branch work: do not merge during the demo if it touches the same files as main.
- Only unmerged Srijan work noted in the teammate review is the phone branch `origin/followthrough-app-actions`; it is explicitly do-not-merge during the demo because it touches the same files as main and would clobber. Leave it alone.

---

## 6. Open gaps list: everything still unknown or unproven

Each gap names who resolves it and how. Nothing here is a reason to invent an endpoint, a parameter, or a behavior. If a gap is unresolved at feature freeze, demo around it honestly using the fallback named, and say so.

| # | Gap | Status | Who resolves it | How to resolve it |
|---|---|---|---|---|
| 1 | Managed Agents SDK call shape (`client.interactions.create`, agent `antigravity-preview-09-2026`, `environment="remote"`) | UNVERIFIED: secondary write-ups only, not official docs | Isabella, before any live agent run | Section 1: confirm all 8 items against the official Managed Agents / Antigravity agent guide; rewrite only the guarded seam if the guide disagrees; keep the refusal guard until confirmed |
| 2 | `google-genai` package version the official guide requires | UNVERIFIED: not confirmed in the prototype task | Isabella, with gap 1 | Read the version from the official guide; install exactly that version in the demo environment; record it in integration notes |
| 3 | Model-selection key for the Managed Agents agent (whether one is needed, and its name) | UNVERIFIED: prototype deliberately uses none; reported default is Gemini 3.8 Flash | Isabella, with gap 1 | Confirm from the official guide whether a key is needed at all; do not guess an `agent_config` key; Argon is a separate layer and is not routed through this agent |
| 4 | How the Managed Agents agent receives the `get_facts` / `get_scene` tool surface, and how its output text and run status are read back | UNVERIFIED: prototype reads `output_text` as a fallback | Isabella, with gap 1 | Confirm tool exposure, output field, and polling/streaming behavior from the official guide; adapt only the seam, not the prompt |
| 5 | Whether a Managed Agents credentials or egress-proxy model keeps secrets out of the sandbox | UNVERIFIED: described in secondary write-ups, not verified, not relied on | Nobody needs to resolve this for the demo | The prototype already keeps the token out of the sandbox by construction (auth happens in the prototype HTTP layer, outside the sandbox); do not claim a platform guarantee you have not verified |
| 6 | Draft-create endpoint (`POST /followups`, create a single draft) | ABSENT: verified by reading the server routes; does not exist | Isabella, only if agent drafts must be stored (post-demo or separately reviewed server change) | Do not invent it. For the demo, the server's `generate_run` is the sole source of stored drafts; the prototype's own drafts are its working output and audit report only |
| 7 | Draft-edit endpoint (`PATCH /followups/{id}` or equivalent, persisting edited draft text server-side) | ABSENT: contract and routes have none; approve/dismiss routes discard the request body | Isabella decides; Nayan owns any server change | For the demo, "edit" means the user edits draft text in the phone UI before tapping approve, as a client-side concern. If edited text must persist server-side, that needs a new endpoint, a contract update, and review; the demo works without it and must not claim edit persistence |
| 8 | Run-status endpoint (`GET /followups/runs/{id}` or similar) | ABSENT: no such endpoint in the contract or routes | Nobody for the demo; Isabella notes it for post-demo | Poll `GET /followups?run_id=` until the list is non-empty (2s interval, 30s timeout). Do not wait for a run-status transition; the 202 body says `running` even after synchronous completion |
| 9 | Send / delivery endpoint (including Resend delivery) | ABSENT: no send endpoint, no send code in the server or prototype | Stretch goal owner, post-demo, separately reviewed | Do not add it during the demo. Demo floor is the `approved` state. Do not demo a `sent` state; no code path sets `sent` today |
| 10 | `sent` as a stored status | CONTRACT-LISTED BUT UNSET: listed in the contract status list, never set by any code path | Nayan (contract owner) post-demo | Flag for contract reconciliation after the demo: either cut `sent` until delivery lands, or keep it listed as future. Do not edit the contract mid-demo |
| 11 | `needs_review` missing from the contract's status list | CONTRACT OMISSION, SERVER REALITY: server stores and returns it | Nayan (contract owner) post-demo | Treat `needs_review` as a real fifth status for the demo; flag for contract reconciliation after the demo |
| 12 | Agent-produced drafts replacing the server's canned drafts inside `generate_run` | UNDECIDED BY DESIGN: prototype audits the server's drafts, does not replace them | Isabella decides, with Nayan's review, post-demo or only if blocking | Requires a server change ("accept agent output as the draft source"); the agent output JSON already matches the stored shape, so no shape migration is needed. Do not do this during the demo window unless current server behavior demonstrably blocks the demo |
| 13 | Whether edited draft text must persist server-side at all | UNDECIDED: see gap 7 | Isabella decides | If no, the demo is complete as wired. If yes, it becomes gap 7's new-endpoint work, not a demo-day invention |
| 14 | Live Managed Agents run end to end (prompt, sandbox code execution, output JSON, run report) | UNPROVEN: no live run has been done; only the local prototype loop has run | Isabella, after gap 1 is resolved | Run the confirmed seam once against the LAN backend, capture the run report and the agent output, then run the section 3 tests against that run's `run_id` |
| 15 | Live Argon interaction with this agent (if anyone proposes routing Argon through it) | OUT OF SCOPE AND UNPROVEN: prototype makes no Argon call; Argon reasoning is a separate layer | Nobody for this wiring | Do not route Argon through the Managed Agents agent. Live Argon Ask is proven separately on the backend; keep the two layers separate in the demo narrative |
| 16 | Current LAN IP of the Mac backend at demo time | TO CONFIRM at demo time (task brief says 10.1.63.33) | Whoever starts the backend on demo day | Confirm the Mac IP before step 1 of section 2; update `SCENE_API_BASE` only, keep `/api/v1` paths unchanged |

### If time runs out: cut in this order (keep the demo honest)

1. Cut step 5 of section 2 (agent drafts into the server). It is optional.
2. Cut the live SDK launch and use the section 1 fallback framing (honest prototype, labeled as such). Keep beats 2, 3, and 4 of section 4; they do not depend on the live launch.
3. Never cut: the section 3 no-send tests, the `needs_review` 400 demonstration, or the nothing-sent closing line. Those are the prize-lane evidence.
4. Never cut by inventing: no invented endpoint, no invented parameter, no claimed live run, no claimed `sent` state, no edited contract, no changed signing identity, no merged real-server.

---

## Quick reference: endpoints used (and endpoints that do not exist)

Used (contract, verified):
- `POST /api/v1/followups/generate` (body `{"session_id": "<uuid>"}` or `{}`) -> `202 {run_id, status, steps}`
- `GET /api/v1/followups?run_id=<id>` (agent view, no status filter) and `GET /api/v1/followups?run_id=<id>&status=pending` (approval queue) -> `200 {followups: [...]}`
- `POST /api/v1/followups/{id}/approve` (empty body, human tap only) -> `200 {id, status: approved}`; `needs_review` or unverified pending -> `400 not_approvable`; unknown id -> `404 followup_not_found`
- `POST /api/v1/followups/{id}/dismiss` (empty body, human tap only) -> `200 {id, status: dismissed}`; unknown id -> `404 followup_not_found`
- `GET /api/v1/facts?limit=50` (optional `?actor=<name>`) -> `200 {facts: [...]}`
- `GET /api/v1/scenes/{id}` -> `200` scene detail with transcript; unknown id -> `404 scene_not_found`

Do NOT use (they do not exist; do not invent them):
- `POST /followups` (create a draft)
- `PATCH /followups/{id}` (edit a draft)
- `GET /followups/runs/{id}` (run status)
- Any send or deliver endpoint

No keys, tokens, or credentials appear in this guide. Placeholders only; the real token comes from the phone app pairing at runtime.
