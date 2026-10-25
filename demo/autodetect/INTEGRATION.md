# Auto conversation detection: backend integration guide

Standalone module, not yet wired into the running backend. This guide tells
Nayan / Isabella exactly where the call goes and what changes. It edits
nothing itself: the integrator makes the backend change, in
`~/workspace/scene-backend/app/ingest.py` (and one small spend branch in
`process_chunk` in the same file).

Module status note: `autodetect.py` had not landed in this folder when
this guide was written, so every name below follows the shared contract
exactly. If the landed module renames a function or a key, update this
guide to match the module; the module is the source of truth for names
and thresholds.

## 0. What this is

Scene records whatever the user captures. Today every 30s chunk goes
through the same path: transcribe, then Argon analysis, then a full
scene. There is currently NO conversation detection.

`autodetect.py` adds one cheap, stdlib-only gate between transcription
and analysis: speech-presence plus dialogue-pattern detection over the
transcript text and word timestamps. It does NOT do diarization, it
never identifies a speaker, and it adds no dependency and no ML model.
See README.md for the module itself.

Contract (exact):

```python
detect(transcript: str, words: list, chunk_duration_s: float) -> dict
# returns keys: label, confidence, reasons, route,
#               speech_seconds, word_count, turn_count
```

Labels: `conversation`, `monologue`, `ambient`, `silent`.
Routes: `analyze`, `mark_and_skip`.

## 1. Plug point: after transcribe, before analyze

Verified against `~/workspace/scene-backend/app/ingest.py`.

The pipeline is `IngestPipeline` in `ingest.py`:

- `process_chunk(session_id, start_ts, end_ts, video_path, audio_path)`
  creates the chunk (`store.create_chunk`), marks it `processing`, and
  retries `_run_once` up to `_MAX_RETRIES` times (4 attempts total).
  On success it books spend, marks the chunk `indexed`, and broadcasts
  the scene summary + status. On failure it marks the chunk `failed`
  and broadcasts an error.
- `_run_once(session_id, start_ts, end_ts, video_path, audio_path)` is
  where the work happens, in this order:
  1. `_extract_frames(video_path)` (dense 1fps frames, 6-frame fallback,
     mock placeholder fallback; never raises).
  2. `self.transcriber.transcribe(audio_path)` -> segments
     (`{speaker_label, text, start_ts, end_ts, word_timestamps}`),
     then `self._backfill_timestamps(segments, start_ts, end_ts)`.
     The real transcriber is `FasterWhisperTranscriber` in
     `app/services.py`; its `speaker_label` is always `"Unknown"`.
  3. `self.analyzer.analyze(keyframes)` -> draft
     (`ArgonSceneAnalyzer` in `app/services.py`: one Argon
     Interactions call per chunk).
  4. `self.attributor.attribute(segments, keyframes, draft["people"])`
     (`FaceVoiceAttributor` in `app/services.py`: an intentional stub,
     always `Unknown`, never a guessed name).
  5. Transcript built from the attributed segments, embeddings computed
     (not persisted), scene dict built, `_critique(scene)`, then
     `store.add_scene(scene)` (the store assigns the id) and
     `store.update_scene(scene_id, thumb_url=..., keyframes=...)`.

The detection call goes in `_run_once`, between step 2 and step 3:
after `transcribe` + `_backfill_timestamps`, before
`self.analyzer.analyze(keyframes)`. Nowhere else. Do not put it in
`process_chunk`, in `routes.py` (`_handle_chunks` just hands the
multipart video/audio to `process_chunk`), or in `services.py`.

Inputs, built from what `_run_once` already has at that point:

- `transcript`: the segment texts joined, e.g.
  `"\n".join(seg.get("text", "") for seg in segments)`.
- `words`: the word strings flattened out of every segment's
  `word_timestamps`, e.g.
  `[w.get("word", "") for seg in segments
   for w in (seg.get("word_timestamps") or [])]`.
- `chunk_duration_s`: the chunk window length in seconds as a float.
  `start_ts` / `end_ts` arrive as ISO strings (see `_handle_chunks`
  in `routes.py`, which defaults them with `now_iso()`), so parse them
  to seconds and subtract; if parsing fails, fall back to `30.0`
  (the standard chunk length).

Code sketch (guide only, not a patch):

```python
from autodetect import detect  # stdlib-only module, lives next to the backend

# ... inside _run_once, after _backfill_timestamps, before analyze ...
try:
    detection = detect(
        "\n".join(seg.get("text", "") for seg in segments),
        [w.get("word", "") for seg in segments
         for w in (seg.get("word_timestamps") or [])],
        chunk_duration_s,
    )
except Exception:
    detection = None  # detector failure -> analyze (see section 5)

if detection is not None and detection.get("route") == "mark_and_skip":
    stored = self._store_minimal_scene(
        session_id, start_ts, end_ts, segments, detection)
    return stored  # process_chunk still marks indexed + broadcasts

draft = self.analyzer.analyze(keyframes)  # unchanged current path
```

Two placement facts the integrator must respect:

