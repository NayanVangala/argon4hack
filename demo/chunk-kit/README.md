# Scene chunk test kit

Ready-to-run test for one real video + audio chunk end to end:
dense frame extraction, transcription, Argon analysis, scene storage.
This kit only *runs* the test. It does not start the server, does not
call Argon directly, and contains no keys or tokens (placeholders only).

Run it on the machine that can reach the backend (the Mac running the
server, or any machine on the same LAN). The server must already be
running; this kit never starts it.

## 0. What was verified from code (read-only)

All claims below were checked against `~/workspace/scene-backend/app/` on
2026-10-25. File references are to that copy; confirm the Mac copy
matches before trusting the stale-server branch below.

### Route and fields (`app/routes.py`, `_handle_chunks`)

- Route: `POST /api/v1/chunks`
- Multipart file fields (both required): `video`, `audio`
- Optional multipart text fields: `session_id`, `start_ts`, `end_ts`
- The route writes the `video` part to a temp file with a `.mp4`
  suffix and the `audio` part to a temp file with a `.wav` suffix. It
  does not validate codecs or content types, so any readable mp4/wav
  works; mp4 + wav are simply the shapes the route assumes.
- If `session_id` is omitted, the server uses the live session, else
  its current session id. If `start_ts` is omitted it defaults to now;
  if `end_ts` is omitted it defaults to `start_ts` (a zero-length
  window, which does NOT block the upload).
- Missing part (either `video` or `audio` absent), exact response:

```text
HTTP 400
{"error": {"code": "bad_request", "message": "Missing video or audio part."}}
```

- Not multipart at all, exact response:

```text
HTTP 400
{"error": {"code": "bad_request", "message": "Expected multipart form data."}}
```

- Success, exact shape (note: `202`, not `200`):

```json
{"chunk_id": "...", "session_id": "...", "start_ts": "...",
 "end_ts": "...", "status": "received"}
```

- Auth: only enforced when the server was started with
  `AUTH_ENABLED=1`. Then a missing/wrong token gives:

```text
HTTP 401
{"error": {"code": "unauthorized", "message": "Token expired, re-pair."}}
```

  If `AUTH_ENABLED=1` but the server-side `SCENE_API_TOKEN` is unset,
  the server refuses everything (fail closed) and prints the warning
  in the log-lines section below. When auth is off, no token is needed
  and a sent `Authorization` header is ignored.

### Pipeline order (`app/ingest.py`, `_run_once` inside `process_chunk`)

1. Frame extraction: dense frames first, then the 6-frame path, then
   the mock placeholder (see below).
2. Transcription (`transcriber.transcribe(audio_path)`).
3. Analysis (`analyzer.analyze(keyframes)`).
4. Attribution, then embedding (computed, not persisted), then the
   Critic, then `add_scene`, then `update_scene` with thumb/keyframe
   URLs.
5. Only after the scene is stored: `add_spend(0.07)`, chunk status
   `indexed`, then the WebSocket broadcast (scene first, then status).

Retry behaviour: a failing `_run_once` attempt is retried up to 3 more
times (4 calls total). If all fail, the chunk is marked `failed` and
the failure surfaces as a WebSocket error only; there is no poll route
for it, and no spend is added.

### Frame extraction (`app/ingest.py`, `_extract_frames`)

- Dense path first: one ffmpeg call, `fps=1`, frames scaled to fit a
  768x768 box, capped at 30 frames (`-frames:v 30`, JPEG quality `-q:v 2`).
  This is the "dense frames" code the test is proving.
- On dense failure, the 6-frame path: one ffmpeg seek-extract per
  fraction `0.10, 0.25, 0.40, 0.55, 0.70, 0.85` of the probed duration
  (ffprobe; 30.0 s fallback if ffprobe is missing/unusable).
- If that also fails, the mock placeholder `mock://keyframes/0.jpg`
  is used and the chunk still proceeds.
- **No duration validation exists anywhere in `routes.py` or
  `ingest.py`.** A clip longer than 30 s is not rejected: dense
  extraction simply caps at the first 30 frames (1 fps). A clip
  shorter than 30 s is not rejected either: it yields fewer dense
  frames. `start_ts`/`end_ts` are form fields, never derived from the
  file's actual duration.

### Spend (`app/ingest.py`: `_SPEND_PER_CHUNK_USD = 0.07`)

Every successfully stored chunk adds exactly $0.07, mock or real
analysis alike. Status spend is rounded to 2 decimals. So a +0.07
delta proves the chunk was stored; it does NOT prove live Argon ran.
Only the scene content proves that (see step 4).

### Verification endpoints (`app/routes.py`, `app/store.py`)

