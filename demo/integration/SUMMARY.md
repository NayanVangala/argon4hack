# Integration swarm: convergence summary

Goal: wire up everything built, in an order that does not break the working demo, to impress judges tonight. Patches and guides only. Nothing here touches the running demo directly.

Baseline (proven): backend on Nayan's Mac, live Argon Ask, Isabella's phone on LAN, Ask working. Freeze 7:30 PM, submission 10:00 PM PDT.

## What each deliverable wires

**1. Autodetect patch** (`01-autodetect-patch/PATCH.md`, `ingest-autodetect.diff`, 4 hunks, all in `app/ingest.py`)
Wires the standalone autodetect module into `IngestPipeline._run_once`, immediately after transcribe plus timestamp backfill, immediately before `analyzer.analyze`. Guarded import mirroring the critic pattern: missing module degrades to analyze-everything, never a crash. Routing: conversation and monologue to analyze; ambient and silent to mark_and_skip (minimal scene kept, same shape plus `detection_*` fields, `verified: false`, no fabricated Argon summary). Spend: skipped chunks book $0.00 instead of the flat $0.07; dashboard falls $0.07 per skip while cash saved is ~$0.019, do not quote $0.07 as cash saved. Failure defaults to analyze; clean silence becomes a stored minimal scene, never a silent drop. Two corrections vs the sketch: use `words_from_segments(segments)` (landed `detect()` needs word dicts, not strings) and leave timestamp backfill untouched (non-numeric timestamps count as unknown). Honesty: post-transcription classification only. No noise-robust VAD, no energy thresholds, no frequency filtering, no always-on listening, no recording trigger. The user still presses Record.
WARNING, prominent in the patch: re-verify the plug point against the CURRENT repo backend before applying. Srijan changed `src/backend/app/` and those changes are pending Claude audit review. Do not apply blindly to the running backend.

**2. Managed Agents wiring** (`02-managed-agents-wiring/MANAGED-AGENTS-WIRING-CHECKLIST.md`, 342 lines)
A guide for Isabella, not an edit to her code. SDK confirmation FIRST: 8 items against the official Managed Agents guide (entry point, agent id `antigravity-preview-09-2026`, input param, `environment="remote"`, google-genai version, model key, output/polling shape, tool surface). If the guide disagrees, rewrite only the guarded seam, keep the prompt verbatim, keep the refusal guard; if unreachable before freeze, use the honest fallback framing (prototype, live launch pending confirmation). Wiring order: dry-run/self-test, then `--live` against LAN with Bearer fail-closed rules, then verbatim prompt copy, then generate plus list plus read-only fact/scene reads, then tap-only approve/dismiss. No-send tests A-E: dry-run `sent: []`, approve gate (pending 200, needs_review 400, unknown 404, no state change on failed approve), needs_review routing, code inspection (4 client methods only), auth fail-closed (401 aborts, no retry, token never logged). Prize-lane evidence, four beats: agent run, verification with ratios including the failing case ("LLM proposed; code disposed"), approval tap plus visible 400 plus needs_review absent from queue, nothing-sent closing line. Must NOT change: frozen contract, SceneApp signing identity (team C9FJ8G22S9, bundle com.isabelladoan.sceneapp), real-server reference only, approval gate, verification rule (fuzzy difflib >= 0.80 plus timestamp overlap, not exact match). 16 open gaps, each with owner and resolution; cut order if time runs out: optional server change first, then live SDK launch, never the no-send tests, the 400 demo, or the nothing-sent line, never by inventing an endpoint or claim.

**3. Master wire-up sequence** (`03-wireup-sequence/MASTER-WIREUP-RUNBOOK.md`, one page, plus `FAILURE-BRANCHES.md`)
Six steps, each with exact do, test, rubric impact, and rollback. (1) Confirm working demo baseline, judged by deltas from today's baseline, not fresh-seed values. (2) Autodetect integration plus restart plus retest (back up `~/scene-backend` first, one chunk per label, failure paths default to analyze, no timeline gaps). (3) Managed Agents integration (Isabella) plus retest (2 pending / 1 needs_review, `sent: []`, approve gate 200 / 400 / 404). (4) Glasses plus band live plus retest (Dev Mode ritual, glasses WITHOUT band first per the run sheet, force-quit Meta AI, bridge order, frame proof by live preview image, session plus Record only after stream, band last with LED check, firmware 129 Back-tap warning, 30-minute rule then fall back to seeded plus chunk-upload). (5) Dashboard decision, audit FIRST: judge dashboard.html separately from the backend files, dashboard is backup only, never the demo lead, no repo-backend restage on the strength of a dashboard decision. (6) Cloud SQL go/no-go by 6:30 PM, Nayan's console work only; GO requires full end-to-end proof with time to re-prove before freeze, otherwise NO-GO and LAN plus SQLite stands. Rollback everywhere: restore the `~/scene-backend` backup, restart (kill port 8000, re-export the key in the server window, `python3 server.py`), re-run the previous step's test.

RULE THROUGHOUT: wire one thing, test it, then wire the next; never wire everything untested at once. Any failed test stops that step and the next step does not start. The running backend is a separate copy from the repo clone, so restaging from the repo is deliberate, never automatic.

## What still needs human hands

- Nayan: re-verify the autodetect plug point against the current repo backend, apply the patch to the running backend copy, restart, retest (chunk test, Ask, follow-ups, lens).
- Isabella: confirm the Managed Agents SDK shape against the official guide, then integrate per the checklist, then retest.
- Glasses plus band pairing at the venue, per the runbook order.
- Cloud SQL console work by 6:30 PM, or LAN plus SQLite stands.
- Claude audit review of Srijan's backend changes before any repo-backend restage or restart from the repo.

## Deliberately NOT wired

- Srijan's backend changes (actions, followthrough, routes, dashboard.html): pending Claude audit review. No restage, no restart from the repo on their strength.
- Cloud SQL: not provisioned, pending Nayan's console work.
- The autodetect module and Managed Agents prototype themselves: patches and guides only. Nothing in this swarm edits the running backend, Isabella's code, the contract, the bridge, or the repo.
