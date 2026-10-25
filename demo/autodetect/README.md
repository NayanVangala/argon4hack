# autodetect: auto conversation detection for Scene

Standalone, stdlib-only module that decides whether a recorded chunk is
worth sending to Argon. It runs after transcription and before analysis
in the ingest pipeline, and it is NOT wired into the backend yet: see
INTEGRATION.md for the wiring guide.

No diarization, no speaker identity, no new dependencies, no ML model.
It looks only at speech presence (how much speech, from the word
timestamps) and dialogue patterns (turn-taking shape in the transcript).
Every speaker stays `"Unknown"`, exactly as the rest of Scene.

## The call

```python
from autodetect import detect

result = detect(transcript, words, chunk_duration_s)
# result keys: label, confidence, reasons, route,
#              speech_seconds, word_count, turn_count
```

- `transcript`: the chunk's transcript text (segments joined).
- `words`: the word strings flattened from the segments' word
  timestamps.
- `chunk_duration_s`: the chunk window length in seconds (float, 30.0
  for a standard chunk).

Exact threshold numbers live as constants in `autodetect.py` and are
deliberately not restated here, so there is exactly one place to tune
them.

## Labels

- `conversation`: back-and-forth speech, multiple turns. Worth analyzing.
- `monologue`: one person talking steadily. Still content, still analyzed.
- `ambient`: background noise or fragments, no real speech content. Skipped.
- `silent`: (near-)no speech in the chunk. Skipped.

## Routing

- conversation -> analyze
- monologue -> analyze
- ambient -> mark_and_skip
- silent -> mark_and_skip

`analyze` means the unchanged current path: Argon analysis and a full
scene. `mark_and_skip` means store a minimal scene record (so the
timeline stays complete), skip the Argon call, and record the label,
confidence, and reasons on that minimal scene. Each skipped chunk saves
about $0.019 of Argon cost; skipped chunks book $0.00 analysis spend.

On any uncertainty, malformed input, or detector failure, the pipeline
defaults to `analyze`. Nothing is ever dropped silently: every chunk
ends as a full scene or a minimal scene.

## Self-test

From this folder:

```sh
python3 autodetect.py
python3 test_autodetect.py
```

Run both before integrating. If either fails, do not wire the module in.

## Backend wiring

See INTEGRATION.md: plug point (`_run_once` in
`~/workspace/scene-backend/app/ingest.py`, after `transcribe`, before
`analyzer.analyze`), the minimal-scene field list, spend bookkeeping,
failure behavior, and the integration checklist. This guide edits no
backend code; Nayan / Isabella make the diff.