- `GET /api/v1/status` returns `scene_count` and `spend_usd`
  (plus `recording`, `session_id`, `last_scene_ts`).
- `GET /api/v1/scenes/today?limit=1` returns the newest scene first.
  Its summary fields are: `id`, `start_ts`, `end_ts`, `summary`,
  `quote`, `thumb_url`, `type`, `verified`, `confidence`.
- `GET /api/v1/scenes/<id>` returns the detail fields: `id`,
  `session_id`, `start_ts`, `end_ts`, `summary`, `objects`, `people`,
  `actions`, `visible_text`, `type`, `confidence`, `critique`,
  `transcript`, `keyframes`, `pinned`.
- **Detail omits `quote`, `verified`, and `thumb_url` by contract
  shape** (routes `_DETAIL_FIELDS`). So verify the quote from the
  summary endpoint, and verify `transcript[0].text` in the detail
  (ingest sets the scene quote to the first transcript line's text).

### Server log lines: what actually exists

There are **no success log lines** for the individual pipeline steps.
`ingest.py` and `services.py` only log warnings on fallback; nothing
is printed when frames, transcription, or analysis succeed. Do not
wait for a "frames extracted" or "analysis done" line: it will never
appear. The lines that do exist, quoted verbatim from code (`%s`/`%r`
are filled in at runtime):

Request line, printed for every request (`routes.py`, `log_message`):

```text
POST /api/v1/chunks
```

Server startup (`server.py`):

```text
Scene backend REST on http://localhost:8000/api/v1
Scene backend WS live on ws://localhost:8000/api/v1/live
```

Frame fallbacks (`ingest.py`, `logger.warning`):

```text
[ingest] dense extraction skipped: ffmpeg not found on PATH
[ingest] dense frame extraction failed (%s), falling back to 6-frame path
[ingest] keyframe extraction failed (%s), falling back to mock placeholder
```

Transcription fallbacks (`services.py`, `logger.warning`):

```text
FasterWhisperTranscriber: faster-whisper/model unavailable (%s); falling back to mock transcript.
FasterWhisperTranscriber: transcribe failed (%s); falling back to mock transcript.
```

Analysis fallbacks (`services.py`, `logger.warning`):

```text
ArgonSceneAnalyzer: zero real frames (placeholders only); returning mock draft.
ArgonSceneAnalyzer: no GEMINI_API_KEY/GOOGLE_API_KEY in environment; returning mock draft.
ArgonSceneAnalyzer: Argon call/parse failed (%s); returning mock draft.
```

Auth fail-closed warning (`routes.py`, printed):

```text
WARNING: AUTH_ENABLED is on but SCENE_API_TOKEN is unset; refusing all requests (fail closed).
```

Expected order on a healthy run: `POST /api/v1/chunks`, then
silence (success has no log lines). Any fallback warning above, in
pipeline order (dense, then 6-frame, then transcribe, then analyze),
means that step degraded to mock; the upload still returns 202.

## 1. Generate the clip

```bash
./make-chunk.sh
```

This creates `chunk-test.mp4` (testsrc2 video, 640x360, 30 fps) and
`chunk-test.wav` (440 Hz tone, 16 kHz mono), each 30 s, in the current
directory. To put them elsewhere: `./make-chunk.sh /path/to/outdir`.

If ffmpeg/ffprobe is missing, the script prints install instructions
(`brew install ffmpeg` on macOS, `sudo apt install ffmpeg` on
Ubuntu/Debian) and exits 1; it does not fail silently.

## 2. Verify duration

`make-chunk.sh` already runs this check and fails if either file is
outside 29.5-30.5 s. To re-check by hand:

```bash
ffprobe -v error -show_entries format=duration \
  -of default=noprint_wrappers=1:nokey=1 chunk-test.mp4
ffprobe -v error -show_entries format=duration \
  -of default=noprint_wrappers=1:nokey=1 chunk-test.wav
```

Both should print a value near `30.0`.

## 3. Phone-record-and-trim fallback (second path)

If you would rather use a real phone recording than the synthetic clip:

1. Record a video on the phone (at least 30 s; any format, e.g. `.mov`).
2. Transfer it to the Mac, e.g. as `phone-raw.mov`.
3. Trim to exactly the first 30 s and split into the two parts the
   route expects:

```bash
ffmpeg -y -i phone-raw.mov -t 30 -c:v libx264 -pix_fmt yuv420p phone-trim.mp4
ffmpeg -y -i phone-trim.mp4 -vn -ac 1 -ar 16000 phone-trim.wav
ffprobe -v error -show_entries format=duration \
  -of default=noprint_wrappers=1:nokey=1 phone-trim.mp4
ffprobe -v error -show_entries format=duration \
  -of default=noprint_wrappers=1:nokey=1 phone-trim.wav
```

Notes:

- `-t 30` keeps the first 30 s. To trim a later 30 s window instead,
  put `-ss <start>` before `-i`, e.g.
  `ffmpeg -y -ss 10 -i phone-raw.mov -t 30 ...`.
- If the phone clip is shorter than 30 s, ffmpeg does not error; it
  just outputs a shorter file. Check the ffprobe durations: a short
  clip still uploads and still passes (fewer dense frames), but it is
  not a full 30 s test, so re-record if you need the full window.
- Then upload with the trimmed names (step 4), e.g.
  `./upload-chunk.sh phone-trim.mp4 phone-trim.wav`.

## 4. Upload and verify, in order

Set the base URL once (default `http://localhost:8000`; for LAN use,
the Mac's LAN address and port 8000):

```bash
export BASE_URL=http://localhost:8000
# LAN example only (replace with the Mac's actual LAN IP):
# export BASE_URL=http://<MAC_LAN_IP>:8000
```

### 4a. Status BEFORE

```bash
curl -s "$BASE_URL/api/v1/status" | python3 -m json.tool
```

Write down `scene_count` (call it BEFORE_COUNT) and `spend_usd`
(call it BEFORE_SPEND).

### 4b. Upload

```bash
./upload-chunk.sh chunk-test.mp4 chunk-test.wav
```

Or, to pin the chunk to a session, first create one and pass its id:

```bash
curl -s -X POST "$BASE_URL/api/v1/sessions" | python3 -m json.tool
SESSION_ID=<id-from-above> ./upload-chunk.sh chunk-test.mp4 chunk-test.wav
```

Expected: HTTP `202` and
`{"chunk_id": "...", "session_id": "...", "start_ts": "...", "end_ts": "...", "status": "received"}`.
If the server runs with `AUTH_ENABLED=1`, add the token via the
environment (never in a file):

```bash
SCENE_API_TOKEN=<server-token> ./upload-chunk.sh chunk-test.mp4 chunk-test.wav
```

### 4c. Status AFTER: count + 1, spend + 0.07

```bash
curl -s "$BASE_URL/api/v1/status" | python3 -m json.tool
```

Pass criteria:

- `scene_count` equals BEFORE_COUNT + 1.
- `spend_usd` equals BEFORE_SPEND + 0.07 (rounded to 2 decimals).
- No other uploads or Ask calls between the BEFORE and AFTER reads,
  or the spend delta will include those too (Ask adds its own spend).

### 4d. Newest scene: summary, quote, confidence

```bash
curl -s "$BASE_URL/api/v1/scenes/today?limit=1" | python3 -m json.tool
```

Pass criteria on `scenes[0]`:

- `summary` is non-empty.
- `quote` is non-empty.
- `confidence` is present (`verified`, `review`, or `silence`).

Then fetch its detail (replace `<id>` with `scenes[0].id`):

```bash
curl -s "$BASE_URL/api/v1/scenes/<id>" | python3 -m json.tool
```

Pass criteria: `summary` and `confidence` match the summary endpoint,
and `transcript` is non-empty (`transcript[0].text` should equal the
summary endpoint's `quote`). Remember detail has no `quote` field;
its absence is contract shape, not a failure.

### 4e. Live vs mock: read the content, not just the counts

- **Live Argon pass:** the summary describes the test clip content
  (synthetic pattern / tone, or the real phone scene) in its own
  words, and the transcript reflects the actual audio. For the
  synthetic clip, real faster-whisper over a pure 440 Hz tone may
  return little or no speech; that is a transcription result, not a
  pipeline failure, as long as the scene was still stored.
- **Mock fallback (any step degraded):** the summary is exactly
  `Live chunk indexed (mock scene)` and the transcript text is
  exactly `Live segment (mock transcript).` (both strings are the
  fixed mocks in `services.py`). If you see those, check the server
  log for the fallback warning lines above to learn which step fell
  back, then see the failure branches below.

### 4f. Server log lines, in order

On the server terminal, in order:

1. `POST /api/v1/chunks`
2. Nothing else on success (there are no success lines).
3. On degradation, the matching warning line(s) above, in pipeline
   order: dense-frame warning, then 6-frame warning, then transcribe
   warning, then analyzer warning.

## 5. Failure branches

| Symptom | Cause (verified) | Fix |
|---|---|---|
| `ffmpeg: command not found` from `make-chunk.sh`, or the script's install message | ffmpeg/ffprobe not installed | `brew install ffmpeg` (macOS) or `sudo apt install ffmpeg` (Ubuntu/Debian), then re-run `./make-chunk.sh` |
| `ERROR: file not found` from `upload-chunk.sh` | Clip not generated, or wrong directory | Run `./make-chunk.sh` first, or pass the real paths: `./upload-chunk.sh phone-trim.mp4 phone-trim.wav` |
| `curl: Failed to connect` / connection refused | Server not running, or wrong `BASE_URL`/port | Start the server on the Mac first (this kit never starts it); check `BASE_URL` and that port 8000 is reachable from this machine |
| HTTP 400 `Missing video or audio part.` | One part omitted | Re-run `./upload-chunk.sh` with both files. Reproduce deliberately with: `curl -s -F video=@chunk-test.mp4 "$BASE_URL/api/v1/chunks"` (audio omitted) |
| HTTP 400 `Expected multipart form data.` | Body was not multipart (e.g. a JSON POST) | Use `./upload-chunk.sh` (it uses `-F` multipart fields); do not POST JSON to this route |
| HTTP 401 `Token expired, re-pair.` | Server runs with `AUTH_ENABLED=1` and the token was missing/wrong | Re-run with the server's token in the environment only: `SCENE_API_TOKEN=<server-token> ./upload-chunk.sh ...`. Never write the token into a file |
| Every request 401 plus the fail-closed warning in the server log | `AUTH_ENABLED=1` but the server-side `SCENE_API_TOKEN` is unset | Set the token in the server's environment and restart the server |
| HTTP 500 `Internal error.` | Server-side exception (routes map all unexpected errors to this generic envelope) | Check the server terminal for a traceback; the response body deliberately carries no detail |
| 202, but summary is exactly `Live chunk indexed (mock scene)` | A step fell back to mock | Read the server log: `no GEMINI_API_KEY/GOOGLE_API_KEY in environment` means the server was started without a key (restart it with the key in its environment; key placeholder only, never committed here). `zero real frames` means frame extraction produced nothing usable (check ffmpeg on the server and that the video file is readable). `faster-whisper/model unavailable` means faster-whisper is not installed on the server (transcript falls back; scene still stores) |
| 202, but scene count did not increase | A concurrent read raced, or the chunk went to a different store (e.g. server restarted into a fresh memory store) | Re-read status, confirm you are hitting the same server/`BASE_URL` and the same store backend; re-run the BEFORE/AFTER pair with no other activity in between |
| Stale server without dense code | **Not observable from the API or logs**: dense success has no log line, and the detail endpoint returns a single CDN keyframe placeholder URL regardless of frame count | Confirm on the Mac itself that the running server's `app/ingest.py` contains `_extract_dense_frames` and `_DENSE_FPS`. Do not try to infer dense vs 6-frame from timings or API output |
| Clip longer than 30 s | Not an error: no duration validation; dense extraction caps at 30 frames | Trim with `-t 30` (see phone fallback) if you want a strict 30 s test |
| Clip shorter than 30 s | Not an error: fewer dense frames, still 202 | Re-record/trim a full 30 s clip if the test must cover the full window |

## 6. Claims this kit could NOT verify from code (stated plainly)

- **No per-step success log lines exist.** The "expected server log
  lines in order" for a healthy run are just `POST /api/v1/chunks`
  followed by silence. Any guide claiming a success line per pipeline
  step would be inventing it.
- **Dense vs 6-frame extraction cannot be distinguished via the API
  or logs.** Both paths succeed silently; only reading the running
  server's `ingest.py` on the Mac settles which code is live.
- **Chunk duration is never validated.** "Too long" and "too short"
  are not error cases in code; they only change how many dense frames
  exist. The +0.07 spend and count checks pass for both.
- **The scene detail endpoint has no `quote` field.** A check that
  reads `quote` from `GET /api/v1/scenes/<id>` will fail even on a
  healthy run; read `quote` from the summary list endpoint instead.
- **The spend delta assumes no concurrent activity.** Ask calls add
  spend too, so the +0.07 check is only valid with no other traffic
  between the BEFORE and AFTER status reads.

## Files in this kit

- `make-chunk.sh` — generates `chunk-test.mp4` + `chunk-test.wav`
  (30 s each) with an ffprobe duration check.
- `upload-chunk.sh` — POSTs to `$BASE_URL/api/v1/chunks`
  (default `http://localhost:8000`) with `video` + `audio` fields,
  optional `session_id`/`start_ts`/`end_ts`, and an optional Bearer
  token from `SCENE_API_TOKEN` only when auth is on.
- `README.md` — this file.
