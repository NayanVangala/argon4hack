# Scene wiring runbook: backend to phone to lens to glasses, in 10 minutes plus the glasses track

## Honest constraint, read first

No agent can tap Nayan's phone, type in his terminal, or pair his
glasses. Every step below is written for Nayan to execute himself:
exact commands, exact taps, exact expected outputs, and a failure
branch for every step. Nothing in this runbook is done by an agent.
Nothing here requires a live Argon call, a server restart, or a key
from an agent; the reader supplies the key from the provisioned AI
Studio account, in his own terminal only.

## 0. Demo-phone decision (decide this before any build or install)

Primary: Isabella's phone is the demo phone. Build and install from
Isabella's Mac onto her phone. Reason: the SceneApp Xcode project
hardcodes her signing identity, team `C9FJ8G22S9` and bundle ID
`com.isabelladoan.sceneapp`. Building from her Mac onto her phone
matches that identity, so there is no signing fight. Do not change
the team or bundle ID to make a build pass; if Xcode complains about
signing, stop and sort it out with Isabella.

Fallback: Nayan's phone, only if Isabella's phone is unavailable.
COORDINATION STEP FIRST, before any build or project edit: confirm
with Isabella before changing the team or bundle ID, or arrange for
the build to go out under her team. No fallback build happens until
that conversation has happened. Once agreed, redo all phone taps on
the fallback phone from scratch: Developer settings live in that
phone's saved preferences, not in the repo, so they do not carry over.

Whichever phone is the demo phone, it must be on the same venue
Wi-Fi as Nayan's Mac backend for the whole demo. A phone on cellular
cannot reach the Mac's LAN address.

Nuance: the team and bundle ID live in the SceneApp project, not in
the SceneBridge project. The bridge project uses bundle ID
`com.scene.bridge` with no hardcoded team, and its README says to
pick a Development Team in Signing and Capabilities. The team rule
above is still stated for both builds, and the team must not be
changed without Isabella on either project.

## 10-minute execution order

This is the fast path, backend plus app plus lens plus one real
chunk, with seeded data proving the whole chain before any glasses
work. The glasses track (Part 6) is separate: start it early in
parallel or after this path, because first-time pairing is the
wildcard and does not fit in 10 minutes.

1. Part 1, backend, about 2 minutes: kill the old server, export the
   key, restart, verify status.
2. Part 2, phone, about 2 minutes: mock OFF, bare base URL, Reload,
   confirm real scenes.
3. Part 3, seeded test, about 3 minutes: Memory, two Asks, generate,
   approve, refuse, Day screen.
4. Part 4, lens, about 1 minute: URL with `?api=`, live scene check,
   Day screen check.
5. Part 5, real chunk, about 2 minutes: ffmpeg clip, upload, confirm
   the new scene.
6. Part 6, glasses plus band, own track: Developer Mode, register
   without the band, bridge order, frame proof, band last.

---

## Part 1. Backend wiring (Mac Terminal)

Do every step on the Mac, in Terminal. The server runs in the
foreground: keep its Terminal window open for the whole demo. Open a
second Terminal window for the checks. Run from the Mac copy at
`~/scene-backend`, never from a repo clone directory. Nothing here
spends anything by itself: spend only moves when a chunk is ingested
(+0.07) or an Ask runs (+0.12, or the real Argon dollar cost when
the API returns one).

### Step 1: Kill anything already on port 8000

```sh
lsof -ti:8000 | xargs kill
lsof -i:8000
```

If the second command prints nothing, the port is free. If the first
printed nothing, nothing was listening, which is also fine. If a
process survives, see Failure A.

### Step 2: Go to the backend directory

```sh
cd ~/scene-backend
ls server.py scene.db
```

Both names must print. If `scene.db` is missing, do not panic and do
not copy one in from somewhere else: the server creates a fresh one
and seeds it on first start (see Failure C).

### Step 3: Export the key in this same Terminal window

```sh
export GEMINI_API_KEY='PASTE_YOUR_KEY_HERE'
```

Replace the placeholder with the key from the provisioned AI Studio
account. That is a placeholder, not a real key, and no real key
belongs in any file, in the repo, or in the app. Rules that matter:
export in the same window you will run the server from, and before
you start it (a running server never picks up a key exported
afterwards); every new Terminal window needs its own export; never
put the key in a file (`server.py` reads it from the environment
only).

Check without ever printing the key:

```sh
[[ -n "$GEMINI_API_KEY" ]] && echo "key is set" || echo "key is NOT set"
```

If it says NOT set, retype the export in this window. Do not proceed
expecting live Argon until it says set, unless you are deliberately
running in mock mode (see step 6).

### Step 4: Run the server

```sh
python3 server.py
```

Leave this window alone. It stays in the foreground until you stop
it with Ctrl-C. You should see exactly these two lines (port 8000
is the default; a `PORT` variable overrides it):

```
Scene backend REST on http://localhost:8000/api/v1
Scene backend WS live on ws://localhost:8000/api/v1/live
```

Those two lines do NOT prove live Argon. They print whether the key
is present or not. Step 6 is the only way to tell. Note: the
dense-frame code (1 frame per second, capped at 30 frames per chunk)
is already in this copy, but the previously running server was
started from older code. This restart is what activates it. There is
no success log line for dense extraction, so do not go looking for
one.

### Step 5: Verify status from a second Terminal window

```sh
curl -s http://localhost:8000/api/v1/status
```

Expected output for a fresh seeded database:

```json
{"recording": false, "session_id": "<a uuid, yours will differ>", "scene_count": 8, "last_scene_ts": "2026-10-25T12:10:00-07:00", "spend_usd": 1.84}
```

Read it field by field: `recording: false` is correct for seeded
data (the seed session is ended, not live; it flips to `true` only
after a session starts); `session_id` is a uuid and any uuid is
fine; `scene_count: 8` is the seeded set; `last_scene_ts` is the
newest seeded scene (Maya confirming the Friday deadline);
`spend_usd: 1.84` is the seeded baseline. If earlier tests already
ran against this database, expect higher numbers, and that is not a
failure (each chunk adds 0.07, each Ask adds 0.12 unless Argon
returns an explicit dollar cost). What would be wrong is
`scene_count: 0` or `spend_usd: 0.0` on a database you expected to
hold the seed: see Failure C.

From the phone, localhost does not work. Use the Mac LAN address
(see Failure E), for example `http://10.1.63.33:8000/api/v1` with
whatever IP is current.

### Step 6: Tell live Argon from mock fallback in the server log

Read the server window, not the phone. Two facts first: there is no
startup line that says live or mock (the two startup lines print in
both modes); and fallback lines appear lazily, only when a chunk is
analyzed or an Ask runs. Judge it on the first chunk and the first
Ask, not on startup.

Ignore this startup warning. It appears in both modes and is not
about Argon:

```
FaceVoiceAttributor: real fusion unavailable (insightface present: False, speechbrain present: False); returning Unknown/review-or-silence stub.
```

That only means face plus voice fusion is a stub, by design.

Mock fallback, key missing. On the first analyzed chunk:

```
ArgonSceneAnalyzer: no GEMINI_API_KEY/GOOGLE_API_KEY in environment; returning mock draft.
```

On the first Ask:

```
ArgonReasoning: no GEMINI_API_KEY/GOOGLE_API_KEY in environment; delegating to MockReasoning.
```

(The lines carry a `WARNING:app.services:` prefix in Terminal. The
wording after the prefix is the part to match.)

Mock fallback, other causes. Even with a key set, these mean the
answer you just got is mock, not Argon:

```
ArgonSceneAnalyzer: zero real frames (placeholders only); returning mock draft.
ArgonSceneAnalyzer: Argon call/parse failed (...); returning mock draft.
```

Mock answers look like this, and live answers do not: a new scene
summary of exactly `Live chunk indexed (mock scene)`; a transcript
line of exactly `Live segment (mock transcript).`; an Ask that only
ever answers promise questions with the canned Maya Q3 answer, and
everything else with `I don't have a record of that.` plus empty
receipts. Live Argon looks like this: no `no GEMINI_API_KEY` line on
the first chunk or Ask; real descriptions of what was in the frames;
real spoken words; Ask answers with verbatim quote receipts. One
caution: a live Argon Ask can also legitimately answer
`I don't have a record of that.` when the session genuinely does
not record an answer. No-record alone does not prove mock. The log
line plus the fixed mock sentences together are the proof.

Related but separate: if the transcript falls back while Argon stays
live, you will see a faster-whisper line instead, for example:

```
FasterWhisperTranscriber: faster-whisper/model unavailable (...); falling back to mock transcript.
```

That means the transcript is mock even if scene analysis is live.
Fix it by installing the transcription dependency and model, not by
re-exporting the key.

Dense-frame note: a successful dense extraction prints nothing.
Only failures print, and they mean the chunk fell back to the
6-frame path, not to mock Argon:

```
[ingest] dense extraction skipped: ffmpeg not found on PATH
[ingest] dense frame extraction failed (...), falling back to 6-frame path
```

If you see the ffmpeg line, install ffmpeg on the Mac
(`brew install ffmpeg`) and restart the server.

### Failure A: Port already in use

Symptom: the server exits immediately with a traceback ending in
`Address already in use`, or the server never starts but
`curl http://localhost:8000/api/v1/status` still answers, because an
old server is still holding the port. Cause: a previous server
process was never stopped. Fix, in any Terminal window:

```sh
lsof -ti:8000 | xargs kill
lsof -i:8000
```

The second command must print nothing. Then rerun step 4. If the
process is still listed, force it (`xargs kill -9`), confirm empty,
then rerun step 4. Do not "fix" this by switching to another port:
the phone and lens wiring all assume 8000.

### Failure B: Key missing, server runs in mock fallback

Symptom: the server starts cleanly and step 5 looks perfect, but the
first chunk produces the fixed mock scene summary, or the first Ask
produces the canned promise answer or a no-record answer, and the
server log shows the `no GEMINI_API_KEY/GOOGLE_API_KEY in
environment` lines from step 6. Cause: the key was never exported,
was exported in a different Terminal window, was mistyped, or was
exported after the server started. Fix: stop the server with Ctrl-C
in its window, then in that same window run step 3 and step 4 again,
in that order, then confirm with the key check from step 3 before
the next chunk or Ask. Run that check in the server window: if it
says NOT set there, the server in that window does not have the key
either, no matter what another window says.

### Failure C: Wrong database path, or scene.db confusion

