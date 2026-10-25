# Scene fix swarm: convergence summary

4 workers, all complete, all verified on disk. No device calls, no git, no keys, no live Argon calls. Nothing staged to Nayan Mac.

## 1. Chunk test kit — `chunk-kit/`

Ready-to-run kit for the missing chunk test (real video+audio upload proving dense frames + transcription + analysis end to end).

- `chunk-kit/README.md` (384 lines): exact run order, verification steps, one failure branch per step.
- `chunk-kit/make-chunk.sh`: 30s testsrc2 mp4 + 30s 440 Hz tone wav (16 kHz mono), ffprobe check 29.5-30.5s, install instructions and exit 1 if ffmpeg missing.
- `chunk-kit/upload-chunk.sh`: POSTs to `/api/v1/chunks` with `video` + `audio` fields, BASE_URL defaults to localhost:8000, overridable for LAN, token only via env when AUTH_ENABLED=1.
- Verified from routes.py + ingest.py: route, field names, missing-part 400 (`Missing video or audio part.`), success 202, pipeline order, 401 shape.
- Key corrections the kit documents: no per-step success log lines exist (healthy run logs only `POST /api/v1/chunks` then silence); dense vs 6-frame cannot be distinguished via API or logs; no duration validation (over/under 30s still 202s); scene detail has no `quote` field (check summary list + transcript instead); spend +0.07 proves storage, not live Argon (mock still adds it); live-vs-mock discriminator is content (mock summary is exactly `Live chunk indexed (mock scene)`).

## 2. Glasses + band run sheet — `glasses-runsheet.md`

One page, 78 lines, condensed from wiring runbook Part 6, tailored to current state (backend up, demo phone is Isabella phone, LAN 10.1.63.33).

- Covers in order: Isabella phone decision + same-Wi-Fi rule, Dev Mode ritual, glasses-without-band-first, force-quit Meta AI, exact bridge order, frame-callback proof, backend session + Record gated on stream, 2s teardown gap + retry cap 3, band after glasses work (charger, LED codes, gestures), firmware 129 warnings (Back tap ends session despite consumeBack, zero-frames open issue), stuck-broadcast ladder, success criteria, 30-minute fallback to seeded + chunk testing.
- Caveats: bridge steps taken on the runbook's word (not independently re-verified against bridge code); LAN shown as last-known with a re-verify instruction; firmware/LED/gesture items are field experience, not code.

## 3. Managed Agents prototype — `managed-agents/`

Standalone Follow-Through wrapper for Isabella to integrate. NOT an edit to her code.

- `managed-agents/DESIGN.md`: agent antigravity-preview-09-2026, remote sandbox, find-promises → verify-quotes → draft loop, never-sends-without-a-tap guarantee, failure routing, Bearer fail-closed auth.
- `managed-agents/managed_followthrough.py` (714 lines, stdlib only, self-test + dry-run pass): runs the loop, verifies quotes with a code checker, triggers generate, polls approval state. Has no approve/dismiss/send methods, so it cannot approve by accident.
- `managed-agents/INTEGRATION.md`: 6 wiring steps for Isabella, must-not-change list, 4 no-send tests, prize-lane evidence sequence.
- Verified against contract + followthrough.py + routes.py: generate 202 shape (server runs synchronously but still returns `running`, so poll the list), followups list shape, approve/dismiss 200s, needs_review 400, 404, facts + scene transcript endpoints, auth rules.
- Caveats: Managed Agents SDK call shape is UNVERIFIED (secondary write-ups only, guarded seam refuses to run until Isabella confirms against the official guide); no draft-create, draft-edit, run-status, or send endpoint exists (prototype works around all four); server verification is fuzzy (difflib ratio >= 0.80 + timestamp overlap), not exact match, and the prototype ports that rule verbatim; contract omits needs_review but the server really stores it.

## 4. Pitch package — `pitch/`

