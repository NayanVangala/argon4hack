# Scene master wire-up order: one thing, test it, then the next

**THE RULE, NON-NEGOTIABLE: wire one thing, test it, then wire the next. Never wire everything untested at once.** If a step's test fails, stop, roll back that step only, and re-prove the previous green state before touching anything else.

**TWO MORE RULES, SAME WEIGHT:**
- The running backend on Nayan's Mac (`~/scene-backend`) is a **separate copy from the repo clone**. Restaging from the repo is a deliberate step, never automatic.
- **The demo backend must not be restarted from the repo until Srijan's backend changes are reviewed** (separate Claude audit). No exception during the demo window.

**State this runbook assumes (2:30 PM PDT, Oct 25):** backend running on the Mac, live Argon Ask proven, Isabella's phone connected via LAN and Ask working. Backend LAN last known `http://10.1.63.33:8000`; re-verify every time with `ipconfig getifaddr en0` on the Mac, because DHCP can move it. Phone and Mac stay on the same venue Wi-Fi; a phone on cellular cannot reach the LAN address. Demo phone is Isabella's. Deadlines: Cloud SQL go/no-go **6:30 PM**, feature freeze **7:30 PM**, submission **10:00 PM**. No keys in any file, doc, or screenshot. This runbook makes no live Argon call itself; the tests below reuse the already-proven Ask path.

**Before ANY step that edits the running backend: back it up.** Copy `~/scene-backend` to a dated backup folder on the Mac first. Every rollback below is "restore that backup, restart, re-run the previous step's test." Never delete `scene.db` to fix a count problem; that wipes live scenes and resets to the seed.

Sources: `~/workspace/scene-wiring/SCENE-WIRING-RUNBOOK.md` (Parts 1-4, Part 6), `~/workspace/scene-fix-swarm/SUMMARY.md`, `autodetect/INTEGRATION.md`, `managed-agents/INTEGRATION.md`, `glasses-runsheet.md`. No new endpoints, routes, or bridge steps are invented here.

---

## Step 1. Confirm the working demo baseline (phone + backend + Ask green)