Symptom: `scene_count` is back to 8 and `spend_usd` back to 1.84
even though you recorded live scenes earlier, or the counts are
higher than you expect, or the seeded scenes are missing entirely.
The server itself starts fine. Cause: the server builds its database
path from the location of `server.py` itself, not from your current
directory, and there are several `scene.db` files in play (the Mac
staged copy at `~/scene-backend/scene.db`, the repo clone copy under
`src/backend/scene.db`, any other copy you may have run). Each one
seeds itself to 8 scenes and 1.84 on first use and then diverges.
Two related traps: `SCENE_STORE=memory` gives a fresh in-memory
store on every start (seeded to 8 and 1.84, then all live data is
lost on restart); `SCENE_STORE=postgres` selects a different store
entirely and exits at startup without `DATABASE_URL`. Fix: stop the
server, then:

```sh
cd ~/scene-backend
ls -l scene.db
echo "SCENE_STORE=[$SCENE_STORE]"
```

`scene.db` must be listed, and `SCENE_STORE` must print empty
(empty means the SQLite default, which is what you want). If it
prints `memory` or `postgres`, clear it in that window
(`unset SCENE_STORE`), then rerun step 4 from `~/scene-backend`,
never from a repo clone directory, and recheck step 5. Never delete
`scene.db` to "fix" a count problem: deleting it wipes every live
scene and resets you to the 8 scene, 1.84 seed. Do not delete
`scene.db-wal` or `scene.db-shm` while the server is running
either: they are part of the live database, not temp files.

### Failure D: Server bound to the wrong host or port

Symptom: `curl http://localhost:8000/api/v1/status` fails with
connection refused even though a server window looks alive, or it
answers but with stale data from an old server, or the phone cannot
reach the backend at all while localhost works. Cause: almost always
a stray `PORT` value. The server binds `0.0.0.0` on whatever `PORT`
says (default 8000), so it is reachable on localhost and on the LAN
at the same port. Fix: check what the server actually printed at
startup. If its two lines say a port other than 8000, stop it and
restart pinned to 8000 (`PORT=8000 python3 server.py`), then verify
with the step 5 curl. If the startup lines already said 8000 and
localhost still refuses, the server window you are looking at is not
the process you think it is: go back to Failure A.

### Failure E: LAN IP changed

Symptom: everything works from the Mac itself, but the phone or lens
cannot reach the backend at the last known LAN address (for example
`http://10.1.63.33:8000`), and requests time out or fail to
connect. Cause: the Mac LAN address is assigned by DHCP and can
change. Fix: on the Mac, in any Terminal window:

```sh
ipconfig getifaddr en0
```

Use exactly what it prints. First prove the new address works from
the Mac itself:

```sh
curl -s http://<NEW_IP>:8000/api/v1/status
```

If that answers with the step 5 shape, the server is reachable on
the LAN, and the phone and lens base URLs must be updated to that
same address and port. If the new address still fails from the Mac
while localhost works, do not keep guessing addresses: recheck that
the phone and the Mac are on the same Wi-Fi network and that you
typed the new address exactly, then re-run the curl above.

---
## Part 2. Phone app wiring (SceneApp, demo phone)

Prerequisite: the Mac backend is already running and reachable on
the venue network (Part 1). The phone work below is pointless until
that is true. Nothing here changes the repo: all Developer settings
are saved on the demo phone only, so if the demo phone changes, redo
this whole part on the new phone.

### Exact taps: point the app at the real backend

Do these on the demo phone, in this order:

1. Open SceneApp.
2. Tap the Session tab.
3. Scroll down to the DEVELOPER section (below the record button,
   the ARGON SPEND TODAY row, and "Wipe the day").
4. Find the "Use mock data" toggle. It defaults ON. Turn it OFF.
   While it is ON, the base URL field and the token field are
   hidden. If you cannot see a URL field, mock is still on. That is
   your tell, not a bug. Turning mock off clears the on-screen
   scenes, pins, and follow-ups immediately. An empty screen right
   after this tap is expected, not a failure. The real scenes load
   on the next step.
5. A base URL field appears (placeholder `http://localhost:8000`).
   Type the bare Mac LAN URL, with no path on the end:
   `http://<Mac LAN IP>:8000`. Bare means no `/api/v1` on the end.
   The app appends `/api/v1` itself to every call. One trailing
   `/api/v1` is tolerated by the app's normalizer, but bare is the
   canonical form, so type bare. Do NOT leave
   `http://localhost:8000` here. That only works for a simulator
   running on the Mac itself. On a physical phone, `localhost`
   means the phone, not the Mac, and it will never reach the
   backend.
6. Token field: leave it EMPTY unless auth is on. Auth is OFF by
   default on Nayan's Mac server, so the normal demo case is: token
   field empty, no token needed. Only if the backend has
   `AUTH_ENABLED=1`, tap the "Token (if the server needs one)"
   field and type the exact token and nothing else. Do NOT type
   `Bearer ` in front of it. The app adds `Bearer ` itself, so
   typing it yourself sends a doubled prefix and the server rejects
   it (see Branch 4).
7. Tap Reload in the DEVELOPER section.

Notes on what just happened, so a later surprise makes sense: the
live socket (WS `/live`) has no auto-reconnect by design. If live
updates stop, the app does not spin or retry on its own. Recovery is
manual and boring on purpose: pull to refresh on the Memory tab, or
tap Reload in Session > DEVELOPER. The Memory tab also re-fetches
every 15 seconds in real mode, so staying on Memory covers a dropped
socket too. Re-entering the Live or Memory tab re-opens the socket.
The `?token=` on the live socket URL is ignored server-side. The
token field gates REST calls only. Do not debug a live-stream drop
as an auth problem, and do not expect the token field to fix the
socket. If REST works (Reload succeeds), auth is fine even if the
socket later drops.

### Real scenes vs mock data: how to tell