- `pitch/PITCH-SCRIPT.md`: 3-minute script, no slides, time marks 0:00-3:00 with rubric weight per beat. Promises problem, spine, no-retrieval line said out loud (whole session in one 1M-token context, NO retrieval step), verification loop (Critic + code verification + needs_review + nothing sends without a tap), demo beats in order (glasses, scenes, Ask with receipts, follow-up approve), one-line glasses-failure fallback.
- `pitch/VIDEO-SHOT-LIST.md`: 60s uncut lens video, second by second (pin, scroll, back, live scene), restart-the-take rules, no editing around failures.
- `pitch/SUBMISSION-CHECKLIST.md`: fields with honest ready / in-progress / to-confirm status, repo https://github.com/NayanVangala/argon4hack, rule reminders (public repo, hackathon-built features only, dashboard never the lead).
- Flagged to-confirm, not decided: Srijan member vs contributor; Managed Agents wrapper in-progress, not done; Cloud SQL not provisioned (LAN + SQLite fallback per 6:30 PM cutoff); live analyzer over real frames + live transcription still open; final description copy; roster fits max-4; repo HEAD at submission; video take recorded; pitch rehearsed to 3:00 or under; exact form fields/limits.

## What still needs humans

- Isabella rebuild: phone app from latest main (her 767f5c1 receipts push included) + integrate the Managed Agents prototype + confirm the SDK shape.
- Chunk test run: human runs the kit from the Mac (generate, upload, verify).
- Glasses pairing: human runs the run sheet at the venue (Dev Mode ritual, bridge order, band after glasses).
- Pitch rehearsal: human rehearses to 3:00 or under.
- Video recording: human records the 60s uncut lens take.
- Submission tap: human files the form (Srijan status decision + final copy + repo HEAD at that moment).
- Cloud SQL go/no-go by 6:30 PM, else LAN + SQLite stands.

## 5. Auto conversation detection — `autodetect/` (follow-up swarm, 2 workers)

Standalone module, NOT merged into the running backend. Speech-presence plus dialogue-pattern detection, stdlib only, no diarization, never guesses speakers. Demo stays stable until Nayan chooses to integrate.

- `autodetect/autodetect.py` (stdlib only, `math` + `re`): `detect(transcript, words, chunk_duration_s)` returns label, confidence, reasons, route, speech_seconds, word_count, turn_count. Accepts the real faster-whisper shape (`start_ts`/`end_ts`, `word_timestamps`) plus `start`/`end` spellings; `words_from_segments()` flattens segment dicts.
- `autodetect/test_autodetect.py`: 24/24 unit tests pass; `python3 autodetect.py` self-test 9/9 pass (verified by coordinator run).
- `autodetect/INTEGRATION.md`: plug point verified in workspace ingest.py (`IngestPipeline._run_once`, after transcribe + timestamp backfill, before `analyzer.analyze`); guide only, no backend edit.
- `autodetect/README.md`: one-page overview, labels, routing, self-test commands.

Routing table (fixed): conversation -> analyze; monologue -> analyze (a solo speaker can state a promise); ambient -> mark_and_skip; silent -> mark_and_skip (minimal scene kept so the timeline stays complete, Argon call skipped, about $0.019 saved per skipped chunk).

Thresholds (tuned for 30s chunks, documented in module): MIN_WORDS_FOR_SPEECH = 10; MIN_SPEECH_SECONDS = 3.0; skip requires BOTH legs when duration is known; TURN_GAP_SECONDS = 2.0; SHORT_UTTERANCE_MAX_WORDS = 12; MIN_TURNS_FOR_CONVERSATION = 3 with MIN_SHORT_TURNS = 2; MAX_WORD_DURATION_S = 30.0 clamp. Dialogue signals: question-answer pair and/or 3+ gap/punctuation turns with 2+ short ones, no speaker identity. Failure defaults to analyze, never drops a chunk silently.

Caveats: workspace ingest.py books a flat $0.07 per chunk while $0.019 is the estimated Argon-call portion, so the integrator must reconcile what a skipped chunk books (guide says $0.00); integration docs were written to the shared contract before the module landed and the landed module matches it (signature + return keys verified); mock transcript (4 words, no timestamps) classifies as ambient, which only matters if detection ever runs against mock output; repo backend has since moved (Srijan changes), so re-verify the plug point against the current repo backend before merging.

Still needs a human: integrate into ingest per the guide, or leave standalone. Do not restart the running backend from the repo without reviewing Srijan's backend changes.