**Do, in order:**
1. Mac, second Terminal window: `curl -s http://localhost:8000/api/v1/status`. Note `scene_count` and `spend_usd` as the baseline. (Fresh seed was 8 scenes / $1.84; the live server has already run past that, so judge by deltas from today's baseline, not by 1.84.)
2. Phone (Isabella's): Session tab, DEVELOPER section, "Use mock data" OFF, base URL bare `http://<current-Mac-LAN-IP>:8000` (no `/api/v1`, no `localhost`), token empty unless auth is on, tap Reload.
3. Phone Ask tab, in order: `What did Maya promise me?` then `What did Maya say about the weather?` (no word "promise" in the second query).
4. Lens on the demo phone: open the lens page with `?api=http://<current-Mac-LAN-IP>:8000` appended (bare URL, scheme included, no trailing slash, no `/api/v1` in the value). Open the Day screen.

**Test (all must pass):** Status curl answers with `recording: false` and a scene count matching the phone. Phone DEVELOPER shows `CONNECTED · N SCENES`, no red error, and the scene list is NOT the 8 canned mock scenes (mock tell: spend row `$--`; real mode shows a dollar amount). Promise Ask returns `Maya promised to send the Q3 numbers by Friday.` with the verbatim 09:15 quote receipt; no-record Ask returns exactly `I don't have a record of that.` with empty receipts and sources; server log shows no `no GEMINI_API_KEY` fallback line on either Ask (that line means mock, not live Argon). Lens Day screen loads all four areas (spend, people, facts, pending follow-ups) with no `CACHED` or `OFFLINE` label.
**Rubric:** protects live demo 50% (everything else builds on this green state; a broken baseline makes every later test meaningless). Moves nothing by itself.
**Rollback:** nothing to roll back; this step changes nothing. If it fails, fix it from the wiring runbook branches (mock left on, double `/api/v1`, LAN unreachable, 401, cellular) and do NOT proceed to Step 2.

## Step 2. Autodetect integration + restart + retest

**What it is (and is not):** the standalone stdlib-only module in `~/workspace/scene-fix-swarm/autodetect/` (`detect()` classifies a chunk after transcription as conversation / monologue / ambient / silent; conversation and monologue route to analyze, ambient and silent route to `mark_and_skip`, a minimal scene with no Argon call). It never starts capture, does no diarization, never guesses a speaker. It is NOT yet in the running backend.

**Do, in order:**
1. Back up `~/scene-backend` first (see header).
2. Integrator only, in the Mac running copy (never by restaging from the repo): re-verify the plug point against the running copy's `ingest.py`, because the repo backend has since moved (Srijan changes). The guide's plug point is `IngestPipeline._run_once`, after transcribe + timestamp backfill, before `analyzer.analyze`. Confirm that shape still holds in the running copy before editing; if it does not, stop and escalate, do not guess.
3. Add the guarded import (missing module degrades to analyze-everything, never a crashed chunk) and the `_run_once` branch per `autodetect/INTEGRATION.md`, plus the minimal-scene builder (same scene shape, real transcript kept, `verified: False`, detection fields on minimal scenes only, `_critique` still runs).
4. Reconcile spend in `process_chunk`: a `mark_and_skip` chunk books `add_spend(0.00)`, not the flat $0.07 full-chunk figure (the $0.019 figure is the estimated Argon-call portion saved; do not book it as negative spend).
5. Restart the server from `~/scene-backend` only: kill port 8000, re-export the key in the same Terminal window, `python3 server.py`, re-check status from a second window.

**Test (all must pass):** Step 1 baseline re-run green (phone + Ask + lens). Then one chunk of each label: conversation and monologue produce full scenes with Argon drafts; ambient and silent produce minimal scenes with all seven `detection_*` fields, chunk status `indexed`, and $0.00 booked, with no gap in the phone timeline order. Failure paths: detector import removed means analyze-everything; detector raising means that chunk analyzes, never fails silently; empty transcript analyzes, never skips. Never drop a chunk silently; when in doubt, analyze.
**Rubric:** live demo 50% (cheaper, gap-free timeline; skipped silence saves ~$0.019 Argon per chunk) and originality 15% (post-transcription auto-detection is a real pipeline behavior, not a dashboard). Small, but it must not break the 50% to earn the 15%.
**Rollback:** restore the pre-Step-2 backup of `~/scene-backend`, restart (kill 8000, re-export key in the server window, `python3 server.py`), re-run the Step 1 test. If Step 1 goes green again, autodetect stays out and the demo proceeds without it.

## Step 3. Managed Agents integration (Isabella) + retest

**What it is (and is not):** the standalone prototype in `~/workspace/scene-fix-swarm/managed-agents/` (Follow-Through wrapper: find-promises, verify-quotes with code, draft, never sends without a tap). Isabella owns this integration and the approval screens. The Managed Agents SDK call shape is **UNVERIFIED** (secondary write-ups only); the prototype's launcher refuses to run until Isabella confirms it against the official guide. Nothing here edits her code, the server, the contract, or the phone app by itself.

**Do, in order:**
1. Isabella runs the prototype untouched: `python3 managed_followthrough.py --self-test` then `--dry-run` (zero network, zero token, zero sends).
2. Point it at the real server, read + generate only: `GET /facts`, `POST /followups/generate`, `GET /followups?run_id=`. The client has no approve/dismiss/send methods, so it cannot approve or send by accident.
3. Copy `MANAGED_AGENT_PROMPT` verbatim into the Managed Agents run input (get_facts first, code verification normalized difflib >= 0.80 + timestamp overlap, unverified means `needs_review` with empty draft, never pending, nothing sends).
4. Confirm the SDK seam against the official Antigravity agent guide BEFORE any live agent run. Until then, the honest framing is "Managed Agents prompt + sandbox verifier design, running locally as a prototype; live SDK launch pending official-shape confirmation." Do not demo the seam as a live run before then.
5. Wire the approval screens to poll `GET /followups?run_id=<id>` with no status filter for the agent view, and `?status=pending` for the user approval queue (unverified items never appear for approval). Do not change the approval gate, the needs_review routing, the draft shape, the verification rule, or the fail-closed auth rule.

**Test (all must pass):** dry-run shows 2 pending / 1 needs_review, `sent: []`, all local-vs-stored verdicts agreeing. Live: stored results match the phone app's list for the same `run_id` field-for-field. Approve gate, human tap only: approve a pending item returns `200 {status: approved}`; attempting to approve a needs_review item returns `400 not_approvable` and its state does not change (re-poll: still `needs_review`, empty draft); a made-up id returns `404`. Zero unverified items in the pending queue, zero non-empty drafts on unverified items. Then re-run Step 1 (phone + Ask + lens green).
**Rubric:** the **$5,000 Best Use of Managed Agents prize lane** (this is the lane's evidence: agent run, sandbox code verdicts with ratios, the approval tap, the 400 gate, the "nothing sends without a tap" close) plus live demo 50% (the follow-through beat is the demo's closing beat) and problem 25% (verified follow-through is the usefulness story).
**Rollback:** disconnect the prototype; the server's canned-plus-verified generation and the phone's existing approve/dismiss screens are the fallback and already produce the right stored states. Re-run the Step 1 test plus the approve-gate test (200 / 400 / 404). If those pass, the demo proceeds with the server path and the prototype shown honestly as a prototype, not a live run.

## Step 4. Glasses + band live + retest

**Do, in order (condensed from `glasses-runsheet.md`; do not reorder):**
1. Preconditions: demo phone decided (Isabella's), phone + Mac on the same venue Wi-Fi, phone auto-lock off, band charger packed. Glasses pair to the demo phone, never to the Mac.
2. Meta AI Developer Mode ritual on the demo phone: 7 taps on the Developer Mode entry, toggle OFF then back ON, confirm it stays ON (force-quit Meta AI and retry if the toggle never appears; stop and escalate if it will not stay ON).
3. Glasses WITHOUT the band first: band powered OFF or out of range when registering or updating registration. If registration fails with the band connected, disconnect it, force-quit Meta AI, redo with glasses only.
4. Force-quit Meta AI completely BEFORE opening SceneBridge (Meta AI and the bridge fight over the same Bluetooth channel).
5. Bridge order: launch SceneBridge, "Register glasses" until registered, grant camera permission ("Request" then "Check" until granted; if denied, grant in phone Settings, then "Check"), wait for glasses in the list, tap the entry, "Start stream" (createSession, session start, up to 10s for started state, addCamera, stream start).
6. Frame proof, the only proof that counts: the Live preview must fill with a live camera image. State saying "streaming" with preview still "No frame yet" after 10s is NOT streaming; do not start recording.
7. Only after the stream runs: "Start session" (backend session), then "Record" for 30s chunking. One continuous session; do not stop/start between chunks. Teardown gap: count to 3 after "Stop stream" before "Start stream" again; at most 3 stream-start attempts, then work the stuck-broadcast ladder (Meta AI Stop/End, hold capture 8-10s, case closed 30-60s, force-quit + Bluetooth toggle, forget + re-register as last resort only).
8. Band ONLY after glasses work: check LED (green solid >80% good, orange solid 20-80% usable, blinking orange <20% charge first, do not demo on it), power on, connect, test EACH gesture once against the lens (pinch to pin, swipe timeline, middle tap back, gesture kill switch). Firmware 129 warning: a band Back tap can END a session despite consumeBack, so never make Back the only navigation path; every beat Back can reach must also be reachable another way.

**Test (all must pass):** bridge shows registered + camera granted + glasses in list; "Start stream" flips to "Stop stream" AND the preview shows a live moving image; backend session started, Record on, 30s windows rolling in one continuous stream/session; a new scene created while the lens is open appears at the top of the lens timeline within seconds; band gestures (if used) each confirmed against the lens, plus a non-Back path for every beat. Then re-run Step 1 (phone + Ask green) to prove the glasses track did not disturb the phone path.
**Rubric:** live demo 50% (this is the single biggest lever: glasses live is what the demo leads with; without it the demo is phone + seeded data) and problem 25% (hands-free capture is the concrete use case). **30-minute rule: if glasses fight for more than 30 minutes, STOP the glasses track** and fall back to seeded + chunk-upload testing for the demo. Do not burn the demo slot on a pairing fight, and do not discover the zero-frames issue on stage.
**Rollback:** stop the stream cleanly, end the session, glasses idle, Meta AI force-quit. The demo falls back to the Step 1 state (phone + backend + Ask + lens, seeded + chunk-upload proven). No backend change is involved, so no backend rollback is needed; if a phone setting changed, redo the Step 1 phone taps from scratch on the demo phone.

## Step 5. Dashboard decision (audit FIRST; no blind restage)

**Do, in order:**
1. Wait for the separate Claude audit of Srijan's backend changes on main (`src/backend/app` actions.py, followthrough.py, routes.py, plus dashboard.html). Do not start this step before the audit lands.
2. Read the audit's verdict on dashboard.html separately from its verdict on the backend files. Dashboard and backend are different decisions.
3. Decide: (a) If the audit clears dashboard.html AND it can be shown without touching the running backend, test it standalone as backup only; (b) if the audit flags anything in the backend files, or the dashboard requires the repo backend, leave the running backend untouched and the dashboard out. The dashboard is backup only, never the demo lead (hackathon avoid list: a dashboard as the main feature), and no repo-backend restage happens on the strength of a dashboard decision.
4. If (a): show it only after the glasses + phone demo beats are proven, and re-run Step 1 after any dashboard change.

**Test:** Step 1 baseline green after the decision, whatever it is. If dashboard is shown: it loads against the running backend's data (or its stated source) without changing phone, lens, Ask, or follow-up behavior; no new error appears in the server log; the demo script still leads with glasses, not the dashboard.
**Rubric:** pitch 10% at most (a backup screen for judges, not a demo beat) and, if misused as the lead, it actively hurts live demo 50% and problem 25% by displacing the glasses story. A "no" here costs nothing; a careless "yes" can cost the demo.
**Rollback:** remove the dashboard from the demo path (close it, stop serving it if it was served for testing). Do NOT touch the running backend to roll back a dashboard decision. Re-run Step 1 to confirm green.

## Step 6. Cloud SQL go / no-go by 6:30 PM (Nayan's console work; else LAN + SQLite stands)

**Do, in order:**
1. Nayan works his own GCP console on his own billing account (planned shape from the deploy notes: Cloud SQL Postgres 16, us-west2, db-f1-micro, 10GB SSD, Cloud Run host with app-level Bearer auth, DATABASE_URL via Secret Manager). No other agent provisions it, and no credential goes in any doc.
2. The go criterion is end-to-end proof, not "provisioned": the running demo path (phone + Ask + lens, Step 1 test) works against the cloud backend with the same pass criteria, on the venue Wi-Fi, with spend and scene state consistent.
3. **At 6:30 PM, decide and stop deciding.** If end-to-end proof is not in hand by 6:30 PM, the decision is NO-GO, full stop. LAN + SQLite stands for the demo. Do not let a half-migrated database into the demo window.
4. If GO: cut over only with a fresh Step 1 test against the cloud backend, a known-good LAN + SQLite fallback still runnable, and time left before the 7:30 PM freeze to re-prove Steps 2-4 against the new backend. If any of those is missing, it is NO-GO.

**Test (GO requires all):** Step 1 test green against the cloud backend (status, phone CONNECTED, promise + no-record Ask with receipts, lens Day with no CACHED/OFFLINE labels); a real chunk ingests and appears; follow-up generate + approve gate (200 / 400 / 404) still hold. NO-GO requires only: Step 1 test green against LAN + SQLite, which is already proven.
**Rubric:** live demo 50% (risk, not gain: a working cloud backend adds robustness off-venue, but a failed cutover kills the 50% outright). Problem, originality, and pitch move only if the demo itself stays green; there is no rubric credit for the database choice alone.
**Rollback:** stay on / revert to LAN + SQLite: point the phone base URL and lens `?api=` back at the Mac LAN address, restart the Mac backend from `~/scene-backend` if it was stopped (kill 8000, re-export key in the server window, `python3 server.py`), re-run Step 1. The LAN + SQLite state is the permanent fallback; it is not a degraded demo, it is the proven demo.

---

## End state checklist (after Step 6, before the 7:30 PM freeze)

- [ ] Step 1 green: phone + backend + Ask + lens, with today's baseline numbers noted (deltas, not absolutes).
- [ ] Each wired item (autodetect, Managed Agents, glasses + band) either green with its test passed, or explicitly rolled back with Step 1 re-proven.
- [ ] Dashboard: in as backup only, or out, per the audit. Repo backend: NOT restaged onto the running backend unless the audit cleared it AND a deliberate restage + full Step 1 re-test followed.
- [ ] Cloud SQL: GO with end-to-end proof, or NO-GO with LAN + SQLite confirmed. Decision made by 6:30 PM, not revisited after.
- [ ] Pitch and submission work proceeds from this frozen demo state; nothing new is wired after 7:30 PM.
