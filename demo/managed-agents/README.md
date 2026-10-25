# Managed Agents prototype: Scene Follow-Through Agent

Standalone prototype for the $5,000 Best Use of Managed Agents prize
lane. Read-only on everything else: this folder is the only thing this
work writes, and it edits no server, app, contract, or bridge file.

## Files

- `DESIGN.md` — the execution design: Managed Agents execution
  (agent `antigravity-preview-09-2026`, remote sandbox), the agent
  loop (get_facts → code verification → drafts → human tap), the
  never-sends-without-a-tap guarantee, failure routing
  (verification failure ⇒ `needs_review`, never a draft), and Bearer
  auth (fail-closed, token never in repo or chat).
- `managed_followthrough.py` — reference implementation (Python,
  stdlib only, clearly-marked SDK seams). Runs the loop against the
  contract API: fetch facts, verify quotes with a code checker,
  trigger the generate endpoint, poll/wait for approval state.
  Never approves, dismisses, edits, or sends anything.
- `INTEGRATION.md` — step-by-step wiring guide for Isabella: how to
  plug this into her agent + approval screens, what she must NOT
  change (approval gate, `needs_review` 400 behavior, draft shape),
  how to test without sending anything, and the prize-lane evidence
  to show judges.

## Quick start (no server, no token, no sends)

```bash
python3 managed_followthrough.py --self-test
python3 managed_followthrough.py --dry-run
```

Expected: self-test passes; dry-run reports 3 promises, 2 `pending`
(verified), 1 `needs_review` (unverified, empty draft), `sent: []`.

Live mode (still sends nothing; triggers generate and polls only):

```bash
export SCENE_API_BASE="http://<mac-lan-ip>:8000/api/v1"
export SCENE_API_TOKEN="<token from the phone app pairing>"
python3 managed_followthrough.py --live
```

## Verified against

- `SCENE-API-CONTRACT.md` (follow-ups API surface)
- `scene-backend/app/followthrough.py` (generation + approval logic)
- `scene-backend/app/routes.py` (HTTP status codes, Bearer auth)
- `SCENE-FINAL-SPEC.md` §4.7 (Follow-Through Agent loop)

## Explicitly NOT verified (read before demoing)

- The Managed Agents SDK call shape (`client.interactions.create`,
  agent `antigravity-preview-09-2026`, `environment="remote"`) comes
  from secondary write-ups only, not official Google docs read in
  this task. It lives in a guarded seam that refuses to run until
  confirmed. See DESIGN.md §2 and INTEGRATION.md step 4.
- There is no draft-creation, draft-edit, run-status, or send
  endpoint in the verified server code. This prototype works around
  all four absences instead of inventing them. See DESIGN.md §6.
- The verification rule is fuzzy (normalized difflib >= 0.80 +
  timestamp-window overlap), not exact string match, despite the
  brief's shorthand. The prototype ports the server rule verbatim so
  the two verdicts agree. See DESIGN.md §3 step 2.

## Constraints honored

- New files only, in this folder. No device calls, no git commands,
  no commits or pushes, no edits to existing code.
- No keys or credentials in any file (placeholders only; the token
  comes from `SCENE_API_TOKEN` at runtime and is never logged).
- No live Argon calls, no server starts.
