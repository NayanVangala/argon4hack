# Scene frontend: phone app + Scene Lens

Everything in this folder was built during the Gemini 4 Argon SF Hackathon on **October 25, 2026** (hacking started 10:30 AM). Commit history shows the build.

Two clients, one backend. Both talk to the same REST API (`docs/SCENE-API-CONTRACT.md`) and never talk to each other.

| Part | What it is | Folder |
|---|---|---|
| **SceneApp** | The main iPhone app (SwiftUI) | `SceneApp/` |
| **Scene Lens** | The in-glasses app for the Ray-Ban Display (600×600 web app) | `lens/` |

---

## SceneApp (iPhone, SwiftUI)

Five tabs in a floating nav pill: **Live · Memory · Ask · People · Session**.

- **Live:** recording timer, the current scene as Argon describes it, detection stickers.
- **Memory:** today as a timeline of blocks (newest first on open, auto-refreshes every 15s when connected). Tap a block for the verbatim quote, video receipt, Pin, and "Ask about this".
- **Ask:** floats over Memory. Every answer comes with a receipt: the verbatim quote, who said it, when, and a confidence badge (**Verified** / **Review** / **Couldn't confirm**). Unknown speakers are never given a guessed name.
- **Follow-through:** runs the Follow-Through Agent (`POST /followups/generate`). The three agent steps tick off live (find promises → check each quote against the footage → draft follow-ups). Each draft shows its proof and what the agent checked. **Nothing is sent without an Approve tap**, and quotes the agent couldn't match stay under *Needs review* and can never be approved.
- **People:** enrolled speakers plus unknown voices.
- **Session:** record / stop (starts and ends a real session on the server), Argon spend, Wipe the day, and a **Developer** box to switch between mock data and a server.

### Run it

1. Open `SceneApp/SceneApp.xcodeproj` in Xcode.
2. Pick an iPhone simulator and press ▶.

It starts on built-in mock data, so it runs with no backend.

### Connect it to a backend

In the app: **Session → Developer → turn off "Use mock data"**, type the backend URL (default `http://localhost:8000`), tap **Reload**. The setting is saved on the phone, not in the repo.

To try it against the mock server:

```
python3 src/backend/mock-server/server.py
```

### Build check from Terminal

```
xcodebuild -project src/frontend/SceneApp/SceneApp.xcodeproj -scheme SceneApp -destination 'generic/platform=iOS Simulator' build
```

---

## Scene Lens (in-glasses web app)

A 600×600 web app for the Ray-Ban Display's right lens. The display is additive (black = see-through), so everything is bright-on-black.

**Input = focus.** The Neural Band's gestures arrive as keys: swipes are arrow keys, a pinch is Enter, back is Escape. Every screen has at most four focus targets and a visible focus ring, because there is no cursor.

Screens: **Now** (LIVE + current scene + Pin), **Timeline**, **Ask** (pinch the box to dictate with Meta's Composer), **Answer** with receipt, **Pinned** flash, **Stop** confirm (two steps, ends the session on the server), and an **Offline** mode that shows cached scenes.

### Run it

Open `lens/index.html` in a browser. Use ↑ ↓ to move, Enter to pinch, Esc to go back. It runs on mock data.

### Connect it to a backend

Add `?api=<backend URL>` to the address, for example:

```
lens/index.html?api=http://localhost:8000
```

On the real glasses the page must be served over **https**, and the backend must be https too (browsers block an https page from calling an http API).

---

## Design

Blue / white / black. Lime and other block colors from the original spec were replaced on build day. Red is used only for recording and destructive actions. Type: Archivo-style heavy display, Inter-style body, monospace only for evidence (timestamps, receipts, badges). Every button squishes on press; blocks cascade in.

## Known gaps (backend side)

- **No delete endpoint yet.** "Wipe the day" stops recording and hides the day in the app, but the data stays on the server until a delete endpoint exists.
- Ask receipts don't include the speaker name or a video clip URL yet. The UI shows them when the API adds them.
