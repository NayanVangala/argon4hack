# Autodetect integration patch: wire `autodetect.py` into backend ingest

## ⚠️ STOP: RE-VERIFY BEFORE APPLYING — DO NOT APPLY BLINDLY

**This patch is based on the workspace backend copy at
`~/workspace/scene-backend/app/ingest.py`. It is NOT verified against the
current repo backend.**

Srijan pushed changes to `src/backend/app/` on main (`actions.py`,
`followthrough.py`, `routes.py`, `dashboard.html`) that are pending review
via a separate Claude audit. Those files are not `ingest.py`, but
`routes.py` feeds `process_chunk` (it supplies `start_ts` / `end_ts`), and
the repo backend may have drifted from the workspace copy in other ways.

**Before applying, the integrator MUST:**

1. Diff the plug point below — `IngestPipeline._run_once`, after
   `transcribe` + timestamp backfill, before `analyzer.analyze` — against
   the CURRENT repo backend (`src/backend/app/ingest.py`).
2. Confirm the anchor lines in §2 still exist verbatim (or adapt the
   patch to the repo's actual anchors and note the adaptation).
3. Confirm the running backend on Nayan's Mac is the copy being patched.
   The running backend is a separate copy from the repo clone; patching
   the repo alone does not change the running demo, and patching the
   running copy without the repo diff leaves the two diverged.
4. Do NOT restart the running backend on this patch alone. Apply, run
   the retest checklist in §7, and keep the pre-patch copy as fallback
   until the checklist passes.

This patch edits nothing itself. It is a guide + diff for the integrator
to apply by hand. No step in this document touches the running demo.

---

## 0. What this is, honestly

This wires a **post-transcription classifier** into ingest. It runs AFTER
a chunk has already been recorded and transcribed, and BEFORE the Argon
analysis call, and answers one question: is this chunk worth an Argon call?

**Explicitly NOT what this is (do not claim otherwise in the demo or pitch):**

- NOT noise-robust VAD. There are no energy thresholds, no frequency
  filtering, no voice-activity detector of any kind.
- NOT always-on listening. It never starts capture. The user still
  presses Record; detection runs only on chunks the user already recorded.
- NOT a recording trigger, wake word, or background capture path.
- NOT diarization. No speaker identity anywhere. Every speaker stays
  `"Unknown"`, `turn_count` is a dialogue-pattern heuristic, never a
  speaker count.
- NOT a new model or dependency. `autodetect.py` is stdlib only.

If a chunk is skipped, it is skipped on transcript evidence only
(word count + word-timing + dialogue pattern), after transcription
already ran.

## 1. Verified shapes (read from the workspace backend copy, not invented)

### 1.1 Backend: `~/workspace/scene-backend/app/ingest.py`

- Class: `IngestPipeline.__init__(self, store, broadcaster, transcriber,
  analyzer, attributor, embedder)`.
- `_run_once(self, session_id, start_ts, end_ts, video_path, audio_path)`
  runs, in order:
  1. `keyframes = self._extract_frames(video_path)` (dense 1fps, 6-frame
     fallback, mock placeholder; never raises).
  2. `segments = self.transcriber.transcribe(audio_path)` then
     `segments = self._backfill_timestamps(segments, start_ts, end_ts)`.
     **This is the plug point: immediately after step 2, before step 3.**
  3. `draft = self.analyzer.analyze(keyframes)` (one Argon call per chunk).
  4. `attributed = self.attributor.attribute(segments, keyframes,
     draft.get("people") or [])`.
  5. Transcript built from `attributed`; embeddings computed (not
     persisted); scene dict built; `scene["critique"] =
     _critique(scene)`; `stored = self.store.add_scene(scene)` (store
     assigns the id); then `self.store.update_scene(scene_id,
     thumb_url=..., keyframes=...)` with CDN URLs
     `https://cdn.helloscene.xyz/t/%s.jpg` and
     `https://cdn.helloscene.xyz/k/%s/0.jpg`.
  6. `return stored` sits inside a `try`, with a `finally` that deletes
     frame temp files via `self._delete_keyframes(keyframes)`. A return
     from inside the `try` still runs that `finally`: the skip branch
     in §3 is safe on cleanup for exactly this reason. Do NOT branch
     around `_run_once` from `process_chunk`.
- `process_chunk(...)`: `store.create_chunk(...)`, chunk status
  `"processing"`, retry loop over `_run_once` up to `_MAX_RETRIES = 3`
  (4 attempts total), then on success: spend (see §5), chunk status
  `"indexed"`, `broadcaster.broadcast_scene(_scene_summary(stored_scene))`
  + `broadcaster.broadcast_status()`, return `status: "received"`.
  On failure: chunk `"failed"` + WS error via `_broadcast_error`.
- Spend constant, top of `ingest.py`: `_SPEND_PER_CHUNK_USD = 0.07`.
- Transcriber output shape (verified in `ingest.py` backfill +
  `app/services.py`): a list of segment dicts
  `{speaker_label: "Unknown", text, start_ts, end_ts,
  word_timestamps: [{word, start_ts, end_ts}]}`. Real faster-whisper
  timestamps are floats in seconds; the mock returns `None` for every
  timestamp (see §4 for what backfill then does).
- `start_ts` / `end_ts` arriving at `process_chunk` are ISO strings
  (`app/routes.py`: `fields.get("start_ts") or now_iso()`, where
  `now_iso()` is UTC ISO with seconds precision; `end_ts` defaults to
  `start_ts` when missing). They are NOT floats. The patch must parse
  them to compute `chunk_duration_s` (§3, helper).

### 1.2 Module: `~/workspace/scene-fix-swarm/autodetect/autodetect.py`

Verified by reading the landed module (self-test: 9/9 passed,
`python3 -B autodetect.py`, run read-only, no files written):

```python
detect(transcript: str, words: list, chunk_duration_s: float) -> dict
words_from_segments(segments) -> list
```

`detect()` returns exactly these keys: `label`, `confidence`, `reasons`,
`route`, `speech_seconds`, `word_count`, `turn_count`.
`detect()` never raises: it wraps its inner logic in try/except and
falls back to `monologue` / `analyze` on unexpected input.
Key thresholds (single source of truth: the module constants, do not
re-tune here): `MIN_WORDS_FOR_SPEECH = 10`,
`MIN_SPEECH_SECONDS = 3.0`, `TURN_GAP_SECONDS = 2.0`.

### 1.3 CORRECTION to the module's own INTEGRATION.md sketch (read this)

The sketch in `~/workspace/scene-fix-swarm/autodetect/INTEGRATION.md` §1
passes words as a list of **strings**:

```python
[w.get("word", "") for seg in segments
 for w in (seg.get("word_timestamps") or [])]   # WRONG against the landed module
```

The landed module's `_clean_word()` returns `("", None, None)` for any
non-dict entry and marks the input malformed, which forces the safe
default `monologue` / `analyze`. Following the sketch literally would
not crash and would not drop anything, but it would silently disable
skipping entirely (every chunk would analyze).

**The patch below uses `words_from_segments(segments)`, which returns
dicts with `word` / `start` / `end` keys (and accepts the real
`start_ts` / `end_ts` spelling).** That is the only correct `words`
input. If the integrator sees the INTEGRATION.md sketch, follow this
patch, not the sketch, on this one point.

## 2. Import point (Hunk 1)

Copy `autodetect.py` into the backend package first, next to
`ingest.py` (e.g. `app/autodetect.py`), so the import does not depend
on the `scene-fix-swarm` path, which will not exist on the Mac in the
same form. Do NOT add `sys.path` hacks pointing at the swarm folder.

Mirror the guarded-import pattern already at the top of `ingest.py`
for `critic.py` (`try: from .critic import ... except ImportError:
try: from critic import ...`), so a missing module degrades to
analyze-everything instead of crashing chunks:

```diff
--- a/app/ingest.py
+++ b/app/ingest.py
@@ top of file, next to the critic import
 try:
     from .critic import critique_scene as _critic_scene
 except ImportError:  # not a package import, or critic.py not built yet
     try:
         from critic import critique_scene as _critic_scene
     except ImportError:
         _critic_scene = None
+
+# Autodetect: stdlib-only post-transcription classifier. Missing module
+# must degrade to analyze-everything, never to a crashed chunk.
+try:
+    from .autodetect import detect as _detect
+    from .autodetect import words_from_segments as _words_from_segments
+except ImportError:
+    try:
+        from autodetect import detect as _detect
+        from autodetect import words_from_segments as _words_from_segments
+    except ImportError:
+        _detect = None
+        _words_from_segments = None
+        logger.warning(
+            "[ingest] autodetect module not found; "
+            "running analyze-everything (no chunk skipping)")
```

## 3. Exact call site (Hunk 2) + minimal-scene helper (Hunk 3)

### Call site: in `_run_once`, after transcribe + backfill, before analyze

Before (verbatim anchors from the workspace copy):

```python
            # Transcribe first, so a quote exists even if analysis degrades.
            segments = self.transcriber.transcribe(audio_path)
            segments = self._backfill_timestamps(segments, start_ts, end_ts)

            # Analyze, then attribute.
            draft = self.analyzer.analyze(keyframes)
```

After:

```python
            # Transcribe first, so a quote exists even if analysis degrades.
            segments = self.transcriber.transcribe(audio_path)
            segments = self._backfill_timestamps(segments, start_ts, end_ts)

            # Autodetect gate: post-transcription classification only.
            # conversation/monologue -> analyze (unchanged path below).
            # ambient/silent -> minimal scene, Argon call skipped.
            # Any detector failure -> analyze. Never drop a chunk.
            detection = self._detect_chunk(segments, start_ts, end_ts)
            if detection is not None and detection.get("route") == "mark_and_skip":
                return self._store_minimal_scene(
                    session_id, start_ts, end_ts, segments, detection)

            # Analyze, then attribute.
            draft = self.analyzer.analyze(keyframes)
```

Notes on placement, all load-bearing:

- The branch is inside `_run_once`'s `try`, so the `finally` still
  deletes this attempt's frame temps. Frame extraction already ran
  (step 1), so skipping saves the Argon call only, not local ffmpeg
  work. That is expected: ffmpeg is local and cheap, Argon is the cost.
- The branch does NOT call `attributor.attribute`, `embedder.embed`,
  or `analyzer.analyze`. The minimal scene's transcript is built
  directly from `segments` (see helper).
- The branch returns the stored minimal scene exactly like a full
  scene, so `process_chunk` then marks the chunk `"indexed"` and
  broadcasts scene + status with no changes (except the spend branch
  in §5). A skipped chunk is a visible timeline entry, not a hole.
- If `_store_minimal_scene` itself raises (e.g. `add_scene` fails),
  let it propagate: the `_run_once` retry loop and then the `"failed"`
  status apply, exactly like a full-path failure. Never swallow it
  into a fake success and never return `None` as the scene.

### Helpers to add to `IngestPipeline` (new methods, same file)

```python
    @staticmethod
    def _chunk_duration_s(start_ts, end_ts):
        """Chunk window in seconds from the ISO strings routes.py passes.

        Returns 30.0 on any parse failure or non-positive result (the
        standard chunk length; detect() itself also falls back to 30.0
        for unusable durations, so this is belt-and-braces).
        """
        from datetime import datetime

        def _parse(value):
            if isinstance(value, (int, float)):
                return float(value)
            if isinstance(value, str):
                try:
                    return datetime.fromisoformat(value).timestamp()
                except ValueError:
                    return None
            return None

        start = _parse(start_ts)
        end = _parse(end_ts)
        if start is None or end is None:
            return 30.0
        duration = end - start
        return duration if duration > 0 else 30.0

    def _detect_chunk(self, segments, start_ts, end_ts):
        """Run autodetect, or return None (= analyze) on any failure.

        None means: module missing, or detect() raised (it promises
        never to raise, but the wrapper stays anyway so a future
        module change can never turn a chunk failure into a skip).
        A returned dict with route "analyze" also means analyze.
        Only a dict with route "mark_and_skip" skips.
        """
        if _detect is None or _words_from_segments is None:
            return None
        try:
            transcript = "\n".join(seg.get("text", "") for seg in segments)
            words = _words_from_segments(segments)
            duration = self._chunk_duration_s(start_ts, end_ts)
            return _detect(transcript, words, duration)
        except Exception as exc:  # noqa: BLE001 - default is analyze
            logger.warning("[ingest] autodetect failed (%s); "
                           "defaulting to analyze", exc)
            return None

    def _store_minimal_scene(self, session_id, start_ts, end_ts,
                             segments, detection):
        """Store the minimal scene for a skipped chunk; return it stored.

        Same field shape as a full scene, same _critique call, same
        add_scene + update_scene thumb/keyframe patch as the full path.
        The only additions are the seven detection_* fields, on
        minimal scenes only. Full scenes keep their fields exactly.
        """
        transcript = [{
            "speaker": seg.get("speaker_label", "Unknown") or "Unknown",
            "text": seg.get("text", ""),
            "start_ts": seg.get("start_ts") or start_ts,
            "end_ts": seg.get("end_ts") or end_ts,
        } for seg in segments]
        quote = transcript[0]["text"] if transcript else ""
        label = detection.get("label", "")
        scene = {
            "session_id": session_id,
            "start_ts": start_ts,
            "end_ts": end_ts,
            # Placeholder, never a fabricated Argon-style summary.
            "summary": "No conversation detected",
            "quote": quote,
            "thumb_url": "",
            # Valid existing value; the truth lives in detection_* below,
            # not in type, so phone/lens readers see no new enum value.
            "type": "conversation",
            "verified": False,
            # "silence" is an allowed confidence value (services.py
            # ArgonSceneAnalyzer._sanitize_confidence); everything else
            # skipped uses "review", as the full path's default.
            "confidence": "silence" if label == "silent" else "review",
            "objects": [],
            "people": [],
            "actions": [],
            "visible_text": [],
            "critique": [],
            "transcript": transcript,
            "keyframes": [],
            "pinned": False,
            "embedding_refs": None,
            "detection_label": label,
            "detection_confidence": detection.get("confidence"),
            "detection_reasons": detection.get("reasons") or [],
            "detection_route": detection.get("route"),
            "detection_speech_seconds": detection.get("speech_seconds"),
            "detection_word_count": detection.get("word_count"),
            "detection_turn_count": detection.get("turn_count"),
        }
        scene["critique"] = _critique(scene)
        stored = self.store.add_scene(scene)
        scene_id = stored.get("id")
        thumb_url = ("https://cdn.helloscene.xyz/t/%s.jpg" % scene_id
                     if scene_id else "")
        keyframe_urls = (["https://cdn.helloscene.xyz/k/%s/0.jpg" % scene_id]
                         if scene_id else [])
        try:
            stored = self.store.update_scene(
                scene_id, thumb_url=thumb_url, keyframes=keyframe_urls)
        except (AttributeError, KeyError, TypeError):
            stored["thumb_url"] = thumb_url
            stored["keyframes"] = keyframe_urls
        return stored
```

## 4. Backfill interaction the integrator must understand

`_backfill_timestamps` fills missing segment/word timestamps from the
chunk window (`start_ts`/`end_ts`, which are ISO strings at this point
in the pipeline). `autodetect._clean_word` only accepts numeric
timestamps, so a backfilled ISO string is treated as "no usable
timestamp" (it is dropped, not parsed as a time). Consequences, all
safe-direction:

- Real faster-whisper chunks: float word timestamps survive, so
  `duration_known` is True and the skip test needs BOTH legs: fewer
  than 10 words AND under 3.0s of speech. A short-but-clear utterance
  (e.g. 7 words over ~3-4s) still analyzes.
- Mock / timestamp-less chunks: backfilled words carry ISO strings,
  so `duration_known` is False and the skip test falls back to word
  count alone (under 10 words -> ambient). A sub-10-word chunk with no
  timing is far more likely a noise hallucination than a promise; the
  module documents this fallback explicitly.
- Do NOT "fix" backfill to emit numeric timestamps for autodetect's
  benefit: giving every word the full chunk window would inflate
  `speech_seconds` to the cap and break the duration leg. Leave
  backfill untouched.

One documented divergence from INTEGRATION.md §5: that guide says an
empty transcript routes to analyze. The landed module treats a clean
empty input (no words, empty transcript, not malformed) as `silent` /
`mark_and_skip`, stored as a minimal scene. That is NOT a silent drop:
the scene row, timeline entry, and broadcast all still happen, with the
real (empty) transcript. The patch follows the landed module. If the
integrator wants the stricter INTEGRATION.md rule instead, add one
explicit guard in `_detect_chunk` (empty transcript AND empty word
list -> return `None`) and note it as a deliberate deviation; do not
silently bake it in.

## 5. Routing table

| Label | Route | What happens |
|---|---|---|
| `conversation` | `analyze` | Unchanged full path: Argon, attribution, embeddings, critique, full scene |
| `monologue` | `analyze` | Unchanged full path (one person talking is content, not noise) |
| `ambient` | `mark_and_skip` | Minimal scene (§3), no Argon / attribution / embedding calls |
| `silent` | `mark_and_skip` | Minimal scene (§3), no Argon / attribution / embedding calls |

Failure routing (see §6): every failure path lands on `analyze`, never
on a drop. Every chunk ends as a full scene or a minimal scene.

## 6. Spend booking change (Hunk 4) + the $0.07 vs $0.019 discrepancy

Before (in `process_chunk`, after a successful `_run_once`):

```python
        # Store step, in order: spend once per chunk, then indexed.
        self.store.add_spend(_SPEND_PER_CHUNK_USD)
        self.store.update_chunk_status(chunk_id, "indexed")
```

After:

```python
        # Store step, in order: spend once per chunk, then indexed.
        # Skipped chunks cost no Argon call, so they book $0.00.
        # Full chunks book the existing flat figure, unchanged.
        if (stored_scene or {}).get("detection_route") == "mark_and_skip":
            self.store.add_spend(0.00)
        else:
            self.store.add_spend(_SPEND_PER_CHUNK_USD)
        self.store.update_chunk_status(chunk_id, "indexed")
```

**The discrepancy, stated plainly so nobody misreads the dashboard:**

- `_SPEND_PER_CHUNK_USD = 0.07` is the current flat per-chunk booking
  figure in `ingest.py`. It is NOT the Argon call cost.
- The module docs (README.md / INTEGRATION.md) put the Argon analysis
  call at ~$0.019 per chunk (dense-frame path; the older figure was
  ~$0.010). That $0.019 is the real cash saving per skipped chunk.
- So booking $0.00 for a skipped chunk makes the spend total fall by
  $0.07 per skip, while the real Argon saving is only ~$0.019. The
  $0.07 figure evidently bundles more than the Argon call (or is a
  conservative booking figure); this patch does not investigate or
  change it, and the integrator must NOT "fix" it here.
- Rules that follow: do NOT book the $0.019 saving as a negative spend;
  do NOT subtract skipped chunks from the total anywhere else; do NOT
  change what a full chunk books; do NOT quote "$0.07 saved per skip"
  as a cash saving (the honest cash figure is ~$0.019, the dashboard
  figure is $0.07 of booking avoided). True cost accounting (splitting
  the flat figure into Argon vs other) is separate work, not this patch.
- Detection itself costs $0: stdlib only, local, no API call, on every
  chunk including analyzed ones.

## 7. Failure defaults (complete list)

| Situation | Behavior | Why it is safe |
|---|---|---|
| `autodetect.py` missing at import | `_detect is None` -> `_detect_chunk` returns `None` -> analyze, one warning log line | Pipeline runs exactly as today |
| `detect()` raises (despite its never-raise promise) | Caught in `_detect_chunk` -> `None` -> analyze, warning logged | A detector bug can never fail or skip a chunk |
| Malformed input (wrong types, non-dict words, missing keys) | Module sanitizes; if it would otherwise skip, returns `monologue` / `analyze`, confidence 0.5, with a reason saying so | Malformed evidence never earns a skip |
| Uncertain / low-confidence | Module routes to `analyze` unless the evidence cleanly meets the ambient/silent test | A wrongly analyzed ambient chunk costs ~$0.019; a wrongly skipped conversation loses content |
| Clean silence / ambient | `mark_and_skip` -> minimal scene, chunk `"indexed"`, broadcast as normal | Stored and visible, not dropped |
| Minimal-scene store fails | Exception propagates -> retry loop -> chunk `"failed"` + WS error | Never a fake success, never `None` as scene |
| Analyzer / attributor / store failure on analyze path | Unchanged: retry, then `"failed"` + WS error | Detection adds no new failure mode there |

## 8. Apply guide (step by step)

1. **Re-verify first** (see the warning at the top): diff `_run_once`
   against the current repo backend; confirm anchors; confirm which
   backend copy (repo vs Mac running copy) is being patched.
2. From the autodetect folder, confirm both pass before wiring:
   `python3 autodetect.py` (self-test, 9/9 at time of writing) and
   `python3 test_autodetect.py`. If either fails, stop; do not wire.
3. Copy `autodetect.py` into the backend package as `app/autodetect.py`
   (same directory as `ingest.py`). Copy `test_autodetect.py` alongside
   it for the retest step, or keep tests out of the deployed package
   and run them from the swarm folder; either way, the import in §2
   must resolve.
4. Apply Hunk 1 (guarded import), Hunk 2 (call site), Hunk 3 (helpers),
   Hunk 4 (spend branch), all in `app/ingest.py` only. No changes to
   `routes.py`, `services.py`, the API contract, the bridge, the phone
   app, the lens page, the Critic, follow-through, or Ask.
5. Do NOT change thresholds in `autodetect.py` at integration time.
   Do NOT change `_backfill_timestamps`. Do NOT change the flat $0.07
   booking for full chunks.
6. Restart the backend copy being tested (only after step 1), then run
   §9. Keep the pre-patch backend copy runnable as fallback until §9
   passes; feature freeze is 7:30 PM PDT, submission 10:00 PM PDT, so a
   failed retest means reverting to analyze-everything, not debugging
   live on the demo phone.

## 9. Retest checklist after restart

- [ ] **Module sanity (before restart):** `python3 autodetect.py`
  9/9, `python3 test_autodetect.py` green, from the autodetect folder.
- [ ] **Conversation chunk:** record a real back-and-forth chunk ->
  full scene with Argon draft, chunk `"indexed"`, $0.07 booked (flat
  figure, unchanged), appears on phone timeline in order.
- [ ] **Monologue chunk:** one person talking steadily -> full scene,
  same as conversation. (Mislabels between conversation and monologue
  cost nothing: same route.)
- [ ] **Ambient chunk:** background noise / fragments, few words ->
  minimal scene with summary `"No conversation detected"`,
  `verified: false`, all seven `detection_*` fields present, chunk
  `"indexed"`, **$0.00 booked**, timeline shows the chunk in order
  with no gap.
- [ ] **Silent chunk:** near-silence -> minimal scene, confidence
  `"silence"`, same spend/timeline checks as ambient.
- [ ] **Ask:** whole-session Ask still works and reasons over the
  session including minimal scenes (their real short transcripts are
  in context; no crash on the placeholder summary).
- [ ] **Follow-ups:** follow-through generation still verifies quotes
  against transcripts; minimal scenes' quotes (first line or `""`)
  do not produce fabricated follow-ups.
- [ ] **Lens:** lens timeline still renders every chunk in order,
  including minimal scenes; no hole where a skipped chunk was.
- [ ] **Phone timeline:** same check on Isabella's demo phone over LAN
  (backend LAN 10.1.63.33 in the pre-patch setup; re-confirm the LAN
  address at test time, do not assume it).
- [ ] **Failure paths:** (a) temporarily rename `app/autodetect.py`
  away and restart -> every chunk analyzes (no crash, no skip);
  restore and restart. (b) Empty-transcript chunk -> per §4, minimal
  `silent` scene (or analyze, if the integrator took the stricter
  guard; record which behavior was chosen). (c) Spend delta check:
  one skipped chunk moves total spend by $0.00, one full chunk by
  $0.07; do not expect a $0.019 line item anywhere.
- [ ] **Rollback:** if any check above fails, revert `app/ingest.py`
  to the pre-patch copy (analyze-everything) and restart; the demo
  without autodetect is strictly better than a broken ingest.

## 10. What this patch deliberately does not do

- No Cloud SQL, no Managed Agents wiring, no Srijan backend changes,
  no phone/lens changes. Those are other workers' scope.
- No threshold tuning, no VAD, no diarization, no new routes, no
  contract change, no key/credential handling (none appear in this patch).
- No claim about native video, frame counts beyond what `ingest.py`
  already does, or Argon Interactions internals beyond the one-call-
  per-chunk shape verified in `services.py` comments.

## Sources verified for this patch

- `~/workspace/scene-backend/app/ingest.py` (plug point, spend constant,
  scene shape, retry/broadcast behavior, critic import pattern).
- `~/workspace/scene-fix-swarm/autodetect/autodetect.py` (API, return
  keys, thresholds, never-raise contract, self-test 9/9).
- `~/workspace/scene-fix-swarm/autodetect/INTEGRATION.md` (routing,
  minimal-scene field list, spend note) — with the §1.3 string-words
  correction above, which overrides its sketch.
- `~/workspace/scene-backend/app/routes.py` (`start_ts`/`end_ts` ISO
  strings, `now_iso()`), `app/services.py` (transcriber segment shape,
  `"silence"` as an allowed confidence value) — read-only cross-checks
  only; this patch touches neither file.