Mock data is a fixed, canned day that ships in the app. If you see
any of the items below, you are still looking at mock data, no
matter what the URL field says. Mock data, exactly: exactly 8
scenes, always the same ("Walking to the office", midday, no quote;
"Lunch at the Ferry Building", Jordan: "Let's do this again next
week."; "Standup with Jordan and Priya", Priya: "I'll take the
onboarding bug."; "Maya explaining the Q3 numbers at the
whiteboard", Maya: "I'll send the Q3 numbers by Friday.";
"Whiteboard session", no quote; "Pricing discussion", Jordan: "What
if we drop the price to 49?"; "Someone suggests keeping the price",
unknown speaker: "Let's keep it at forty-nine."; "Coffee with
Priya", Priya: "Send me the deck when it's ready."). People tab:
exactly Maya (14 quotes, 6 scenes), Jordan (8 quotes, 4 scenes),
Priya (5 quotes, 3 scenes), all shown verified. Ask answers are
canned (Maya always gets the Q3 numbers answer, pricing always gets
the 49 answer). Follow-ups are the same three canned drafts (Maya Q3
numbers, Priya deck, price at 49 needs review).

The spend row is the fastest mock tell. Mock mode: the ARGON SPEND
TODAY row on the Session tab shows `$--` (a dash, no number). In
mock mode the app never asks the server for spend, so the row can
never show a real dollar amount. Real mode: after Reload, the same
row shows a dollar amount like `$0.12` (whatever the server's
`/status` reports as `spend_usd`). If the server reports no spend,
the row still shows `$--`, so use the row together with the scene
list, not alone.

Real server data, by contrast: the scene list comes from the
server's `/scenes/today`, so it is whatever actually happened
today (it can be empty, it can be one scene, it will not be the 8
canned scenes above); people counts come from the server, not the
Maya/Jordan/Priya 14/8/5 set; the DEVELOPER section shows
`CONNECTED · N SCENES` (with the real count) when there is no error
in real mode. Note: `N` can be 0 on a real, empty day.
`CONNECTED · 0 SCENES` plus an empty Memory tab ("No blocks yet.")
is a successful real connection, not mock and not a failure. Ask
answers come from the server and carry real receipts, not the canned
answers.

### Confirm it worked

After the Reload tap, check all of these before calling the phone
wired: (1) DEVELOPER shows `CONNECTED · N SCENES` and no red error
line under Reload. (2) The scene list is NOT the 8 canned mock
scenes above (empty with `CONNECTED · 0 SCENES` still passes: a real
server with no scenes yet today). (3) ARGON SPEND TODAY shows a
dollar amount, not `$--`, unless the backend reports no spend. If it
still shows `$--` while scenes loaded fine, re-check: mock may still
be on, or the server genuinely has no spend figure. Do not force it.
(4) Switch to the Memory tab, pull to refresh, and confirm the same
scenes appear there. This proves the pull-to-refresh recovery path
works, which is the path you will use if the live socket drops
mid-demo. If any check fails, go to the matching branch below. Do
not start a recording session as a connectivity test: in real mode
that creates a real server session, which is demo state, not a test.

### Branch 1: Mock left on

Symptom: the 8 canned scenes appear instantly, the spend row shows
`$--`, there is no red error, and the DEVELOPER section shows no
base URL or token field at all. Cause: "Use mock data" is still ON.
It defaults ON, and while it is on the app never touches the network
at all, so no URL or token value can fix it and no error will ever
appear. Fix: Session tab, scroll to DEVELOPER, turn "Use mock data"
OFF, then tap Reload. Expect the screen to go empty the moment you
flip the toggle (the app clears the mock scenes on switch); Reload
fills it with real scenes. If the URL/token fields still do not
appear after flipping the toggle, you are not in the DEVELOPER
section of the Session tab, or the toggle did not actually flip;
flip it again and watch for the fields to appear.

### Branch 2: Double `/api/v1` in the URL

Symptom: after Reload, a red error in DEVELOPER along the lines of
"Couldn't reach the backend: HTTP 404" (the exact suffix is the
server's error text; the 404 is the signal). Cause: the base URL
contains `/api/v1` twice, for example
`http://<Mac LAN IP>:8000/api/v1/api/v1`. The app's normalizer
strips exactly one trailing `/api/v1`, so one survives, and then the
app appends `/api/v1/scenes/today` again, producing
`.../api/v1/api/v1/scenes/today`, which the server does not have.
Note: a single trailing `/api/v1` is NOT this bug. The normalizer
strips one, so `http://<Mac LAN IP>:8000/api/v1` works. Only the
double is broken. Fix: delete the whole base URL field, retype the
bare URL `http://<Mac LAN IP>:8000` with no path, tap Reload.
Confirm the error clears and `CONNECTED · N SCENES` appears.

### Branch 3: LAN unreachable

Symptom: after Reload, a red error starting "Couldn't reach the
backend:" followed by a connection error (refused, timed out, host
unreachable, or similar; the suffix varies by phone and network, the
prefix is the signal). No scenes load, and the spend row stays `$--`.
Cause: the phone cannot open a connection to the Mac at all. Usual
causes, in order to check: the base URL is still `localhost` (which
on a phone means the phone itself); the Mac backend is not running;
the IP or port is wrong; the phone and the Mac are on different
networks; venue Wi-Fi or a firewall is blocking the connection.
Fix: (1) Confirm the Mac backend is running (Part 1) and note its
exact LAN IP. (2) On the phone, confirm it is on the same venue
Wi-Fi as the Mac (same network name the Mac is on). (3) In Session
> DEVELOPER, delete the base URL, retype
`http://<Mac LAN IP>:8000` exactly, tap Reload. (4) If it still
fails, the problem is network or backend, not the phone taps: do not
keep retyping the URL. Hand it to Part 1 (is the server listening
on the LAN, not only on localhost? Is the venue network isolating
clients from each other?).

### Branch 4: 401 with auth on

Symptom: after Reload, a red error along the lines of "Couldn't
reach the backend: unauthorized". Starting or stopping a recording
can show the same word: "Couldn't start session: unauthorized".
Cause: the server has `AUTH_ENABLED=1` and the request did not carry
the exact token it expects. Three phone-side ways this happens: the
token field is empty, the token is mistyped, or the token field
contains `Bearer <token>` (the app already adds `Bearer `, so the
server receives a doubled prefix and the token no longer matches).
Two non-phone causes: you are pointed at a different, auth-on server
while assuming auth is off; or the server is fail-closed, meaning
`AUTH_ENABLED=1` but no token was configured on the server at all,
in which case it refuses every request and no phone value can pass.
Fix: (1) Confirm from Part 1 whether this server really has auth
on, and what the exact token is. If auth is off on your Mac server
and you still get 401, you are pointed at the wrong server: fix the
base URL (Branch 3), not the token. (2) If auth is on: clear the
token field completely, retype the exact token with no `Bearer `
prefix, no leading or trailing spaces, tap Reload. (3) If it still
401s after a careful retype, stop retyping. Either the token you
were given is wrong, or the server is fail-closed with no token
configured. That is a backend fix (set the token or turn auth off),
not a phone fix. (4) Do not chase the live socket for this. The
socket `?token=` is ignored server-side; the token field above is
the only auth the phone controls, and it gates REST calls.

### Branch 5: Phone on cellular while the Mac is on Wi-Fi

Symptom: identical to Branch 3 ("Couldn't reach the backend: ...")
even though the URL looks right, and it may have worked earlier on
Wi-Fi. The LAN IP is the giveaway: a `10.x`, `172.16-31.x`, or
`192.168.x` address is only reachable from inside that local
network. Cause: the phone is routing over cellular instead of the
venue Wi-Fi, so the Mac's LAN address is unreachable from the
phone's network. This also happens when the phone shows a Wi-Fi icon
but is actually on a different network (for example a phone hotspot
or a neighbouring venue network) than the Mac. Fix: (1) On the
phone, open Wi-Fi settings and join the exact same venue network
name the Mac backend is on. Confirm the name matches; "a Wi-Fi
network" is not enough, it must be the same one. (2) In SceneApp,
Session > DEVELOPER, tap Reload. Do not change the URL: if the URL
was right on Wi-Fi before, it is still right. (3) If it still
fails, temporarily turn cellular data off on the phone (so there is
no cellular fallback route), confirm Wi-Fi is still connected to
the venue network, tap Reload again. Turn cellular back on after
the demo if you want it, but for the demo the phone stays on venue
Wi-Fi.

### Branch 6: Base URL whitespace or trailing slash

Symptom: you typed the URL with a trailing slash
(`http://<Mac LAN IP>:8000/`) or with spaces around it, and you are
worried that is why it fails, or it did fail and you suspect the
slash/spaces. Cause, verified in code: this alone should NOT break
it. The app's URL normalizer trims leading and trailing
whitespace/newlines and strips trailing slashes (repeatedly) before
any call, so `http://<Mac LAN IP>:8000/`,
`http://<Mac LAN IP>:8000`, and the same with surrounding spaces
all resolve to the same origin. If the app still fails after you
entered a slashed/spaced URL, the cause is something else: go to
Branch 3 (unreachable) or Branch 4 (401), whichever error text you
actually see. Fix (do it anyway, so the field is clean and
unambiguous): delete the whole base URL field, retype the bare URL
with no spaces and no trailing slash, tap Reload. One exception the
normalizer does NOT fix: a space inside the URL (for example a space
before `:8000` or inside the IP). That is not leading/trailing
whitespace, it survives normalization, and it breaks the URL. The
full delete-and-retype above removes it; do not try to edit one
character in place, retype the whole field.

---
## Part 3. Seeded end-to-end test (one pass, in order)

Do the steps in this order: later expectations depend on earlier
steps (Ask adds spend, approving changes the pending count). You
perform every step; nothing here runs itself.

Preconditions: backend running on your Mac from `~/scene-backend`
(`python3 server.py`, SQLite default, port 8000); base URL for every
curl below is `http://localhost:8000/api/v1`; auth is OFF by default
(if you turned it on, add `-H "Authorization: Bearer <token>"` to
every curl). This test assumes a FRESH seed: the first run against
the seeded database. SQLite seeds only once, on an empty store, and
restarts never duplicate or reset the seed. If you already ran Ask
or Follow-Through earlier, spend and follow-up counts will be higher
than the numbers below; the shapes and statuses still have to match.
IDs are random UUIDs per seed. Never match by ID. Match follow-ups
and scenes by their promise, person, quote, and summary text. For a
clean rerun only: stop the server, move
`~/scene-backend/scene.db` aside, restart. The server reseeds the
empty store on startup.

### Step 0: Baseline (do this first, it anchors everything)

```sh
curl -s http://localhost:8000/api/v1/status
```

Expected:

```json
{ "recording": false, "scene_count": 8,
  "last_scene_ts": "2026-10-25T12:10:00-07:00", "spend_usd": 1.84 }
```

(`session_id` is present too; its value is a random UUID, ignore
it.) `recording: false` is correct: the seed has no live session.
If this does NOT appear: `scene_count: 0`, `spend_usd: 0.0` means
wrong backend or empty database (server pointed at a fresh store
that did not seed, or a different port); connection refused means
the server is not running; `spend_usd` above 1.84 means the seed is
not fresh (someone already ran Ask calls, each adds 0.12, so note
the starting number and check deltas instead of absolute values);
`recording: true` means a live session was started after seeding
(the seeded scenes are still there, so continue, but the demo is no
longer in its pristine seeded state).

### Step 1: Memory shows the seeded scenes

App: open the phone app, Memory tab. You should see 8 scenes,
newest first. Curl (authoritative check):

```sh
curl -s "http://localhost:8000/api/v1/scenes/today?limit=50"
```

Expected: `"scenes"` has 8 entries, newest first, exactly these
summaries in this order: 12:10 Maya confirms the Friday deadline
(Maya, verified); 11:48 Unknown speaker asks about the demo flow
(Unknown, review); 11:20 Maya whiteboards the Scene pipeline (Maya,
verified); 11:02 Maya reviews the pitch rubric (Maya, verified);
10:31 Hallway, no conversation (none, silence); 10:05 Maya sketches
the Ask flow on a napkin (Maya, verified); 09:42 Unknown speaker
asks about the demo flow (Unknown, review); 09:15 Maya explaining
Q3 numbers at the whiteboard (Maya, verified, pinned). Spot-check
the pinned one: the 09:15 scene is the only pinned scene. Its detail
must show quote `I'll send the Q3 numbers by Friday`, visible text
`Q3 revenue $4.2M`, and objects `whiteboard, laptop, coffee cup`.
The 09:42 scene is the one scene whose critique has a fail
(`visual_grounding`, note `Face partially occluded in keyframe`);
every other scene passes all four critique checks.

If this does NOT appear: fewer than 8 scenes, or different
summaries, means you are looking at a different backend or a store
that already ingested live chunks. The phone app showing other
scenes (for example Priya/Jordan scenes) means the app is still on
its canned mock data, not the server: check the app's base URL. 8
scenes but oldest first is a display bug in the client, not the
server: the API returns newest first, and the curl output is the
truth. An empty list means an empty or wrong backend (see Step 0);
`/scenes/today` is not session-scoped, so a wrong session is not
the cause.

### Step 2: Ask a promise question

App: Ask tab, type the query below exactly, send. Curl:

```sh
curl -s -X POST http://localhost:8000/api/v1/ask \
  -H "Content-Type: application/json" \
  -d '{"query": "What did Maya promise me?"}'
```

The query must contain the word "promise". That word is what routes
this to the Maya answer. Expected: answer
`Maya promised to send the Q3 numbers by Friday.`, one receipt
(scene_id of the 09:15 scene, timestamp
`2026-10-25T09:15:00-07:00`, quote verbatim
`I'll send the Q3 numbers by Friday`, thumb URL on the CDN), and
`sources` starting with a `fact:` entry (the fact `Maya promised Q3
numbers by Friday`) followed by the `scene:` entry for the 09:15
scene. Side effect: this Ask adds $0.12 to spend. After this step,
`GET /status` should read `spend_usd: 1.96` on a fresh seed
(1.84 + 0.12). If a live Argon key is configured and Argon returns
an explicit dollar cost, the increment may differ from 0.12; the
answer and receipt must still match.

If this does NOT appear: `I don't have a record of that.` with
empty receipts means the query did not contain "promise" (check
spelling), or the 09:15 scene is missing from the session, or the
receipt's quote failed the transcript check and was dropped: re-run
Step 1 and confirm the 09:15 scene and its transcript line exist.
An answer with no receipts, or a quote that is not verbatim from a
transcript line, violates the cite-or-say-no-record rule: that is a
backend bug, not a data problem; do not demo past it. A
plausible-sounding answer about something else entirely cannot come
from the server path with no Argon key configured (the fallback is
the canned mock answer): suspect the app's mock data instead of the
server.

### Step 3: Ask a no-record question

App: Ask tab, type the query below exactly, send. Curl:

```sh
curl -s -X POST http://localhost:8000/api/v1/ask \
  -H "Content-Type: application/json" \
  -d '{"query": "What did Maya say about the weather?"}'
```

Do NOT use the word "promise" anywhere in this query. Any query
containing "promise" returns the Step 2 answer by design. Expected:
exactly `I don't have a record of that.`, with empty receipts and
empty sources. Side effect: this Ask adds another $0.12. After this
step, `GET /status` should read `spend_usd: 2.08` on a fresh seed
(1.96 + 0.12). Remember this number: it is the spend Step 7
expects.

If this does NOT appear: the Step 2 Maya answer coming back means
your query contained "promise" (or a substring of it): reword and
retry. A made-up weather answer with receipts is the same backend
bug class as Step 2: an answer must never appear without a verbatim
transcript receipt behind it. A generic app error means the app lost
the server connection: the curl result decides (if curl returns the
no-record answer, the server is fine and the app connection is the
problem).

### Step 4: Follow-ups generate: 2 pending, 1 needs_review

App: Memory tab, tap the Follow-through entry, then
`Find follow-ups`. Wait for the list to fill. Curl (run generate
EXACTLY ONCE in this sequence):

```sh
curl -s -X POST http://localhost:8000/api/v1/followups/generate \
  -H "Content-Type: application/json" -d '{}'
```

Expected: `202` with a `run_id`, `status: "running"`, and `steps:
["find_promises", "verify_quotes", "draft_followups"]`.
(`status: "running"` in the response is normal even though the run
completes synchronously; the stored run is then `done`.) Then list
that run:

```sh
curl -s "http://localhost:8000/api/v1/followups?run_id=<run_id>"
```

Expected: exactly 3 follow-ups. (1) Maya promised Q3 numbers by
Friday, Maya, quote verified true, pending, draft
`Hi Maya, following up on the Q3 numbers you mentioned today. Could
you send them over when you get a chance?` (2) Maya decided the
demo leads with glasses, not the dashboard, Maya, quote verified
true, pending, draft `Hi Maya, confirming we agreed the demo leads
with the glasses and the dashboard stays backup only.` (3) Unknown
speaker promised to share the demo link, Unknown, quote verified
false, needs_review, empty draft. Why the third one fails
verification: its quote, `I'll drop the link somewhere`, appears in
no transcript line, so the fuzzy quote check fails and the draft is
withheld. That is the system working, not a bug.

If this does NOT appear: 0 follow-ups means the run polled the
wrong `run_id`, or generation ran against an empty/wrong session:
re-check the `run_id` from the 202 response and re-list. 6
follow-ups (4 pending, 2 needs_review) means generate was run twice
(each run appends 3 more): restart from the clean-rerun note in
Preconditions if you need exact counts, or filter by `run_id` and
test against the latest run only. The Unknown draft showing as
pending with a draft means the approval gate is broken: an
unverified quote must never become a pending draft. All 3
needs_review means the seeded scenes/facts are not loading
(verification needs the real transcripts): go back to Step 1.

### Step 5: Approve one pending follow-up

Pick the first pending follow-up (the Q3 numbers one for Maya).
Note its `id` from the Step 4 list. App: tap that follow-up in the
Follow-through list, then Approve. Curl:

```sh
curl -s -X POST http://localhost:8000/api/v1/followups/<id>/approve
```

Expected: `200` with exactly `{ "id": "<same id>", "status":
"approved" }`. Confirm the flip stuck:

```sh
curl -s "http://localhost:8000/api/v1/followups?run_id=<run_id>"
```

The Q3 follow-up now reads `status: "approved"`. The other two are
unchanged: 1 pending, 1 needs_review. Nothing is sent anywhere on
approve; delivery is a stretch goal and the demo floor is the
approved state itself.

If this does NOT appear: `400 not_approvable` means you approved
the wrong row (the needs_review one) or a pending row whose quote
is unverified: re-list and pick a row with `status: "pending"` and
`quote_verified: true`. `404 followup_not_found` means the id is
wrong or from another run: copy it fresh from the Step 4 list
output. `200` but a re-list still shows `pending` means the approve
did not persist: that is a store bug; do not proceed to Step 7
counts until it is fixed, because Step 7 assumes this flip.

### Step 6: Attempt to approve the needs_review one (must fail)

This step is curl-only. The phone app deliberately offers no Approve
button for needs_review rows (they render under a `NEEDS REVIEW`
heading with the note `COULDN'T MATCH THIS QUOTE TO THE FOOTAGE -
NOT OFFERED FOR APPROVAL`). In the app, just confirm that row is
present under that heading and has no approve control. Take the
Unknown follow-up's `id` from the Step 4 list and run:

```sh
curl -s -X POST http://localhost:8000/api/v1/followups/<id>/approve
```

Expected: `400` with `{ "error": { "code": "not_approvable",
"message": "Unverified drafts are never approved; they stay under
needs_review." } }`. Confirm nothing changed with the Step 4
re-list: the Unknown follow-up still reads `status:
"needs_review"`, the Q3 one still `approved`, the demo-leads one
still `pending`.

If this does NOT appear: `200 approved` means the approval gate is
broken. This is a stop condition: an unverified draft must never be
approvable. Do not demo Step 7 as a pass. `404` means a wrong id;
re-copy it from the list. The app showing an Approve button on the
needs_review row means the app is not enforcing the gate in its UI:
the curl 400 is still the authoritative result, but flag the UI gap
before demoing.

### Step 7: Lens Day screen

Lens: tap the `Day` button (from the timeline or a scene detail)
and let the Day screen load from the server, not from cached data.
If the lens shows an offline note instead of numbers, it never
reached the server; fix connectivity before judging the values.
Expected, after Steps 1-6 in order on a fresh seed: Spend `$2.08`
(1.84 baseline + 0.12 Step 2 Ask + 0.12 Step 3 Ask), source
`GET /status` `spend_usd`. People (2): Maya (5 scenes, 6 quotes,
verified) and Unknown (2 scenes, 0 quotes, unverified), source
`GET /people`. Watch out: the lens's own canned mock Day data lists
Maya with 3 quotes, not 6. If you see 3 quotes, you are looking at
the lens mock, not the server. Facts (3): `Maya promised Q3 numbers
by Friday`; `Maya decided the demo leads with glasses, not the
dashboard`; `Live demo is 50 percent of the judging score`, source
`GET /facts?limit=20`. Pending follow-ups (1): only the demo-leads
Maya follow-up. The Q3 one is approved (Step 5) and the Unknown one
is needs_review (Step 6), and the Day screen queries
`GET /followups?status=pending`, so neither appears here.

Curl equivalents for all four areas:

```sh
curl -s http://localhost:8000/api/v1/status
curl -s http://localhost:8000/api/v1/people
curl -s "http://localhost:8000/api/v1/facts?limit=20"
curl -s "http://localhost:8000/api/v1/followups?status=pending"
```

If this does NOT appear: spend still `$1.84` means the Day screen
is showing cached or mock data, or the Ask calls in Steps 2-3 hit a
different backend than the one the lens reads: compare `GET /status`
curl output directly (if curl says 2.08 and the lens says 1.84, the
lens is not on live data). Spend higher than `$2.08` means extra
Ask calls happened somewhere (retries count too, 0.12 each): check
the delta from the Step 0 baseline rather than the absolute number.
Pending follow-ups = 2 means Step 5's approve did not stick, or the
lens is showing pre-approve cached data: re-run the Step 5
confirmation list. Pending follow-ups = 0 means the approve in Step
5 hit the wrong row, or a second generate run confused the listing:
re-list by `run_id` and recount. People or facts lists showing
Priya/Jordan entries means that is the lens canned mock Day data,
not the server: the server seed has only Maya and Unknown and only
the 3 facts above. Any one area showing an offline note while the
others load means that area's fetch failed independently (the Day
screen loads each area separately): re-check that one endpoint with
curl; do not treat the whole screen as failed.

