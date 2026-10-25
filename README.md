# Scene

Your glasses remember everything you see and hear. Ask about any of it, with video proof.

Scene is a second mind on Ray-Ban Meta glasses. The design: glasses capture the day through an iOS bridge that uploads 30 second chunks, and the backend turns each chunk into a scene with a transcript, speaker attribution, and keyframes. Ask loads the whole session into one Gemini 4 Argon 1M-token context and reasons over all of it at once, with no retrieval step, and every answer carries a video receipt: a frame, a timestamp, and a verbatim quote. A Critic checks every scene against its own transcript and frames, and every answer against its receipts, before anything reaches you. The Follow-Through Agent finds today's promises, verifies each quote in code, drafts the follow-up, and waits for your tap. Nothing sends without approval.

Status today: the repo holds the real backend in `src/backend/` next to the contract-shaped mock. Live Argon Ask over a whole session is proven against the real backend. The bridge hardware stream test is still unrun. See "What is not here yet".

## Built during the hackathon

Built October 25, 2026, at the Gemini 4 Argon hackathon in San Francisco.

OnRecord, an earlier conversation-memory project, is inspiration and pattern reference only. No OnRecord code is in this repo or in the demo. Everything demoed here was built today, in this repo, during the hackathon.

## Live demo script (60 seconds, hands-free)

What we show on stage. The lens pieces (timeline swipe, Ask, pinch to pin, stop to dark) are built in `src/frontend/lens`. The live glasses link is untested until the bridge hardware stream test runs.

Glasses on, recording starts, the lens shows a LIVE dot and nothing else. Swipe the timeline in the lens with the Neural Band. Ask out loud: "What did Maya promise me?" The answer comes back in the lens with the video frame and the quote, and a pinch pins it. The stop confirm darkens the lens. The phone is never touched.

## Architecture

```
Glasses → iPhone bridge → backend → phone app / Scene Lens
```

- **Bridge** (`src/bridge`): Swift app on the Meta Wearables DAT SDK 1.0.1. Camera and mic stream sliced into 30s chunks, buffered locally when offline.
- **Backend** (`src/backend/`): the real pipeline, Python. Chunk ingest with real keyframe extraction, faster-whisper transcription, Argon scene understanding, Postgres plus ChromaDB storage, Ask on whole-session Argon context, 5 read-only MCP tools over stdio, Bearer auth. `src/backend/mock-server` holds the contract-shaped mock (Python stdlib only) the app teams built against; it serves canned data and does not enforce auth.
- **Phone app** (`src/frontend/SceneApp`): SwiftUI, the main UI. Live, Memory, Ask, People, Session.
- **Lens** (`src/frontend/lens`): web app on the 600x600 in-lens display. Timeline, voice Ask, pinch to pin.

Full API contract: `docs/SCENE-API-CONTRACT.md`. Team brief with the rubric mapping: `docs/SCENE-TEAM-BRIEF.md`. Build spec: `docs/SCENE-FINAL-SPEC.md`.

## Run it

Real backend (from the repo, needs an Argon key in the environment):

```bash
cd src/backend
export GEMINI_API_KEY=...
python3 server.py
```

REST: `http://localhost:8000/api/v1`. Live socket: `ws://localhost:8000/api/v1/live`. SQLite is the default store; Postgres with `SCENE_STORE=postgres DATABASE_URL=postgresql://localhost/scene` is optional. Keyframe extraction needs ffmpeg (`brew install ffmpeg`).

Backend mock (Python stdlib only, port 8000):

```bash
cd src/backend/mock-server
python3 server.py
```

`PORT=9000 python3 server.py` overrides the port. The mock serves canned data (8 scenes, Maya plus Unknown, 3 facts, 1 pinned scene), auth is not enforced, and restart resets to seed data.

Phone app: open `src/frontend/SceneApp/SceneApp.xcodeproj` in Xcode and run. It ships in mock mode. Flip the Developer switch in the Session tab to point it at a server; the default URL is `http://localhost:8000`, editable in that same section.

Lens: static web app, `src/frontend/lens/index.html` plus `lens.js`, no build step. It defaults to mock mode; point it at a server with `index.html?api=<server-origin>&token=<token>`, for example `?api=http://localhost:8000`.

Bridge: open `src/bridge/SceneBridge.xcodeproj` in Xcode (first open resolves the SPM package `facebook/meta-wearables-dat-ios`), or:

```bash
xcodebuild -scheme SceneBridge -destination 'generic/platform=iOS'
```

## Team

- **Nayan Vangala**: backend, capture, stage demo.
- **Isabella Doan**: phone app, lens, Follow-Through Agent, approval screens.

## What is not here yet

- The bridge hardware stream test has not been run yet.
- One real video chunk through the analyzer plus whisper is still unproven (needs ffmpeg plus a real chunk).
- The contract base URL `https://api.helloscene.xyz/api/v1` is a placeholder until a deploy URL exists, and the bridge still carries a dev token placeholder plus a Meta App ID placeholder.
- Spend is a flat 0.12 per Ask until token-based pricing lands, and the WebSocket token check is still open.