- Frame extraction (step 1) already ran before this point, so skipping
  a chunk saves the Argon call only, not the local ffmpeg work. That is
  fine: ffmpeg is local and cheap, Argon is the cost.
- The `finally` in `_run_once` deletes the frame temp files. A
  `mark_and_skip` return from inside the `try` still runs that
  `finally`, so no extra cleanup is needed as long as the branch stays
  inside `_run_once`. Do not branch around `_run_once` from
  `process_chunk`: the retry loop, the `finally` cleanup, and the
  broadcast path all live there for a reason.

Import placement: import `detect` lazily or at the top of `ingest.py`
so that a missing module degrades to analyze-everything (section 5),
never to a crashed chunk. Suggested shape:

```python
try:
    from autodetect import detect as _detect
except ImportError:
    _detect = None
# ... and in _run_once: if _detect is None, skip detection entirely.
```

## 2. Routing table

Fixed routing table (verbatim):

- conversation -> analyze
- monologue -> analyze
- ambient -> mark_and_skip
- silent -> mark_and_skip

### analyze: the unchanged current path

`conversation` and `monologue` chunks go through exactly what happens
today: `analyzer.analyze(keyframes)`, attribution, embeddings,
`_critique`, `store.add_scene` with the full scene dict, thumbnail /
keyframe URL patch, spend booked, chunk `indexed`, scene broadcast.
No field, prompt, or threshold in the analyzer changes. A monologue is
still analyzed: one person talking is content, not noise.

### mark_and_skip: minimal scene, no Argon call

`ambient` and `silent` chunks skip `analyzer.analyze`,
`attributor.attribute`, and the embedding calls, and instead store a
minimal scene record through the same `store.add_scene` so the timeline
stays complete. The minimal scene keeps the same field shape as a full
scene (the store in `app/sqlite_store.py` / `app/postgres_store.py`
`setdefault`s anything missing, but pass the fields explicitly anyway
so phone and lens readers never see a shape change):

- `session_id`, `start_ts`, `end_ts`: the chunk window, unchanged.
- `summary`: empty, or a short label-derived placeholder such as
  "No conversation detected". Never a fabricated Argon-style summary.
- `quote`: the first transcript line if one exists, else `""`.
- `transcript`: the real transcript lines from the attributed-shape
  build (speaker `"Unknown"`, text, timestamps). Transcription already
  ran and costs nothing extra, and keeping it means Ask and
  follow-through can still see what little was said.
- `type`: keep a valid existing value (the full path uses e.g.
  `"conversation"`); the detection label lives in the detection fields
  below, not in `type`.
- `verified`: `False`. A skipped chunk is never verified.
- `confidence`: `"review"`, except a `silent` chunk may use `"silence"`
  (the value `ArgonSceneAnalyzer._sanitize_confidence` already allows).
- `objects`, `people`, `actions`, `visible_text`: `[]`.
- `critique`: run the existing `_critique(scene)` call on the minimal
  scene, same as the full path, so the field is never missing.
- `thumb_url`, `keyframes`: patched in after `add_scene` returns, by
  the same `update_scene` code as the full path.
- `pinned`: `False`. `embedding_refs`: `None` (same as today: embeddings
  are computed but not persisted in this phase).
- Detection fields, added on minimal scenes only (full scenes keep
  their existing fields exactly):
  - `detection_label`: `detection["label"]`
  - `detection_confidence`: `detection["confidence"]`
  - `detection_reasons`: `detection["reasons"]`
  - `detection_route`: `detection["route"]` (`"mark_and_skip"`)
  - `detection_speech_seconds`: `detection["speech_seconds"]`
  - `detection_word_count`: `detection["word_count"]`
  - `detection_turn_count`: `detection["turn_count"]`

After the minimal scene is stored, return it from `_run_once` exactly
like a full scene. `process_chunk` then marks the chunk `indexed` and
broadcasts the scene summary + status with no changes, so the phone
timeline shows the chunk in order with its neighbors. A skipped chunk
is a visible gap-free timeline entry, not a hole.

## 3. What does NOT change

- The Record button stays the session trigger. Detection runs only on
  chunks the user already recorded. There is no always-on listening,
  no background capture, and no wake-word path.
- No speaker identity anywhere. Detection uses speech presence and
  dialogue patterns only. `speaker_label` stays `"Unknown"`,
  `FaceVoiceAttributor` stays a stub, and no diarization model is
  installed, imported, or called. `turn_count` counts turns in the
  dialogue pattern; it is not a speaker count and must never be
  presented as one.
- The Critic is untouched: same `_critique` call, same checks, same
  module (`app/critic.py`). Minimal scenes go through it; they do not
  change it.
- Follow-through verification, Ask, and the phone / lens surfaces are
  untouched. Follow-through still verifies quotes against transcripts
  with code and never sends without a tap; Ask still reasons over the
  whole session context. Minimal scenes appear in that context with
  their real (short) transcripts, like any other scene.
- Existing scene fields stay the same. The only additions are the
  seven `detection_*` fields, and only on minimal scenes.