### Pass criteria (all must hold)

1. 8 seeded scenes, newest first, 09:15 scene pinned.
2. Promise Ask returns the Maya answer with the verbatim 09:15
   quote.
3. No-record Ask returns exactly `I don't have a record of that.`
   with empty receipts and sources.
4. One generate run yields 2 pending + 1 needs_review.
5. Approving a pending follow-up returns 200 and the status flips.
6. Approving the needs_review follow-up returns 400 and nothing
   changes.
7. Day screen shows $2.08 spend, 2 people, 3 facts, 1 pending
   follow-up (on a fresh seed, in this order).

---
## Part 4. Lens wiring (demo phone browser)

Who does this: you, on the demo phone. Prerequisites, assumed done
before you start here: the backend is running on the Mac; the demo
phone is on the same venue Wi-Fi as the Mac (the lens talks to the
Mac over that Wi-Fi, not over the internet); the demo phone is most
likely Isabella's phone, fallback your phone, and you open the lens
on the one phone you will demo from.

What the lens is: a web app, two files in the repo at
`src/frontend/lens/` (`index.html`, `lens.js`). It is not an app
you install. You open its page in the demo phone's browser.

One thing this part does NOT prescribe: how the lens page itself is
served to the demo phone. The backend does not serve the lens files
(no static route for them was found in the backend routes). So take
whatever lens page URL you already use to open
`src/frontend/lens/index.html` on the demo phone, and append the
`?api=` part below to it. Everything below is about that `?api=`
value and what the lens does with it. If no served lens URL exists
yet, that is a gap to close before this part can run, not something
to invent here.

### 1. Build the lens URL

Form:

```
<lens-page-url>?api=<backend-base-url>&token=<token>
```

Concrete example (LAN IP is last known only, re-verify it first):

```
<lens-page-url>?api=http://10.1.63.33:8000
```

Re-verify the Mac's LAN IP before you build the URL. On the Mac:

```
ipconfig getifaddr en0
```

Use whatever that prints, in place of `10.1.63.33`. That address
can change between networks, so never trust the last known value
blindly.

Rules for the `api` value, verified from `lens.js`: bare service
URL only. Use `http://10.1.63.33:8000`, NOT
`http://10.1.63.33:8000/api/v1`. The lens appends `/api/v1/...`
itself to every request, and appends `/api/v1/live` for the socket.
Passing the full URL doubles the prefix and every call 404s (see
Branch B). Include the scheme. `http://` is required, not optional.
Without it the fetch becomes a relative path and the socket
constructor fails silently (see Branch B). No trailing slash. The
parser strips exactly one trailing slash, so one trailing slash
happens to survive, but two leave a stray slash behind. Simplest
rule: no trailing slash at all. On the Mac itself only,
`http://localhost:8000` works. From the demo phone it does not:
`localhost` on the phone means the phone, not the Mac. From the
phone, always use the Mac's LAN IP. `&token=` is optional when
backend auth is off (the default). If you have a token, append it
as `&token=<token>`. Never paste a real token into any doc, chat
log, or screenshot you share; the URL bar will show it while the
page is open, so keep the phone screen out of demo recordings when
the URL is visible.

How the parser works, exactly: it reads the URL query, and if `api`
is present it flips the lens out of mock mode and sets the base URL
(stripping one trailing slash); if `token` is present it stores it.
If you open the lens with no `?api=` at all, it stays in mock mode
and shows canned demo data. That data looks real but is not live
(see Branch D).

What `token` does and does not do (verified both sides): it DOES
authenticate REST calls (every REST fetch adds
`Authorization: Bearer <token>` when a token is set). It does NOT
authenticate the socket. The lens still appends it to the socket URL
as `?token=...`, but the server deliberately ignores it: the routes
say "WS ?token= is deliberately NOT checked here", and the socket
handler never reads the query string. Backend auth is off by
default, so for the normal demo setup the token changes nothing for
the socket either way (see Branch C).

Steps: (1) On the Mac, confirm the backend is up and get the current
LAN IP with `ipconfig getifaddr en0`. (2) On the demo phone, on the
same Wi-Fi, open the lens page with
`?api=http://<current-LAN-IP>:8000` appended (plus
`&token=<token>` only if you were given one). (3) The lens should
land on the Now screen. If it shows the timeline instead, that means
recording is off (the Now screen falls back to Timeline when not
recording). That is a recording-state issue, not a lens URL issue;
start a session from the phone app first, then reload the lens.

### 2. Live WebSocket check

What the socket is: after page load the lens opens a WebSocket to
`<baseUrl with http swapped for ws>/api/v1/live`. So
`http://10.1.63.33:8000` becomes
`ws://10.1.63.33:8000/api/v1/live`, and `https://...` would become
`wss://...` by the same rule.

What does NOT prove the socket is live: the pulsing LIVE dot on the
Now screen (it is a CSS animation that runs regardless of socket
state; it breathes even when the socket is dead); the clock ticking
(it refreshes every 15 seconds on the Now screen with no network
involved); old scenes sitting on the timeline (those may be cached,
see Branch D).

What DOES prove the socket is live: a new scene arriving while the
lens is open. The server pushes `{"event": "scene", "scene":
{...}}` messages, and the lens prepends each new scene to the top
of its list, newest first, with no duplicates. If you are on the Now
screen, the Now title updates to the new scene. If you are on the
Timeline, the new card appears at the top and the scene count goes
up.

Check: (1) With the lens open on the demo phone, trigger one new
scene through the normal recording path (a fresh moment captured
while recording is on). (2) Watch the lens. Within a few seconds of
the scene being created, the new scene must appear at the top of the
timeline, and the Now screen title must change to it. (3) If nothing
appears after about 10 seconds, the socket is stale or dead even if
everything else looks fine. Go to Branch A. Do not trust the LIVE
dot.

Note on reconnect: the lens does reconnect on its own. On socket
close it retries after 3 seconds. There is no error handler and no
visible "reconnecting" indicator, so a drop is silent. A brief drop
fixes itself; a persistent stale timeline does not, and needs
Branch A. (This differs from the phone app, which has no
auto-reconnect by design.)

### 3. Day screen check

Open it from the Now screen (Day button) or the Timeline (Day
button). Opening Day triggers a fresh fetch before the screen shows.
Each of the four areas is fetched independently, and each is labelled
live, cached, or offline on its own. One area failing never kills
the others, so check all four, not just the first one you see.

Healthy backend, what each area shows: Spend (top right of the Day
screen header): a dollar number, `SPEND $X.XX`, from
`GET /api/v1/status` (`spend_usd`). Any real number counts as
healthy here; do not expect a specific value. People: up to 5 rows,
each `NAME · N SCENES`, from `GET /api/v1/people`. If more than 5
people exist, a `+N MORE` row follows. Empty but healthy shows
`NO PEOPLE TODAY` (no CACHED or OFFLINE suffix). Facts: up to 4 rows
of fact text, from `GET /api/v1/facts?limit=20`. If more than 4
exist, a `+N MORE` row follows. Empty but healthy shows
`NO FACTS TODAY`. Follow-ups: up to 4 rows, each
`PERSON · <promise text>`, from
`GET /api/v1/followups?status=pending`, filtered to pending only.
If more than 4 exist, a `+N MORE` row follows. Empty but healthy
shows `NONE PENDING`. `NONE PENDING` is a healthy empty state, not
an error.

Pass criteria for this step: all four areas load, and NONE of them
carries a `· CACHED` or `· OFFLINE` suffix, and no area shows
`OFFLINE · NOT LOADED`. If any area is cached or offline, the
backend fetch for that area failed, even if rows are visible. Go to
Branch D.

### 4. Confirm it worked

All of these must be true before you call the lens done: (1) The
lens URL has `?api=http://<current-LAN-IP>:8000` with the IP you
just verified, bare URL, scheme included, no trailing slash, no
`/api/v1` in the `api` value. (2) A new scene created while the
lens is open appears at the top of the timeline within seconds, and
the Now title updates to it. (3) The Day screen shows a dollar
spend figure and people, facts, and follow-ups (or their healthy
empty texts) with no `· CACHED`, `· OFFLINE`, or
`OFFLINE · NOT LOADED` labels anywhere. (4) No
`OFFLINE · SHOWING CACHED` banner is visible on the Timeline. If
any item fails, use the matching branch below, fix it, reload the
lens page, and re-run this checklist from step 2. Reloading is safe:
a successful reload re-fetches scenes and overwrites the cache, and
re-opens the socket.

### Branch A. WebSocket drop: timeline stops updating, everything else looks alive

Symptom: new scenes stop appearing on the lens, but the Now screen
still shows the LIVE dot, the clock still ticks, and old scenes are
still visible. No error or banner appears for a socket drop. Cause:
the socket closed and either has not reconnected yet, or cannot
reconnect (backend down, phone left the Wi-Fi, backend restarted
while the page was open). The lens retries silently every 3
seconds, but it shows no reconnecting state, so a dead socket looks
identical to a quiet day except that new scenes never arrive. Fix,
in order: (1) Wait 10 seconds and trigger another new scene. A
transient drop heals itself in one 3-second retry cycle. (2) If
still stale, check the phone is still on the same venue Wi-Fi as
the Mac, and that the backend is still running on the Mac. If
either changed, fix that first. (3) Reload the lens page on the demo
phone, keeping the exact same URL (same `?api=` value). Reload
re-runs the startup sequence: fetch scenes, then open the socket.
(4) Re-run the step 2 live check: trigger a new scene and watch it
prepend. If it still does not appear, the problem is not the socket
retry, it is the URL or the backend. Go to Branch B, then to Part 1.
Do not try to fix this by re-pasting the token. The token is
ignored on the socket (see Branch C), so it cannot revive a dead
socket.

### Branch B. Wrong `api` param shape: bare vs full URL, trailing slash, missing scheme

Symptom: Timeline shows the `OFFLINE · SHOWING CACHED` banner, or
shows nothing at all; Day areas show `· CACHED` or `· OFFLINE` /
`OFFLINE · NOT LOADED`. REST calls are failing, so the socket
(which is built from the same base URL) is failing too. Cause, one
of these: full URL passed (`?api=http://10.1.63.33:8000/api/v1`) so
the lens appends `/api/v1/...` again, producing
`/api/v1/api/v1/...`, which 404s; missing scheme
(`?api=10.1.63.33:8000`) so the fetch is treated as a relative path
and the socket URL is malformed (the socket constructor error is
swallowed silently, so there is no visible error for this one);
wrong host (`localhost` used from the phone, or a stale LAN IP from
a previous network); double trailing slash
(`?api=http://10.1.63.33:8000//`) since the parser strips only one,
leaving a stray slash that doubles up with the appended
`/api/v1/...`. Fix: (1) Rebuild the URL from scratch:
`?api=http://<current-LAN-IP>:8000`, where the IP is fresh from
`ipconfig getifaddr en0` on the Mac. (2) Check the rebuilt value:
starts with `http://`, contains no `/api/v1`, has no trailing
slash, is not `localhost` when opened from the phone. (3) Open the
rebuilt URL on the demo phone (do not just edit the old tab's
address bar from memory; type or paste the full rebuilt URL). (4)
The `OFFLINE · SHOWING CACHED` banner must disappear on reload if
the fetch now succeeds. If the banner persists, the backend itself
is unreachable from the phone: re-check same Wi-Fi and that the
backend is running, then go to Part 1.

### Branch C. Token param confusion: what the token does and does not do

Symptom: you keep changing, re-pasting, or removing `&token=`
trying to fix a dead socket or a stale timeline, and nothing
changes. Or, conversely, REST works but the socket is dead and you
assume the token must be wrong. Cause: the token has two different
fates in the same URL, and only one of them matters. REST: the lens
sends the token as an `Authorization: Bearer <token>` header on
every REST fetch, so the `?token=` value DOES control whether REST
calls pass when backend auth is on. A wrong or expired token there
produces a 401 with the server message "Token expired, re-pair."
Socket: the lens appends `?token=...` to the socket URL, but the
server never reads it, so changing the token cannot fix, break, or
authenticate the socket. Fix: (1) If REST works (Day screen loads
live, timeline fetches) but the socket is dead, stop touching the
token. Use Branch A instead. (2) If REST 401s (Day areas all
offline, timeline banner up, and the backend has auth on), the fix
is the token VALUE in `?token=`: replace it with the current
correct token and reload. Do not add a second token anywhere; the
lens already sends the same value as the REST header and the
(ignored) socket query. (3) If backend auth is off (the default),
the token is irrelevant to both paths. A missing `&token=` is not a
fault in that setup; do not chase it.

### Branch D. Lens showing cached or offline data (including mock data that looks live)

Symptom, two distinct cases. Tell them apart before fixing, because
the fixes differ.

Case 1, cached data (you DID pass `?api=`): Timeline shows the
`OFFLINE · SHOWING CACHED` banner. Day areas show `· CACHED` or
`· OFFLINE` suffixes, or `OFFLINE · NOT LOADED` rows, or
`SPEND · CACHED` / `SPEND · OFFLINE` instead of a dollar figure.
The rows you see are real past data, just not fresh. Cause: a fetch
failed, so the lens fell back to `localStorage`: scenes fall back to
the last fetched list, Day areas fall back to the last cached Day
object. The cache is per-area, so some areas can be live while
others are cached. Fix: do not present cached rows as live. Fix
connectivity (same Wi-Fi, backend running, correct `?api=` per
Branch B), then reload the lens page. On a successful fetch the
cache is overwritten and the banner clears. No manual cache
clearing is needed; a good fetch replaces the stale rows. Re-run
the section 4 checklist and require zero CACHED or OFFLINE labels.