- The API contract is untouched: no new route, no changed response
  shape. `_handle_chunks` in `routes.py` still returns
  `{chunk_id, session_id, start_ts, end_ts, status: "received"}`.

## 4. Cost impact

Only `ambient` and `silent` chunks skip Argon. Each skipped chunk saves
about $0.019 of Argon analysis cost (the per-chunk analyzer call cost).
`conversation` and `monologue` chunks cost exactly what they cost
today; detection itself costs $0 (stdlib-only, local, no API call).

Spend bookkeeping, and one discrepancy to reconcile at integration time:

- Today `process_chunk` books spend unconditionally on success with
  `self.store.add_spend(_SPEND_PER_CHUNK_USD)`, where
  `_SPEND_PER_CHUNK_USD = 0.07` in `ingest.py`. That flat $0.07 booking
  does not equal the ~$0.019 Argon call cost above; it is the current
  per-chunk spend figure, and this guide does not change what a full
  chunk books.
- For a skipped chunk, the analysis cost is $0.00, and spend tracking
  must still record it so spend math stays honest: book
  `add_spend(0.00)` for `mark_and_skip` chunks instead of the flat
  figure. Recommended shape in `process_chunk`, using the detection
  fields already on the stored scene:

```python
if (stored_scene or {}).get("detection_route") == "mark_and_skip":
    self.store.add_spend(0.00)
else:
    self.store.add_spend(_SPEND_PER_CHUNK_USD)
```

- Do not book the $0.019 saving as a negative spend, and do not
  subtract skipped chunks from the total anywhere else. The honest
  record is: full chunks book the current figure, skipped chunks book
  $0.00, and the saving is visible as chunks that cost nothing.

## 5. Failure behavior

Default to analyze. Never drop a chunk silently: every chunk ends as
either a full scene or a minimal scene.

- Detection uncertain: `detect` returns a low `confidence` or an
  unclear label. Route it to `analyze`. When in doubt, spend the Argon
  call; a wrongly skipped conversation is lost content, a wrongly
  analyzed ambient chunk costs ~$0.019.
- Input malformed: empty transcript, missing `word_timestamps`,
  unparsable timestamps, wrong types. Do not crash, do not skip.
  Treat it as analyze: the full path already handles empty transcripts
  (quote `""`, mock/real draft fallback in the analyzer).
- Detector raises: wrap the `detect` call in `try/except` (see the
  sketch in section 1) and fall back to the unchanged analyze path for
  that chunk. A detector exception must never reach the `_run_once`
  retry loop as a chunk failure: retries would just re-raise it.
- Detector module fails to import: `_detect` is `None`, detection is
  skipped silently, and the pipeline runs exactly as it does today
  (analyze-everything). Log one warning line at import time so the
  missing module is visible in logs, then carry on.
- Analyzer / attributor / store failure on the analyze path: unchanged
  current behavior (retry loop, then chunk `failed` + WS error).
  Detection does not add a new failure mode to that path.
- A `mark_and_skip` branch that itself fails (e.g. `add_scene`
  raises): let it raise like any other `_run_once` failure so the
  retry loop and the `failed` status apply. Never swallow it into a
  fake success, and never return `None` as the scene.

## 6. Explicit non-goals

- No diarization. No speaker identity, no speaker labels beyond the
  existing `"Unknown"`, no enrollment, no voice or face matching.
- No always-on listening. Detection runs only on recorded chunks.
- No new dependencies. `autodetect.py` is stdlib only; the backend
  gains no install, no model download, no new service.
- No new ML models. No whisper / Argon / embedding change.
- No backend edits by this guide. This file is instructions; the diff
  is Nayan's / Isabella's, in `ingest.py` only (plus the spend branch
  in `process_chunk` in the same file).
- No changes to the API contract, the bridge, the phone app, the lens
  page, the Critic, follow-through, or Ask.
- No threshold changes at integration time. Exact threshold numbers
  live as constants in `autodetect.py`; this guide deliberately does
  not restate them, so there is exactly one place to tune them.

## 7. Integration checklist (for the integrator)

1. Drop `autodetect.py` (and its `test_autodetect.py`) where
   `ingest.py` can import it; confirm `python3 autodetect.py` and
   `python3 test_autodetect.py` pass first (see README.md).
2. Add the guarded import and the `_run_once` branch from section 1.
3. Add the minimal-scene builder (section 2) reusing the existing
   scene dict shape, `_critique`, `add_scene`, and `update_scene`
   patch code.
4. Add the `add_spend(0.00)` branch in `process_chunk` (section 4).
5. Test with one chunk of each label: conversation and monologue
   produce full scenes with Argon drafts; ambient and silent produce
   minimal scenes with all seven `detection_*` fields, chunk status
   `indexed`, and $0.00 booked.
6. Test the failure paths: detector import removed -> analyze
   everything; detector raising -> analyze that chunk; empty
   transcript -> analyze, not skip.
7. Confirm the timeline on the phone still shows every chunk in order,
   with no gaps where a skipped chunk was.