Case 2, mock data (you did NOT pass `?api=`, or it was dropped): no
OFFLINE banner, everything looks healthy, but the content is fixed
canned data. Tells: timeline shows the same scenes every time (for
example "Coffee with Priya", "Pricing discussion", "Maya on the Q3
numbers"), and the Day screen shows spend `$1.84` with people Maya
and Unknown and the same three facts. No socket is opened at all in
this mode. Cause: `?api=` was missing, misspelled (the param name
is exactly `api`, not `baseUrl` or `server`), or lost when the page
was re-opened from history or a bookmark without the query string.
Fix: open the lens with the full URL including
`?api=http://<current-LAN-IP>:8000`. After reload, the canned
scenes must be replaced by real fetched scenes. If the canned scenes
persist after reload, the `?api=` param is still not reaching the
parser: check the address bar shows `?api=` in the URL you actually
opened, and that you did not open a bookmarked copy of the bare
page.

---
## Part 5. Real chunk test (no glasses needed)

You run every step below on your Mac. Nothing here runs on its own.
Prerequisites, all on the Mac: backend code at `~/scene-backend`,
started from that directory (`python3 server.py`, port 8000, SQLite
by default; `server.py` prints
`Scene backend REST on http://localhost:8000/api/v1`). Keep that
server terminal visible. The route line goes to stdout; the
ingest/service warnings below go to stderr, so both show up in a
foreground terminal. If you launched the server detached, you will
not see the warnings. Before you upload, record the baseline so the
check in step 4 is unambiguous (the store seeds demo scenes when
empty, so the count does not start at 0):

```sh
curl -s http://localhost:8000/api/v1/status
```

Note the `scene_count` number. Call it BEFORE. You will compare
against it after the upload.

### 1. Produce a valid 30-second clip, video plus audio, without glasses

The upload needs TWO parts (see step 2): a video file and a
separate audio file. One combined mp4 is not enough on its own; you
extract the wav from it. Work in a scratch directory, e.g.
`~/scene-test/`.

Option A: generated test clip (no recording needed). This makes a
30-second 720p test-pattern video with a 440 Hz tone, then pulls a
matching wav out of it:

```sh
mkdir -p ~/scene-test && cd ~/scene-test
ffmpeg -y -f lavfi -i testsrc2=size=1280x720:rate=30:duration=30 \
  -f lavfi -i sine=frequency=440:duration=30 \
  -c:v libx264 -pix_fmt yuv420p -c:a aac -shortest test.mp4
ffmpeg -y -i test.mp4 -vn -ac 1 -ar 16000 test.wav
ffprobe -v error -show_entries format=duration \
  -of default=noprint_wrappers=1:nokey=1 test.mp4
```

The last command should print `30` (or very close, e.g. `30.0`).
If it does not, do not upload yet; see "Chunk too long or too
short" below.

Option B: record on your phone, trim to 30 seconds. Record 35
seconds or more (talking to camera is best; a silent static shot
still works but teaches you nothing about the transcript). Transfer
the file to the Mac, then trim and split it:

```sh
mkdir -p ~/scene-test && cd ~/scene-test
ffmpeg -y -i phone.mov -t 30 -c:v libx264 -pix_fmt yuv420p -c:a aac test.mp4
ffmpeg -y -i test.mp4 -vn -ac 1 -ar 16000 test.wav
ffprobe -v error -show_entries format=duration \
  -of default=noprint_wrappers=1:nokey=1 test.mp4
```

Again, expect `30` from the probe. `-t 30` cuts video and audio
together, so the wav stays in sync. If your phone file is already an
mp4, the same commands work with `phone.mp4` in place of
`phone.mov`.

### 2. Upload the chunk (exact endpoint and field names)

Endpoint: `POST /api/v1/chunks`. Multipart field names are exactly
`video` and `audio` for the files, plus optional text fields
`session_id`, `start_ts`, `end_ts`. Both file parts are required;
missing either one is a 400. First create a session and capture its
id:

```sh
SESSION_ID=$(curl -s -X POST http://localhost:8000/api/v1/sessions \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
echo "$SESSION_ID"
```

Then upload (run from `~/scene-test`, where `test.mp4` and
`test.wav` live):

```sh
curl -s -w "\nHTTP %{http_code}\n" -X POST \
  http://localhost:8000/api/v1/chunks \
  -F "session_id=$SESSION_ID" \
  -F "video=@test.mp4" \
  -F "audio=@test.wav"
```

Expected reply, HTTP 202:

```json
{"chunk_id": "<id>", "session_id": "<id>",
 "start_ts": "<iso>", "end_ts": "<iso>", "status": "received"}
```

`session_id`, `start_ts`, and `end_ts` are optional in the request:
omit `session_id` and the server uses the live session, and omit
the timestamps and it stamps the upload time. The 202 means
"received and indexed", not "analyzed by real Argon"; the scene is
already stored by the time you get the reply, because ingest runs
synchronously inside the request.

### 3. Expected server log lines, in order

Pipeline order in code: frames first, then transcription, then
Argon analysis. So warnings appear in that order, and only when a
fallback actually triggers.

The one line you always see:

```
POST /api/v1/chunks
```

Printed by the route handler for every chunk request. If you do not
see even this, the request never reached this server; see "Upload
to the wrong backend URL" below.

The line that does NOT exist: a dense frame count. There is no log
line reporting how many dense frames were extracted. On the happy
path (ffmpeg present, frames extracted, whisper working, Argon key
present) the frame step, the transcription step, and the analysis
step are all silent. Do not wait for a "30 frames" line; it is not
in the code. The only frame evidence is negative: the absence of
the fallback warnings below. Dense extraction itself is one ffmpeg
call, `fps=1`, `scale=768:768:force_original_aspect_ratio=decrease`,
`-frames:v 30`.

Fallback lines, in pipeline order (appear only if triggered):

1. Frames. If ffmpeg is missing:

   ```
   [ingest] dense extraction skipped: ffmpeg not found on PATH
   ```

   (then the 6-frame path runs and, with no ffmpeg, also fails, so
   the next line follows.) If ffmpeg exists but dense extraction
   itself fails:

   ```
   [ingest] dense frame extraction failed (<reason>), falling back to 6-frame path
   ```

   If the 6-frame path also fails:

   ```
   [ingest] keyframe extraction failed (<reason>), falling back to mock placeholder
   ```

2. Transcription. Only if faster-whisper is missing or fails:

   ```
   FasterWhisperTranscriber: faster-whisper/model unavailable (<reason>); falling back to mock transcript.
   ```

   Or, on a transcribe failure rather than a load failure:

   ```
   FasterWhisperTranscriber: transcribe failed (<reason>); falling back to mock transcript.
   ```

   Note: the load-failure warning is logged once per server process
   (the failure is cached); a second chunk with no faster-whisper
   falls back silently, so a missing warning on chunk 2 does not
   mean whisper suddenly works. Check the scene transcript instead
   (step 4).

3. Argon analysis. Only on a fallback (thinking level `low`, max 30
   frames). If frames were all mock placeholders:

   ```
   ArgonSceneAnalyzer: zero real frames (placeholders only); returning mock draft.
   ```

   If frames are real but no key is set:

   ```
   ArgonSceneAnalyzer: no GEMINI_API_KEY/GOOGLE_API_KEY in environment; returning mock draft.
   ```

   If the Argon call or its reply parsing fails:

   ```
   ArgonSceneAnalyzer: Argon call/parse failed (<reason>); returning mock draft.
   ```

So the three shapes of a full run are: all green, only
`POST /api/v1/chunks` (real frames, real transcript, real Argon
draft); no key, everything else fine, `POST /api/v1/chunks` then
the no-key mock draft line, nothing else (frames and transcript are
real; only the scene draft is mock); no ffmpeg, no faster-whisper,
no key, `POST /api/v1/chunks`, dense-skipped, keyframe-failed,
whisper load-failed, zero-real-frames mock draft, in that order
(the upload still returns 202 and still creates a scene; every
stage degraded, none crashed).

### 4. Confirm the new scene in Memory

Do both checks; the API check is the ground truth, the app check is
the user-visible one. API check (from the Mac terminal):

```sh
curl -s http://localhost:8000/api/v1/status
curl -s "http://localhost:8000/api/v1/scenes/today?limit=5"
```

- `scene_count` in the status reply must be exactly BEFORE + 1.
  (Also, `spend_usd` rises by 0.07 per successful chunk, on every
  indexed chunk, mock or real.)
- `scenes/today` returns newest first, so the new scene is the
  FIRST entry in the list. It is not appended at the end.
- Open that scene's detail (`GET /api/v1/scenes/<id>`) and check:
  `summary` is the Argon summary on a green run, or the mock text
  `Live chunk indexed (mock scene)` on a mock-draft run; `quote`
  is the first transcript line, or
  `Live segment (mock transcript).` on a mock-transcript run;
  `confidence` is `review` and people are `Unknown` in both mock
  cases and in any real Argon draft (names are forced to `Unknown`,
  confidence capped at `review`).

App check: open the Scene phone app, Memory tab. The new scene
appears at the top of the list (same newest-first order). Pull to
refresh if it is not there immediately; the app polls as a backup
to the live socket. If the API count went up but the app shows
nothing after a refresh, that is an app/socket problem, not a
backend problem; do not re-upload, or you will create a second
scene.

### Failure branches

One branch per problem. Symptom first, then cause, then the exact
fix. In every branch, re-uploading without fixing the cause just
reproduces the same result (and adds another scene).

Missing audio part: 400. Symptom: HTTP 400 with body
`{"error": {"code": "bad_request", "message": "Missing video or
audio part."}}`, and no new scene (`scene_count` unchanged).
Cause: the chunk handler requires BOTH file parts. Sending only the
mp4, or sending the wav under a different field name (e.g.
`audio_file`), trips it the same way. A non-multipart body (e.g.
JSON via `-d`) gives a different 400,
`Expected multipart form data.` Fix: re-run the exact curl from
step 2 with both parts: `-F "video=@test.mp4" -F "audio=@test.wav"`.
Field names must be literally `video` and `audio`; the filenames
can be anything.

ffmpeg missing: mock keyframes. Symptom: upload still returns 202
and a scene is still created, but the server log shows, in order,
the dense-skipped line and the keyframe-failed line (step 3),
followed by the zero-real-frames mock draft line. The scene summary
is the mock text. Cause: ffmpeg is not on PATH, so dense extraction
returns empty and the 6-frame path also fails; ingest never raises
and falls back to the mock placeholder. Nothing is rejected; the
scene is just not grounded in real frames. Fix: install ffmpeg
(`brew install ffmpeg`), confirm with `which ffmpeg`, restart the
server (see the restart branch), then re-upload. The scene created
during the failure stays mock; only a fresh upload after the fix
gets real frames.

faster-whisper missing: mock transcript. Symptom: upload returns
202, scene created, but its transcript/quote reads exactly
`Live segment (mock transcript).` The server log shows the
faster-whisper load-failed line on the FIRST chunk after server
start, and may show nothing at all on later chunks (failure is
cached per process). Cause: the transcriber loads faster-whisper
lazily and degrades to the mock segment shape on any load failure;
ingest then backfills the mock's empty timestamps from the chunk
window, so the scene looks complete. Fix: install faster-whisper
into the same Python environment the server runs from, restart the
server, re-upload, and check that the new scene's quote is your
actual spoken words (or, for the Option A tone clip, real whisper
output for a tone, which may be empty or junk; use Option B,
speaking on camera, to verify transcription properly). The mock
scene from before stays mock.

Key missing: mock draft. Symptom: upload returns 202, scene
created, frames and transcript may be real, but the summary is
`Live chunk indexed (mock scene)` and the log shows the no-key mock
draft line (step 3). Cause: the analyzer checks for
`GEMINI_API_KEY` or `GOOGLE_API_KEY` in the server process
environment and returns the mock draft without calling Argon when
neither is set. This is a fallback, not an error, so there is no
4xx/5xx anywhere. Fix: set the key in the environment of the
terminal that starts the server, then restart the server and
re-upload. Never put the key in this runbook, in a curl command, or
in any file in the repo; the SDK reads it from the environment
only. The previously created mock scene does not upgrade itself.

Chunk too long or too short: no rejection, silent truncation.
Symptom: no error at all. A 60-second clip returns 202 like a
30-second one; a 10-second clip also returns 202. Cause: there is
NO duration validation anywhere in the routes or ingest code (the
only duration use is probing to place the 6 fallback seek points).
Over-long chunks are silently capped: dense extraction takes at
most 30 frames, and the analyzer samples anything over 30 down to
30. Under-long chunks just yield fewer frames (about one per
second). The scene then covers only part of the clip, or a thin
slice of it, with no warning saying so. Fix: do not expect a 400;
fix the input. Re-trim to exactly 30 seconds with the `-t 30`
command from step 1 and re-check with `ffprobe` before uploading.
If a clip must stay long, split it into 30-second chunks and upload
each separately.

Upload to the wrong backend URL. Symptom, one of three: `curl: (7)
Failed to connect` (nothing listening on that host/port); HTTP 404
with `{"error": {"code": "not_found", "message": "Unknown route:
..."}}` (a server answered, but the path is wrong, e.g.
`/api/chunks` without `/v1`, or `/api/v1/chunk` singular); or a
reply from some other service entirely (wrong port). Cause: the
only chunk route is `POST /api/v1/chunks`. `localhost` works only
from the Mac itself; a phone cannot reach the Mac's `localhost`
(use the Mac's LAN IP instead, same port 8000). Fix: from the Mac
terminal, use exactly `http://localhost:8000/api/v1/chunks`.
Confirm the server is the Scene backend first with
`curl -s http://localhost:8000/api/v1`, which should return
`{"service": "scene-backend", "rest": "/api/v1", ...}`. If that
fails, the server is not running; start it from `~/scene-backend`
before retrying the upload.

Server not restarted after the dense staging: old 6-frame code.
Symptom: uploads succeed, but the behavior matches the old code:
with ffmpeg missing, the log shows ONLY the keyframe-failed line
and never the dense-skipped line; with ffmpeg present, the logs
look identical either way (both paths are silent on success), so
logs alone cannot clear this branch. Cause: Python loaded the
ingest module once at server start. Files staged into
`~/scene-backend` afterwards (including the dense extraction) do
not take effect until the process restarts. There is no reload, no
file watcher. Fix: in the Mac terminal, check the loaded code
first:

```sh
grep -n "_extract_dense_frames\|_DENSE_MAX_FRAMES" ~/scene-backend/app/ingest.py
```

If that prints nothing, the dense code is not even in the file;
re-stage it. If it prints matches but the server predates the
staging, stop the server (Ctrl+C in its terminal), then start it
again from `~/scene-backend` with `python3 server.py`, and
re-upload. Do not expect the previously created scenes to change;
only new uploads use the new code, and each re-upload adds one more
scene to the count in step 4.

---
## Part 6. Glasses plus band connection run sheet

Who does this: Nayan, on the demo phone, at the venue. Nobody pairs
anything from the Mac. The glasses pair to the DEMO PHONE (Meta AI
app plus bridge app on that phone), not to the Mac. The Mac never
touches the glasses directly.

How to read this part: every step gives the exact action, what
success looks like, and the failure branch with its fix. Steps
marked [CODE-VERIFIED] match the bridge code in the repo. Steps
marked [FIELD] rest on field experience from the hackathon sweep,
not on code, and are labelled as such. Do not treat a [FIELD] step
as code-verified.

Bridge facts that shape this whole part [CODE-VERIFIED]: the bridge
is the iOS SceneBridge app on DAT SDK 1.0.1, medium resolution
504x896 at 24fps, raw video plus in-stream PCM audio at 16kHz mono,
and 30 second chunking from one continuous session (not one session
per chunk).

### Step 1. Decide the demo phone first, before any build or install [FIELD]

Action: primary, Isabella's phone is the demo phone; the build and
install come from Isabella's Mac onto her phone. Fallback, Nayan's
phone, only if Isabella's phone is unavailable. Why the phone
choice is load-bearing [FIELD, with one code check]: the SceneApp
project team is Isabella's (C9FJ8G22S9) and its bundle ID is
com.isabelladoan.sceneapp, so building from Nayan's Mac onto her
phone risks a signing fight with that hardcoded team. Note the code
nuance: in the repo, that team and bundle ID live in the SceneApp
project, not in the SceneBridge project. The SceneBridge project
uses bundle ID com.scene.bridge and has no hardcoded team, and its
README says to pick your Development Team in Signing and
Capabilities. Even so, do not change the team on either project
without Isabella, and still build from her Mac onto her phone,
because her phone is already set up for her team. Success: you
know, before touching Xcode, which phone is the demo phone and
whose Mac builds onto it. Failure branch: if the fallback phone
(Nayan's) is used, STOP before any build or install and do the
team-ID coordination step FIRST: confirm with Isabella which team
signs the build for Nayan's phone, and get her explicit go-ahead
for any team change. Do not silently switch the team to make the
build pass. If nobody can confirm the team, do not build. A failed
signing fight burns demo time and can leave a half-installed app on
the phone.

### Step 2. Meta AI Developer Mode ritual [FIELD]

Do this on the demo phone, in the Meta AI app, before registering.
Action: (1) Open the Meta AI app. (2) If Developer Mode is not
already enabled, enable it with 7 taps on the Developer Mode entry
(tap the same entry 7 times in a row). (3) Toggle Developer Mode
OFF, then back ON. (4) If an Install prompt or button is shown, tap
Install. (5) Confirm the toggle stays ON after you leave and
re-enter the screen. Success: Developer Mode reads ON, and the app
is ready to register the bridge. Failure branch, the
toggle-may-not-appear fix: if the Developer Mode toggle does not
appear at all, force-quit the Meta AI app completely (swipe it away
from the app switcher), reopen it, and retry the 7 taps. Do not
keep tapping a screen that never shows the toggle; the force-quit
plus reopen is the fix. If the toggle appears but flips itself back
OFF, repeat the OFF then ON cycle once. If it still will not stay
ON, stop and escalate rather than proceeding to registration:
registration against a phone with Developer Mode OFF will fail in
confusing ways later.

### Step 3. Connect glasses WITHOUT the band first when registering or updating [FIELD]

Action: when you register the glasses, or update their
registration, have the Neural Band powered off or out of range.
Pair and register the glasses alone. Only bring the band in later,
after the glasses stream (Step 8). Success: registration completes
with glasses only, no band in the loop. Failure branch: if
registration fails or the device list shows the wrong device while
the band is connected, disconnect the band, force-quit Meta AI, and
redo registration with glasses only. Do not debug a glasses problem
while the band is attached; the band is a second variable you do
not need yet.

### Step 4. Force-quit Meta AI before running the bridge [CODE-VERIFIED]

Action: after registration, force-quit the Meta AI app completely
(swipe it away from the app switcher) before opening the
SceneBridge app. Why [CODE-VERIFIED]: the bridge README states the
Meta AI app and the bridge fight over the same Bluetooth channel,
and the bridge empty-state text repeats it: "make sure the Meta AI
app is force-quit (it fights the bridge over the same Bluetooth
channel)." Success: Meta AI is not running in the background when
the bridge launches. Failure branch: if the bridge shows "No
glasses found yet" or the stream never starts, check first whether
Meta AI relaunched itself in the background. If it did, force-quit
it again and retry the bridge. This is the single most likely cause
of a device that registered fine but never appears in the bridge.

### Step 5. Bridge order: register, camera permission, device, session, start, camera [CODE-VERIFIED]

Follow this exact order in the SceneBridge app. The app UI enforces
the same order: registration, then camera permission, then the
device list, then the live stream screen. Action: (1) Launch
SceneBridge on the demo phone. The app configures the Wearables SDK
exactly once at launch, before any view touches it. (2) Tap
"Register glasses". Wait for the registration state line to change
from Unknown to a registered state. Complete any Meta AI callback
that appears; the app only forwards Meta Wearables callback URLs.
(3) Grant camera permission: tap "Request" if needed, then "Check"
to confirm it reads granted. Devices only appear after registration
AND camera permission are both done. (4) Wait for the glasses to
appear in the "Glasses" list. Tap the glasses entry to open the
Live screen. (5) On the Live screen, tap "Start stream". Behind
that button the code runs, in order: createSession, session start,
a wait of up to 10 seconds for the session to reach started state,
addCamera with the stream config, then stream start. Subscriptions
to video, audio, and state are attached BEFORE stream start so no
early frames are missed. (6) Only after the stream is running, tap
"Start session" (the backend session) and then "Record" to begin 30
second chunking. Recording is disabled in the UI until the stream
is running, so do not fight that gate: stream first, record second.
Success: registration state is registered, camera permission is
granted, the glasses appear in the list, the Live screen opens, and
"Start stream" flips to "Stop stream" with the stream state line
moving off Idle. Failure branch: registration fails (red error
line): re-check Step 2 (Developer Mode ON) and Step 4 (Meta AI
force-quit), then tap "Register glasses" again. Camera permission
denied: iOS will not re-prompt on a second tap. Go to the phone
Settings for SceneBridge, grant Camera there, return, and tap
"Check". Device never appears: Meta AI is still running (Step 4),
camera permission is not granted, or registration did not complete.
Fix in that order; do not jump to the stuck-broadcast ladder (Step
10) until these three are confirmed good. "Session did not reach
started state in 10s" or "addCamera returned nil": tap "Start
stream" again after the teardown gap in Step 11. If it fails twice
with the same error, go to Step 10, rung 1.

### Step 6. What proves real streaming: an actual frame callback, not a state [CODE-VERIFIED]

Action: after tapping "Start stream", watch the Live preview area,
not just the state line. Success (the only proof that counts): the
black preview box fills with a live camera image. In code, that
image arrives through the video frame callback, which sets the
current frame shown in the preview. Until a frame arrives, the
preview reads "No frame yet". Failure branch: the state line says
streaming (or a similar started state) but the preview still reads
"No frame yet" after 10 seconds: this is NOT streaming. Treat it as
the known zero-frames failure in Step 9. Stop the stream, wait the
Step 11 gap, and retry. Do not start recording: recording with no
frames produces empty 30 second windows that upload nothing useful.
Frames arrive but freeze: stop and restart the stream. A frozen
frame is a stale callback, not a live stream.

### Step 7. Phone stays awake during streaming [FIELD]

Action: before starting the stream, set the demo phone so its
screen does not auto-lock during the demo (Settings, Display,
Auto-Lock, Never, or keep the phone on charge with the screen on).
Keep the phone in hand or on a stand where the screen stays lit for
the whole demo. Success: the screen stays lit from stream start
through session end, with no lock in between. Failure branch: if
the phone locks mid-stream, unlock it and check the preview
immediately. If frames resume, continue, but reset Auto-Lock to
Never before the next run: a lock mid-demo is a demo break even if
the stream survives it. If frames do not resume after unlock, stop
the stream, wait the Step 11 gap, and restart from Step 5, step 5.

### Step 8. Band steps, only after the glasses work [FIELD]

Do not start this step until Steps 5 and 6 pass with glasses alone.
Action: (1) Bring the band charger to the venue. No charger, no
band in the demo. (2) Check the band charge by its LED before
pairing it: green solid, over 80 percent, good to demo; orange
solid, 20 to 80 percent, usable, but charge it if you have time
before the demo slot; blinking orange, under 20 percent, charge it
first, do not demo on a blinking-orange band. (3) Power the band on
and connect it to the glasses setup. (4) Confirm gestures reach the
lens as arrow keys plus Enter: pinch, swipe, and tap gestures on
the band arrive at the Scene Lens as ArrowKey and Enter key events.
Test each gesture once against the lens before the demo run and
confirm the lens responds to each. Success: LED is green solid or
orange solid, and every band gesture moves the lens the way an
arrow key or Enter press would. Failure branch: blinking orange,
charge the band (there is no low-battery workaround). A gesture
does nothing on the lens: re-check that the glasses stream is
still live (Step 6) before blaming the band. If the glasses work
and one gesture still does nothing, drop that gesture from the demo
script and use the phone fallback for that action. Do not debug band
gestures live in front of judges.

### Step 9. Firmware 129 warnings [FIELD]

These are known open issues on firmware 129. They hit the glasses
and the band setup equally, so they apply whether or not the band
is connected. Warning 1, Back tap ends the session: a band Back tap
can end a session despite consumeBack. The consumeBack guard does
not reliably stop it on this firmware. Rule: never make Back the
only navigation path. Every screen and every demo beat that Back
can reach must also be reachable another way (a forward gesture, a
tap, or the phone). Rehearse the demo with Back disabled in your
head: if any step strands you when Back kills the session, rewrite
that step before the demo. Warning 2, streaming with zero frames
arriving: streaming with zero frames arriving is a known open issue
with no workaround. The stream can report a streaming state while
no frame callback ever fires (see Step 6). Rule: test frame
delivery early, before judges, before the full demo rehearsal,
before anything depends on it. If the first stream test of the day
shows state but no frames, you have found this issue, and retrying
the same steps in the same order is not a fix: work the
stuck-broadcast ladder (Step 10) and re-test frame delivery after
each rung. If frames never arrive, the demo cannot use live glasses
video, and that decision must be made early, not discovered on
stage.

### Step 10. Stuck-broadcast recovery ladder, in order [FIELD]

Use this ladder when the glasses are stuck broadcasting, the bridge
cannot connect, or Step 6 shows state with no frames. Work the
rungs in order. Stop at the first rung that fixes it and re-test
frame delivery (Step 6) before continuing. Do not skip to the last
resort. Rung 1, Meta AI Stop or End button: open the Meta AI app,
find the live broadcast or session, and tap Stop or End. Success:
the broadcast ends and the glasses return to idle. If no Stop or
End button is visible, go to rung 2. Rung 2, hold the glasses
capture button 8 to 10 seconds: press and hold the capture button
on the glasses for a full 8 to 10 seconds, then release. Success:
the glasses stop broadcasting (LED or app state confirms idle). If
the glasses keep broadcasting, go to rung 3. Rung 3, glasses in
case, lid closed, 30 to 60 seconds: put the glasses in the case,
close the lid, and wait a full 30 to 60 seconds. Do not open the lid
early to peek. Success: on reopening, the glasses are idle and the
bridge can see them fresh. If they are still stuck after a full
minute in the case, go to rung 4. Rung 4, force-quit Meta AI plus
Bluetooth toggle: force-quit the Meta AI app completely, then
toggle the phone Bluetooth OFF, wait a few seconds, and toggle it
back ON. Success: the phone Bluetooth stack resets and the bridge
sees the glasses on the next attempt. If the bridge still cannot
connect, go to rung 5. Rung 5, forget device plus re-register, last
resort only: in the phone Bluetooth settings and in Meta AI, forget
the glasses device. Then redo the full path from Step 2 (Developer
Mode check) through Step 5 (register, camera permission, device,
session, start, camera), with the band disconnected per Step 3.
Success: a clean registration, and the device appears in the
bridge. Cost of this rung: it wipes the pairing, so it costs the
most time and must never be the first thing tried. If even a clean
re-register fails, the problem is not a stuck broadcast; escalate
instead of looping the ladder.

### Step 11. Session hygiene [CODE-VERIFIED, except the retry cap, which is FIELD]

These rules keep one continuous session alive instead of churning
sessions until the glasses refuse. Rule 1, at least a 2 second gap
between teardown and the next createSession [CODE-VERIFIED]: the
bridge code enforces this itself: after a stop, it waits until at
least 2.0 seconds have passed since the last stop before calling
createSession again, because the glasses can otherwise refuse with
sessionAlreadyExists. Your job: do not fight the code by
force-quitting and relaunching the bridge to "speed up" a restart.
Tap "Stop stream", count to 3, then tap "Start stream". The code
handles the gap; impatience breaks it. Rule 2, cap retries at 3
[FIELD runbook rule, not code]: if a stream start fails, retry at
most 3 times total, with the Step 11 gap between each attempt.
After the 3rd failed attempt, stop retrying and go to the Step 10
ladder instead. Looping retries past 3 does not fix a stuck
broadcast; it hides it. Note: this cap is about session start
retries. It is a different number from the chunk upload retry in
code (try once, retry once, then buffer to disk), which is about
uploads, not sessions. Rule 3, keep one session open rather than
rebuilding per chunk [CODE-VERIFIED]: recording runs as 30 second
windows inside one continuous stream and one backend session. The
chunk timer closes a window every 30 seconds and the next window
starts from the same stream; nothing in the code tears down and
recreates the device session per chunk. Your job: during the demo,
do not tap "Stop stream" and "Start stream" between chunks, and do
not end and restart the backend session to "refresh" it. Start the
stream once, start the session once, hit Record once, and let the
30 second windows roll. End the session only when the demo beat is
done.

End state check: stream stopped cleanly, session ended, glasses
idle, Meta AI still force-quit until the next run, band charger
packed. The next run starts again at Step 4, not at Step 1, unless
the demo phone changed.

---

## Convergence notes: what the six sections verified, and what they did not

What each section verified against code (repo HEAD 0ae8d43, plus
the workspace backend copy): backend, startup lines, status shape,
seed values, mock fallback log lines, spend rules, DB path rules;
phone, useMock default, base URL default and normalizer, token
handling, Developer section layout, spend row behavior, mock
inventory, socket no-reconnect behavior, auth rules, signing
identity; lens, URL param parsing, REST Bearer header, socket
construction and silent 3-second reconnect, Day fetch and render
rules, mock versus cached tells; seeded test, seed scenes and
facts, Ask routing and spend, follow-up generation and approval
gate, Day values in sequence; chunk test, chunk route and field
names, missing-part 400, dense ffmpeg invocation and fallback
chain, mock transcript and summary strings, newest-first ordering;
glasses plus band, bridge stream config and start order, register
and camera permission order, force-quit rule, frame-callback proof,
2-second teardown gap, 30-second chunking in one session, team and
bundle locations.

Known gaps, stated plainly, not papered over:

1. The lens page has no host. The backend serves no static route
   for the lens files, so this runbook gives the `?api=` suffix to
   append to whatever lens page URL is already in use. If no served
   lens URL exists yet, close that gap before Part 4 can run.
2. No dense frame count log line exists. On the happy path the
   frame, transcription, and analysis steps are all silent. Absence
   of fallback warnings is the evidence, plus the stale-server grep
   check in Part 5. Do not wait for a "30 frames" line.
3. No chunk duration validation exists. Over-long clips are
   silently capped at 30 frames; under-long clips yield fewer
   frames. Trim to exactly 30 seconds and verify with `ffprobe`.
4. Live-Argon spend is not always 0.12. With a live key, Argon may
   return an explicit dollar cost instead of the flat 0.12. In that
   case check spend deltas from the Step 0 baseline, not absolute
   values, in Part 3.
5. Team and bundle live in SceneApp, not SceneBridge. The bridge
   project uses com.scene.bridge with no hardcoded team. The team
   rule in Part 0 and Part 6 is stated for SceneApp and applied
   cautiously to the bridge build.
6. Lens and phone sockets differ. The lens silently reconnects 3
   seconds after a close. The phone app has no auto-reconnect by
   design; pull-to-refresh, Reload, and the 15-second Memory poll
   are its recovery. Do not apply one client's behavior to the
   other.
7. Mock data is recognizable, and every part uses that. Phone mock:
   8 canned scenes, Maya/Jordan/Priya counts, `$--` spend. Lens
   mock: same canned scenes, Day spend `$1.84`, Maya 3 quotes (the
   server seed has 6). Server seed: 8 scenes, Maya 5 scenes and 6
   quotes, Unknown 2 scenes and 0 quotes, spend 1.84 baseline. If a
   value matches a mock inventory instead of the server seed, you
   are looking at mock data.

Not verified at runtime (no server was started, no live call was
made, no device was touched, per the workflow limits): the venue
Wi-Fi name, the Mac's actual current LAN IP (re-verify with
`ipconfig getifaddr en0`), whether demo auth is on, the Xcode
trust-prompt flow, the literal Approve button text in the follow-up
detail sheet, the lens visual layout, live socket behavior end to
end, ffmpeg `testsrc2` availability on the Mac, and whether the
Memory 15-second poll runs while another tab is frontmost. Each
part states its own unverified items where they matter; treat
placeholders (`<Mac LAN IP>`, `PASTE_YOUR_KEY_HERE`) as values to
fill from the live environment, never from memory.

Source sections (kept for reference): 01-backend.md,
02-phone.md, 03-lens.md, 04-seeded-e2e.md, 05-chunk-test.md,
06-glasses-band.md, in ~/workspace/scene-wiring/.
