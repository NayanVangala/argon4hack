# SCENE — Final Build Spec
## A second mind for your glasses

**Status:** planning complete, pre-build. **Working title:** Scene (domain: helloscene.xyz). Judge's pick was Footage; Nayan leans Scene; nothing is locked.
**What this is:** the single source of truth. Everything from the design system to the in-lens app, in one document. Sibling deep-dives (`../butter-theme-guide/`, `../in-lens-app-spec/`) remain as reference but nothing essential lives only there.
**How to read it:** §1-3 product + architecture, §4 capture, §5 backend, §6 design system, §7 phone app, §8 web dashboard, §9 Scene Lens, §10 setup code, §11 demo scripts, §12 build plan, §13 judge checklist, §14 risks.

---

## 1. Product

### 1.1 One-liner
Your glasses remember everything you see and hear, and you can ask about any of it later.

### 1.2 The pitch (30 seconds, word for word)
"Memory lies. Footage doesn't. Scene is a second mind that rides on your glasses. It watches what you watch, listens to what you hear, and turns your day into a searchable memory. Ask it anything: 'What did Maya promise me?' — and it answers with the video receipt. I'm Nayan, and this is Scene."

### 1.3 Why now
Three things converged in 2026:
1. **Gemini 4 Argon** — a physical-reasoning model that actually understands video. $2/$10 per 1M tokens intro pricing through Nov 30, 2026, then it doubles. Video analysis is its strength.
2. **Meta Wearables Device Access Toolkit 1.0 stable** (Sept 30, 2026) — camera streaming from Ray-Ban glasses in one API call. The Instagram-Live-plus-FFmpeg hacks are obsolete.
3. **Web Apps on the Ray-Ban Display** (developer preview, May 2026) — a 600x600 in-lens screen any team can ship to with a URL and a QR code.

Nobody has combined all three into one product. The in-lens memory app is greenfield: the repo recon found zero projects combining in-lens display + gesture input with memory retrieval.

### 1.4 Competition and the one-line answers
- **Mira** ($6.6M seed led by General Catalyst, evolved from the viral I-XRAY demo): audio-first "second brain." Our line: *"Mira hears your day. Scene sees it."*
- **InSight** (Devpost, won its event): built our architecture before us — Ray-Ban Meta + diarization + face rec + Postgres + MCP, demoing "what did I discuss with Sarah last week?" Their capture was an Instagram Live + FFmpeg workaround; ours is one DAT API call. Their demo was transcripts-only; ours is video understanding. Our line: *"We did in one API call what took them a hack."*
- **Open Glass** (1st place, Cerebral Valley hackathon — same organizer family): $20 DIY glasses (sunglasses + 3D-printed case + ESP32 camera), photo every 5 seconds, mic always transcribing, live personal Q&A on stage. They won *through* a speech-to-text bug mid-demo because the core loop visibly worked. Within hours: 1,300 preorders. Lessons: wear the hardware, ask it personal questions on stage, demo through the bug, ship the video the same night.

### 1.5 The five surfaces
1. **Capture:** Ray-Ban Meta glasses (camera + mic) via iOS bridge or DAT; Neural Band for input.
2. **Backend:** ingestion → Argon scene understanding → Postgres + ChromaDB → REST API + MCP server.
3. **Phone app (main UI):** Live / Memory / Ask / People / Session, Butter theme, SwiftUI.
4. **Web dashboard:** laptop judges' screen + phone web fallback, Next.js + Tailwind + Motion.
5. **Scene Lens:** in-lens web app on the 600x600 display — glanceable timeline, voice Ask, pinch to pin.

### 1.6 User stories (the day-in-the-life that drives every design decision)
- **Morning:** Nayan puts on the glasses, taps record. The lens shows "● LIVE" and nothing else.
- **Midday:** In a conversation, Maya says "I'll send the Q3 numbers by Friday." He pinches his band. The lens flashes "Pinned ✓" for 1.2 seconds.
- **Afternoon:** "What did Maya promise me?" — dictated to the lens. Answer in the lens: "'The Q3 numbers by Friday' — 2:14 PM" with the video frame. On the phone: the same answer as a toy block with the receipt expandable to the full scene.
- **Evening:** He scrubs the Memory ribbon — the day as colored blocks — and asks "when did we talk about pricing?" Three scenes, each with a quote.
- **Night:** Kill switch. "Wipe the day. No blocks left behind." The lens goes dark.

---

## 2. System architecture

### 2.1 Diagram

```
┌─────────────┐   camera/mic    ┌──────────────┐   chunked     ┌────────────────────────┐
│ Ray-Ban     │ ─────────────▶ │ iPhone       │ ────────────▶ │ BACKEND                │
│ Meta glasses│   DAT / iOS     │ bridge app   │  30s chunks   │  ingest → Argon →      │
│ + Neural    │   bridge        │ (Swift)      │               │  Postgres + ChromaDB   │
│ Band        │                 │              │               │  REST API + MCP server │
└─────────────┘                 └──────────────┘               └──────┬─────────────────┘
      │                                                             │ fetch / WebSocket
      │ in-lens web app (600x600, Scene Lens)                       │
      │◀────────────────────────────────────────────────────────────┘
      │
      │ phone app (SwiftUI, MAIN UI) ◀──── same API ────▶ web dashboard (Next.js)
```

### 2.2 Component responsibilities
- **Glasses:** dumb sensors. Capture only. The only on-device inference is the band's own gesture model (muscle signals → discrete gestures, never raw EMG to apps).
- **iPhone bridge:** chunked 30s upload, auth token provisioning, QR pairing for Scene Lens, local chunk buffering when offline.
- **Backend:** the brain. Ingestion, Argon scene understanding, transcription, speaker attribution, embeddings, storage, retrieval, MCP tools. Source of truth for everything.
- **Phone app:** the main UI. Enroll people, browse memory, ask questions, control sessions. (Nayan's standing call: phone is primary, laptop is backup.)
- **Web dashboard:** judges' screen via AirPlay + phone web fallback. Same API, bigger canvas.
- **Scene Lens:** glance layer. Timeline, Ask, pin. Reads the same API; never asks for text input. The phone app and lens app never talk to each other directly.

### 2.3 Data flow for one 30-second chunk
1. Glasses capture 30s video + audio → phone bridge uploads the chunk.
2. Ingest: extract keyframes at ~1fps, keep the audio track; PySceneDetect pre-pass snaps chunk boundaries to real cuts (±3s).
3. One Argon call per chunk: objects, people, actions, visible text, 2-sentence scene summary → structured JSON.
4. whisperX: transcription with word timestamps + diarization → speaker attribution via face+voice fusion against enrolled prints; no match → "Unknown," never a guess.
5. Embeddings: text (summary + transcript) and visual (CLIP keyframes) into **separate** ChromaDB collections, fused at retrieval. Every vector carries start_ts/end_ts.
6. mem0-style extraction: durable facts ("Maya promised Q3 numbers by Friday") → Postgres facts table.
7. Postgres `scenes` row written; WebSocket push `{ event: "scene", scene }` to Scene Lens + dashboard.

### 2.4 Failure modes (designed in, not discovered on stage)
- **Chunk upload fails:** phone buffers locally, retries with backoff; session continues.
- **Argon call fails:** chunk marked `pending_retry`, retried 3x, then flagged REVIEW with transcript-only indexing (whisperX still runs). The pipeline degrades to audio-only rather than dropping the chunk.
- **No speech in chunk:** SILENCE confidence — still indexed visually (objects/actions), shown muted in the timeline.
- **Attribution uncertain:** REVIEW badge, never asserted as fact. The anti-I-XRAY rule: a guess presented as a name is a product-ending bug.
- **Backend unreachable from lens:** Scene Lens serves cached today's scenes from Service Worker; banner "offline — showing cached."

---

## 3. Capture layer

### 3.1 Glasses hardware (verified)
- **Ray-Ban Meta with Display:** 600x600 full-color micro-LED, monocular (right lens only), private to the wearer. 30 Hz panel (33ms frame budget — no 60fps loops). **Additive display:** black pixels emit no light = transparent. Peak ~5,000 nits, 42 pixels per degree.
- **Camera/mic:** capture path only. First-person video for Argon analysis requires the DAT native path or the iOS bridge — web apps cannot touch the camera.

### 3.2 Capture path decision
| Path | Capture | In-lens UI | Band input | Effort | Verdict |
|---|---|---|---|---|---|
| iOS bridge (exists) + web app | via bridge | web app | via web app key events | Lowest | **Hackathon pick** |
| DAT native + web app | DAT StreamSession | web app | via web app key events | Medium | Best "official" story |
| DAT native + DAM/FlexBox | DAT | native FlexBox | DAM click events | Highest | Most power, most risk |
| Extentos + web app | via Extentos | web app | via web app key events | Low | Verify band coverage first |

**Ship the hackathon on iOS bridge + web app.** Name DAT-native as the production path in the pitch. The canonical native reference is `facebook/meta-wearables-dat-ios` (SPM: MWDATCore/MWDATCamera/MWDATMockDevice; `Wearables.configure()`; registration via Meta AI deep link; `devicesStream()`; StreamSession). The plist/registration cookbook the official README skips lives in tomkrikorian's AGENTS.md gist (MWDAT dict with MetaAppID, `com.meta.ar.wearable` accessory protocol, bluetooth-peripheral/external-accessory background modes, `.onOpenURL` → `Wearables.shared.handleUrl`). Extentos `swift-glasses` wraps DAT 0.8.x and our bridge already builds on it — keep it as the fast path, but band input is undocumented there, so verify before depending on it.

### 3.3 Neural Band (verified, Meta docs)
| Band gesture | System meaning | Our mapping |
|---|---|---|
| Tap index on thumb | Select | Activate focused element |
| Thumb swipe on index (4-dir) | Scroll | Move focus / scrub timeline |
| Tap middle on thumb | Back | Back to Timeline |
| Double-tap middle | Wake/sleep | — (system) |
| Double-tap thumb on index side | Meta AI | — (system) |
| Hold middle to thumb | Switcher | — (system) |
| Wrist turn, index held | Zoom/volume | Scrub (reserved) |

**In web apps these arrive as standard keyboard events** (ArrowUp/Down/Left/Right + Enter). There is no cursor. Pinch is not a click at coordinates — it activates the focused element. **Focus management is the entire input model.** Test everything with arrow keys + Enter in a desktop browser.

**Hard truth:** no official phone-side band API exists. DAT 1.0 exposes camera/mic/audio/motion/IMU; band gestures are consumed by Meta's OS for in-lens navigation. Custom band features live in the in-lens web path (this spec) or unofficial reverse-engineered BLE (Kinesis/neural-band-poc — claiming the band unlinks it from Meta's app; firmware updates can break it). For the hackathon: web path for band input, bridge/DAT for capture.

### 3.4 Kill switch
Deliberate, two-step, placed last in focus order so it can't be hit accidentally. From Now: focus "Stop recording" → pinch → confirm screen with "Stop" focused only after a second focus move. No haptics exist on the platform, so every state change must be visible: the LIVE dot dies on screen, the lens can show nothing.

---

## 4. Backend

### 4.1 Ingestion pipeline (per 30s chunk)

```
chunk.mp4 + chunk.wav
  → store raw (object storage) + chunks row (status: received)
  → PySceneDetect pre-pass → snap boundaries to real cuts (±3s)
  → keyframes @ ~1fps (JPEG)
  → Argon scene-understanding call → scene JSON (§4.3)
  → whisperX (faster-whisper + word timestamps + diarization)
  → speaker attribution (ArcFace + ECAPA fusion vs enrolled prints)
  → text embed → ChromaDB text_memories (+ start_ts/end_ts)
  → CLIP keyframes → ChromaDB visual_memories (+ start_ts/end_ts)
  → mem0-style fact extraction → Postgres facts
  → Postgres scenes row (status: indexed)
  → WS push { event: "scene", scene }
```

**Argon call contract (prompt, per chunk):** send ~6 sampled keyframes + the instruction: "Describe this 30-second first-person scene as JSON: summary (2 sentences), objects[], people[] (count + brief descriptions), actions[], visible_text[] (any legible text). No narration, no speculation about off-camera events." One call per chunk keeps the bill legible (~120 calls/hour of recording). Cost anchor for judges: Olivia (AI Glasses Brazil finalist) runs one frame every 2 seconds — our 30s-chunk cadence is in the same envelope.

**Transcription backbone:** whisperX — faster-whisper for speed, word-level timestamps for quote receipts, diarization merged with Argon people descriptions. Do not hand-roll this.

**Chunking policy (from recon consensus):** chunk 10–30s → transcribe/caption → embed TEXT with start/end timestamps → retrieve top-K → LLM answers with timestamp citations. Keep visual (CLIP) and transcript embeddings in **separate collections, fuse at retrieval.** PySceneDetect pre-pass so 30s windows snap to real cuts. Frame sampling ~1fps (VisionClaw's throttle is the economical pattern).

### 4.2 Data model (Postgres)

- `sessions` — id, started_at, ended_at, device_id, status (live/ended).
- `chunks` — id, session_id, start_ts, end_ts, storage_path, status (received/processing/indexed/failed).
- `scenes` — id, session_id, start_ts, end_ts, summary, objects[] (text), people[] (text), actions[] (text), visible_text (text), type (conversation/person/action/quote/location/alert), verified (bool), confidence (verified/review/silence).
- `transcripts` — id, scene_id, speaker (name or "Unknown"), text, start_ts, end_ts, word_timestamps (jsonb).
- `people` — id, name, face_print_id, voice_print_id, enrolled_at, photo_thumb.
- `pins` — id, scene_id, note, created_at, source (phone/lens/voice).
- `facts` — id, text, scene_id, extracted_at, actors[] (text).
- `embeddings_meta` — collection, vector_id, scene_id, start_ts, end_ts.

**ChromaDB collections:** `text_memories` (scene summary + transcript embeddings), `visual_memories` (CLIP keyframe embeddings), `face_prints` (ArcFace), `voice_prints` (ECAPA). Enrollment = one photo + ~20s voice sample → prints stored here.

### 4.3 Scene JSON (Argon output contract)

```json
{
  "scene_id": "uuid",
  "start_ts": "2026-10-22T14:00:00-07:00",
  "end_ts": "2026-10-22T14:00:30-07:00",
  "summary": "Maya explaining Q3 numbers at the whiteboard",
  "objects": ["whiteboard", "laptop", "coffee cup"],
  "people": [{ "count": 1, "description": "woman, dark hair, gesturing at whiteboard" }],
  "actions": ["pointing", "talking"],
  "visible_text": ["Q3 revenue $4.2M"],
  "type": "conversation",
  "confidence": "verified"
}
```

**Confidence gating:** VERIFIED (face+voice agree) → shown with lime tick, asserted. REVIEW (one signal only) → muted badge, shown as candidate, never asserted as fact. SILENCE (no speech) → visual-only indexing, muted in timeline.

### 4.4 Retrieval (how Ask actually works) — whole-day unified context

The chunk → embed → RAG pipeline runs on any model. The moat is this: **the Ask path loads the entire session — every scene description, transcript, keyframe manifest, and fact — into a single Argon 1M-token context window and reasons over all of it at once.** No retrieval step, no top-K, no chunk-boundary blindness. This is the originality story: only possible on a 1M-context video-native model.

1. Assemble the day: all `scenes` + `transcripts` + `facts` for the session, ordered, into one context (a 60-min demo session is a few hundred K tokens — well inside 1M).
2. Facts are presented first in-context (mem0-style structured facts still win for promise/commitment questions), then scenes, then transcripts.
3. Argon reasons over the whole thing and answers **with timestamp citations** — every claim traceable to a scene_id + timestamp.
4. Demo questions are reasoning questions, not lookups: "what did I promise today that I haven't followed up on?", "did anyone contradict themselves?", "reconstruct every decision in order." Vector search cannot do these.
5. Long decode: the Day Digest — chapters, people, promises, open loops, contradictions — one sustained structured generation.
6. If nothing matches: "I don't have a record of that." (cite-or-say-no-record). Cost: ~$1–4 per Ask at intro pricing; the spend ticker shows it live.

### 4.5 API contract
- `POST /api/v1/sessions` → start; `POST /api/v1/sessions/{id}/end`.
- `POST /api/v1/chunks` — multipart chunk upload.
- `GET /api/v1/scenes/today` → `[{ id, start_ts, end_ts, summary, quote, thumb_url, type, verified }]`.
- `GET /api/v1/scenes/{id}` → full scene + transcript + keyframes.
- `GET /api/v1/status` → `{ recording, scene_count, last_scene_ts }`.
- `POST /api/v1/ask` `{ query }` → `{ answer, receipts: [{ scene_id, timestamp, quote, thumb_url }] }`.
- `POST /api/v1/pin` `{ scene_id?, note? }` → `{ pinned: true }`.
- `WS /api/v1/live` → `{ event: "scene", scene }` pushes.
- Auth: short-lived Bearer token provisioned by the phone app (QR pairing for Scene Lens). No passwords anywhere near the glasses.

### 4.6 MCP server (5 read-only tools)
`search_scenes` (NL → scenes with timestamps), `get_scene` (full detail), `list_people`, `list_interactions_with_person`, `get_facts`. Two tools beat twenty (InSight's lesson: they shipped exactly two). Publish it open-source at the hackathon — the Omi Apps Hackathon drew 123 projects on a memory API; openness wins developer love.

### 4.7 Follow-Through Agent (Managed Agents)

The agent that closes the loop from memory to action. Runs on Google's Managed Agents (sandboxed Linux: reason, call tools, execute code, manage files). This is the $5,000 "Best use of Managed Agents" lane — and the demo's closing beat.

**The loop:**
1. **Find:** `get_facts` → today's promises/commitments (e.g., "Maya promised Q3 numbers by Friday").
2. **Verify with code (the verification loop):** for each promise, `get_scene` → transcript; the agent runs deterministic code in the sandbox that fuzzy-matches the quoted text against the transcript segment and checks timestamp alignment. The LLM proposes the quote; code disposes. A quote that fails verification never becomes a draft — it surfaces as "unverified, needs review."
3. **Draft:** for each verified promise, draft the follow-up (message text to the person, with the verified quote attached).
4. **Approve:** drafts wait in the phone app. The user taps Approve / Edit / Dismiss per draft. Nothing sends without a tap.
5. **Send (stretch):** on approve, deliver via the wired channel (Resend for email). Demo floor: approve shows a sent state; real delivery is a stretch goal, not required.

**Why judges care:** ARIA won the managed-agents prize at Anthropic's hackathon by doing real computation in the sandbox instead of chatting. This agent does the same: it computes (verification), it acts (drafts), and it respects a human gate (approval). The pitch line: "Scene doesn't just remember what you promised. It makes sure you follow through."

**Trigger:** on demand ("follow through on today") from Ask or the Session screen, or auto-run at session end.

**Owner:** Isabella (agent + approval screens).

### 4.8 The Critic — render, watch, critique, fix

Statement Two's loop, built into the pipeline. Verification checks whether a quote is real; the Critic checks whether the understanding itself is right, and then fixes it. Scene never trusts its first draft.

**Per-scene critic (ingest time, runs after Argon describes a chunk):**
1. **Transcript alignment:** do the summary's key claims appear in the transcript? (entity overlap + embedding similarity, code.)
2. **Visual grounding:** do claimed objects and visible text actually appear in the keyframes? (Argon re-pass on 2–3 keyframes, or CLIP similarity.)
3. **People consistency:** does the claimed people count match faces detected across keyframes?
4. **Temporal sanity:** timestamps in order, no gaps, no overlaps.

Each check yields pass/fail + a note, stored on the scene as `critique: [{ check, result, note }]`.
- All pass → confidence unchanged.
- Any fail → confidence drops to review, and the **fix** step runs: re-run the Argon call with the failed checks appended ("you previously claimed X; the transcript does not support it — verify"), or route to needs_review if it still fails. The first draft never enters memory unchallenged.

**Per-answer critic (Ask time):**
1. **Receipt coverage:** every factual claim in the answer maps to a scene_id + timestamp.
2. **Quote verbatim:** quotes fuzzy-match transcript text.
3. **Relevance:** the answer addresses the query.
Fail → regenerate once with the failed checks as constraints; still failing → answer with only the verified subset, or "I don't have a record of that."

**Day-level critique (Day Digest section):**
- **Contradiction scan:** the same person saying conflicting things across scenes ("you told Maya X at 2pm and Y at 4pm").
- **Open-loop scan:** promises with no follow-through (feeds the Follow-Through Agent).

**The loop, stated for judges:**
- **Render:** timeline + digest built from raw captures.
- **Watch:** the agent monitors incoming scenes as they arrive.
- **Critique:** per-scene, per-answer, and day-level critic passes.
- **Fix:** re-run, downgrade, route to review, correct the record.

**Pitch line:** "Scene doesn't trust its first draft. Every scene gets critiqued against its own transcript and frames before it enters your memory, and every answer gets critiqued against its receipts before it reaches you."

---

## 5. Design system (Butter)

### 5.1 Philosophy (60 seconds)
From Butter's manifesto, translated for Scene: the memory is not a database you query, it is a **toy box you play with**. Every screen should feel grabbable. Nothing static, nothing flat, nothing that reads as a settings page. Creativity = exploration: scaffold, never blank canvases. "There are no flat pixels" — everything can animate, update, respond. Levels of detail: arrange blocks at the top level, refine one block deeper, act deeper still; the product never forces you down.

### 5.2 Color tokens (from Butter's production CSS)
| Token | Hex | Scene usage |
|---|---|---|
| `true-black` | `#0F0F0F` | Timeline strip, Live chrome, dark base |
| `black` | `#1E1E1E` | Primary buttons, body text on light |
| `charcoal` | `#3C3C3C` | Hover states, focus rings |
| `white` | `#FAFAFA` | App background (light mode), text on dark |
| `off-white` | `#F7F7F7` | Card surfaces |
| `light-grey` | `#EDEDED` | Nav pill, chips, inputs |
| `light` | `#EBEBEB` | Button label text |
| `hairline` | `#E2E2E2` | Dividers |
| `yellow` | `#E9D352` | Secondary accent (Butter's brand) |
| `blue` | `#4DC5E5` | Focus rings, interactive glow, action blocks |
| `green` | `#63AD45` | Success states, location blocks |
| `pink` | `#F9ABFF` | Quote blocks |
| `red` | `#FF3333` | Kill switch, destructive, alerts |
| `hot-pink` | `#EB3C8B` | Block color option |
| `vivid-green` | `#30A030` | Block color option |
| `lavender` | `#E8D5F5` | Block color option |
| `deep-purple` | `#6050C0` | Depth shading, dark accents |
| **`lime` (Nayan's brand)** | `#BCF015` | **PRIMARY accent: verified ticks, primary CTAs, the color judges associate with the demo** |

**Accent rule:** neutrals everywhere, color only where it means something. Lime = the agent noticed something (Heron AI's accent-as-signal philosophy). Block color by content type: conversation → yellow, person → lime, action → blue, quote → pink, location → green, alert → red.

### 5.3 Typography
- **Display:** "Die Grotesk C" (Klim, paid) — heavy neo-grotesque, tight leading. Free: **Archivo** (800–900, tight leading).
- **Body:** "ABC Diatype" (Dinamo, paid). Free: **Inter**.
- **Labels:** "ABC Diatype Mono" 12–14px, tracking +0.036em, 50% opacity. Free: **JetBrains Mono** or Geist Mono.
- **Scale:** Hero 48–64pt / 0.92–1.09 leading · H2 32–40pt / 0.94 · Subhead 24–28pt / 1.0 · Body 17pt / 1.31–1.5 · Small 15pt / 1.4 · Mono labels 11–12pt / 1.3. Display leading always under 1.1. One display + one body + one mono, never more. Headlines are short declaratives, never sentences.

### 5.4 Shape, depth, the 3D block recipe
- **Radii:** global 1rem. Buttons = chunky rounded rects, NOT pills. Floating nav = pill (1.6rem). Blocks = true squircles.
- **Shadows:** no drop shadows. Depth = glow stack on interactive elements + inflated inner highlight on blocks.
- **Glow stack** (verbatim Butter CSS, primary buttons + focused blocks):
```css
box-shadow: 0px 0px 4px #4DC5E5, 1px 1px 2px #4DC5E5, 1px 2px 2px #63AD45, 1px 4px 6px #E9D352, 1px 6px 10px #4DC5E5;
```
- **Toy block recipe:**
  1. True squircle via SVG clip-path (web) — path data:
  `M 0.5 0 c 0.2251 0 0.3477 0 0.4238 0.0762 a 0.2600 0.2600 0 0 1 0.0000 0.0000 c 0.0762 0.0762 0.0762 0.1987 0.0762 0.4238 L 1 0.5 c 0 0.2251 0 0.3477 -0.0762 0.4238 a 0.2600 0.2600 0 0 1 -0.0000 0.0000 c -0.0762 0.0762 -0.1987 0.0762 -0.4238 0.0762 L 0.5 1 c -0.2251 0 -0.3477 0 -0.4238 -0.0762 a 0.2600 0.2600 0 0 1 -0.0000 -0.0000 c -0.0762 -0.0762 -0.0762 -0.1987 -0.0762 -0.4238 L 0 0.5 c 0 -0.2251 0 -0.3477 0.0762 -0.4238 a 0.2600 0.2600 0 0 1 0.0000 -0.0000 c 0.0762 -0.0762 0.1987 -0.0762 0.4238 -0.0762 Z`
  (SwiftUI: `RoundedRectangle(cornerRadius: 28, style: .continuous)`.)
  2. Fill: saturated flat color or video thumbnail (`object-fit: cover`).
  3. **Inflated highlight:** inner white glow, blur = 15% of block width, radius 22.4%:
```css
.block::after { content: ""; position: absolute; inset: 0; border-radius: 22.4%;
  box-shadow: inset 0 0 calc(var(--block-width) * 0.15) rgba(255,255,255,1); pointer-events: none; }
```
  4. Painted 3D (hero art, empty states): saturated base + deep-purple ambient occlusion in crevices + hot-pink rim light on one edge. Three tones, always.
  5. Sizes: web `--width: min(20vw, 12rem)` → `min(20vw, 28rem)`; phone 72–120pt ribbon blocks.

### 5.5 Motion (the 5 springs — memorize these)
| Token | Feel | Framer Motion | SwiftUI | Use |
|---|---|---|---|---|
| `press` | Instant compress, no bounce | stiffness 550, damping 35 | response 0.22, damping 0.9 | Press-down squish |
| `snappy` | Fast settle, whisper of overshoot | stiffness 320, damping 26 | response 0.35, damping 0.72 | Default transitions, tabs, panels |
| `pop` | Clear overshoot, one bounce | stiffness 260, damping 17 | response 0.45, damping 0.55 | Release, block expand, entrances |
| `jelly` | 2–3 visible wobbles | stiffness 190, damping 12 | response 0.6, damping 0.38 | Drop settle, loading cascade |
| `drift` | Smooth, no overshoot | stiffness 130, damping 22 | response 0.5, damping 1.0 | Ambient, scrub-follow |

**Staggers:** 0.03 tight (rows) · 0.05 standard (cascades) · 0.07 dramatic (onboarding). Cap cascades at 0.5s total (one 1.2s onboarding moment allowed).
**Squash & stretch** (volume-preserving, scaleX × scaleY ≈ 1): press 1.12/0.88 · release 0.95/1.05 · hover inflate 1.03–1.05 · drag lift 1.06. Transform-origin at contact point for presses, center for hovers.
**Easings:** ease-out `cubic-bezier(0.200, 0.715, 0.205, 0.990)`; ease-in-out `cubic-bezier(0.835, 0.120, 0.225, 0.770)`; overshoot `cubic-bezier(0.34, 1.35, 0.64, 1)`.
**Doctrine:** easing + staggering + secondary motion. Entrances springy/elastic. Stagger collections a few frames per item, consistent seed. Secondary motion overlaps entrances (blocks sway subtly after landing). Text animates by word, not letter. Page transitions: out 0.98 scale + fade 0.22s; in rise 24px + fade on `snappy`; shared blocks morph via `layoutId`. Total under 0.5s.

### 5.6 Components
- **Primary button (3-layer):** label `#EBEBEB`; `::after` solid `#1E1E1E`; `::before` `#4DC5E5` glow, opacity 0, scaleY 0.9 → on hover fades in with infinite `hue-rotate(360deg)` 2s. Focus-visible: 0.3rem `#4DC5E5` outline, 0.3rem offset. Press → squish 0.94 (`press`), release `pop` overshoot.
- **Floating nav pill:** `#EDEDED`, 1.6rem radius. All navigation in one container. Active tab: black segment, white label, slides on `pop` (overshoot on the indicator is the signature).
- **Scene block:** squircle + thumbnail/color + inflated highlight + mono label chip. Press squish, tap shared-element expand, drag lift + tilt + jelly drop.
- **Timeline strip:** `#0F0F0F` stadium, time ruler ticks, playhead.
- **Labels:** mono 12–14px, tracking 0.036em, 50% opacity.
- **Loader:** gradient `#D6D6D6 → #FAFAFA`, display-type label, blocks cascade-assemble with `jelly` — the UI builds itself, never shimmer bars.
- **Cards:** squircle image tile + name below. No borders, no drop shadows.

### 5.7 Copy voice
Confident, declarative, playful but never silly. Short punchy headlines, second-person, block wordplay:
- Hero: "It's a whole new memory."
- Memory: "Your day, block by block."
- Ask: "Ask anything. There's a block for that."
- Empty: "No blocks yet. Go live a little."
- Session start: "Press record. Be present. We'll remember."
- People: "Every voice gets a block."
- Kill switch: "Wipe the day. No blocks left behind."
Rules: feature names are verbs. Headers are short imperatives. Emphasize removing friction. Never "unlock the power of," never "seamless," never "leverage."

### 5.8 What NOT to copy from Butter
Their marketing lavender/purple 3D tones (keep the functional block palette); desktop-only patterns (custom cursors, scroll marketing); two accents where one will do (lime leads, yellow supports). No purple-blue gradients, no SaaS card grids, no lorem ipsum.

---

## 6. Phone app (main UI) — SwiftUI, Butter theme

**Shared:** `ButterSpring` tokens (§9.1), squircle = `RoundedRectangle(cornerRadius: 28, style: .continuous)`, inflated highlight = white gradient overlay masked to block shape, haptics paired with every `pop`/`jelly` (light on grab, medium on drop, heavy on kill switch). Demo on a real phone — the toy feel does not survive the simulator.

### 6.1 Live (home, the hero)
Full-bleed camera feed (or latest keyframe when headless), zero chrome. Floating:
- Top-left status pill (`#0F0F0F`, white mono): "● LIVE", lime dot breathing 1→1.18 on `drift`, 1.1s loop.
- Top-center: "SCENE 12" in mono 50%.
- Top-right: "End" pill (`#EDEDED`, black text), squish on press.
- Bottom: current Argon scene caption as large display type directly on the feed, no card: "Maya explaining the Q3 numbers". Crossfades per scene on `snappy`.
- Detections arrive as small squircle sticker-blocks that `pop` in with 0.04 stagger, stacking in a corner pile: person name + lime verified tick; object labels in block colors.
- Elapsed clock in huge display type, lock-screen style (Butter-meets-VOID composition: giant time over live video).
- Motion: one orchestrated moment per scene change (caption swap + sticker pops), then quiet. The recording indicator is the only continuous motion.

### 6.2 Memory (the Butter screen)
- Top: day header in huge display type "TODAY", date in mono beneath.
- Dark timeline strip (`#0F0F0F` stadium, full-bleed, ~84pt) with time ruler ticks + playhead. On it the ribbon: horizontal scene blocks, squircle thumbnails, width ∝ duration, thin top color band by type.
- Press → squish (`press` down, `pop` release). Tap → `matchedGeometryEffect` shared-element expand on `pop` (~0.5s): summary, verbatim quote in display type, tap-to-play video receipt, "Pin" + "Ask about this" chunky buttons.
- Drag block out to pin: lift 1.06 + tilt toward drag, spring-lag follow, drop → `jelly` + medium haptic. Neighbors scoot on `snappy`, 0.03 stagger.
- Pull-to-refresh: ribbon stretches (scaleY 1.06, volume-preserved), release snaps back `jelly`.
- Loading: blocks cascade-assemble y 16→0, `jelly`, 0.05 stagger. The memory builds itself.
- Levels of detail: ribbon (arrange) → tap (refine: summary + quote) → tap quote (video receipt) → "Ask about this" (act). Never forced; every level one tap away.

### 6.3 Ask
NOT a separate chat tab — the Memory ribbon stays as base layer, Ask floats over it (Heron AI pattern: chat floats over the working surface).
- Floating input: chunky `#EDEDED` pill, display-type placeholder "Ask anything…", lime send block (squircle, squish on press).
- Answers arrive as toy blocks that `pop` in: answer in body type; video receipt as mini squircle (thumbnail + timestamp + verbatim quote in display type, bracketed receipt line: `[MAYA · VERIFIED VERBATIM · 4:32 PM]`).
- Suggested questions as small color chips above input ("What did Maya promise?", "When did we discuss pricing?"). Tap → chip squishes, question flies into input.
- Answer blocks tap-to-expand via the same shared-element morph as Memory.

### 6.4 People
Vertical stack of speaker blocks: squircle in the person's color, avatar (enrolled photo) with lime verified tick, name in display type, mono stats ("14 quotes · 6 scenes · verified"). Tap → mini ribbon of their moments.
- Enrollment: photo + 20s voice → prints stored; the person's block assembles with `jelly` cascade on completion. Copy: "Every voice gets a block."
- Unknown segments listed with an "enroll" affordance. Never shows a guess as a name.

### 6.5 Session
Radically simple:
- Center: one giant chunky record button (3-layer Butter button at 120pt, squircle). Idle: black, "RECORD". Recording: red `#FF3333` with breathing glow.
- Beneath: mono 50% stats: "2H 14M · 23 BLOCKS · 0 GAPS" + live Argon spend ticker (judges ask about cost — show the number).
- Kill switch: big red squircle buzzer, long press travel (scale 0.88), overshoot release, heavy haptic thunk. Confirm sheet rises `pop`: "Wipe the day. No blocks left behind." / "Wipe it" (red) / "Keep" (black).
- The anti-dashboard: one state change + one kill switch, nothing else.

### 6.6 Navigation
One floating pill (`#EDEDED`, 1.6rem), bottom-docked: Live / Memory / Ask / People / Session, icons + mono labels. Active: black segment, white label, slides on `pop`. The pill gets the inflated highlight so it reads as a toy, not chrome.

---

## 7. Web dashboard (Next.js + Tailwind v4 + shadcn + Motion)

**Purpose:** judges' screen via AirPlay + phone web fallback. Same API as the phone app; no separate backend.

### 7.1 IA
1. **Overview** (default): today's block ribbon + day stats + Argon insight block.
2. **Timeline:** full-width explorer — dark strip, zoomable ribbon, filter chips.
3. **Ask:** ribbon minimized to top strip, answers as blocks in main canvas, receipt stage.
4. **People:** speaker block grid. **Sessions:** session blocks + detail. **Settings:** minimal, mono labels, chunky toggles.

### 7.2 Laptop layout (≥1024px)
- Floating nav pill centered top (more Butter than a side rail).
- Main canvas `#FAFAFA`. Hero per page: huge display headline ("TODAY", "ASK ANYTHING") with mono kicker at 50% above.
- Overview: 3 stat blocks (blocks captured, people, quotes — squircle, saturated, inflated highlight, big display numerals) → full-width dark timeline strip with ribbon → Argon insight block (yellow `#E9D352`, display opener: "Ask remembers." + grounded fact + action button; miralife's copy anatomy).
- Timeline explorer: filter chips (color dots + mono labels) → zoomable ribbon (−/+ chunky squircles, zoom springs `snappy`) → detail panel slides in right on `pop` (shared `layoutId` morph from ribbon block to panel header).
- Ask: two-pane — left chat column (input pill docked bottom, answer blocks stacking `pop`), right receipt stage (selected frame large in squircle, quote in display type beneath).
- Dark `#0F0F0F` statement bands alternate with light sections (Butter's layout rhythm). Section padding 100–140px.
- Hover everywhere: blocks inflate 1.04, cursor-following tilt on hero blocks (`stiffness 150, damping 20`).

### 7.3 Phone layout (<768px)
Single column, bottom-docked floating nav pill (mirrors the app). Ribbon full-bleed horizontal scroll with edge fade masks. Stat blocks stack 1-up; headlines via `clamp()`. Ask: single column, receipt stage becomes a bottom sheet (`pop` rise, `drift` backdrop). Touch = press: everything squishes. No hover states.

### 7.4 shadcn mapping
- `Button` → 3-layer Butter button (primary black, accent lime, danger red). Keep API, replace CSS.
- `Card` → `Block`: squircle clip, saturated bg/thumbnail, inflated highlight, no border, no shadow.
- `Badge` → mono kicker chip. `Input` → chunky `#EDEDED` pill. `Dialog`/`Sheet` → `pop` rise + `drift` backdrop. `Tabs` → sliding pill indicator with `pop` overshoot. `Skeleton` → never; loading = blocks cascade-assembling.

### 7.5 Responsive rules
One codebase, fluid type via `clamp()`, padding 25px → 80px. Breakpoints 768 / 1024. The dashboard must feel like the same toy box as the phone app, not a "desktop admin version." Same blocks, same springs, same colors. If it looks like a SaaS dashboard, the brief has failed.

---

## 8. Scene Lens (in-lens web app)

### 8.1 Platform facts (verified, Meta docs)
- **Display:** 600x600 micro-LED, monocular right lens, private. 30 Hz (33ms frame budget). **Additive: black = transparent.** Validate every screen over bright backgrounds in the simulator.
- **Input:** band gestures arrive as **keyboard events** — swipes = ArrowUp/Down/Left/Right, index pinch = Enter on the focused element, middle tap = Back (system). No cursor. **Focus management is the entire input model** — predictable order, always-visible focus ring. Test with arrow keys + Enter on desktop.
- **Text entry:** focus input + pinch → system Composer (band handwriting, dictation, on-screen keyboard). No password fields.
- **Runtime:** `fetch` + WebSocket work; localStorage works; Service Worker + Cache API for offline. Startup budget 300 KB / 15 requests. **No camera, no mic, no notifications** for web apps — capture stays on the bridge/DAT path.
- **Audio:** playback through glasses speakers + TTS. Cannot record.
- **App model:** public HTTPS URL (valid TLS). Sideload in Developer Mode via Meta AI app or QR/deep link. History capped at 5 entries — shallow navigation by construction.
- **Distribution:** no store yet; dev-mode sideload is fine for the hackathon.
- **Testing:** Meta's official Ray-Ban Display Simulator Chrome extension (exact 600x600 additive display, environment backgrounds, D-pad injection, QR to glasses, perf scoring) + displayglasses.dev previews.
- **Samples:** `facebook/meta-wearables-webapp` (AI toolkit + Snake example), `@wearables-ui-toolkit/mrbd` React library, live docs MCP `mcp.developer.meta.com/wearables`.
- **Baseplate:** `levin-riegner/lr-rbm-demos` — 52 open-source 600x600 web apps with lens-output previews and QR loading. Fork one, reskin.

### 8.2 Architecture
Backend is the source of truth (Postgres + ChromaDB). Scene Lens polls/streams (`GET /scenes/today`, `GET /status`, `POST /ask`, `POST /pin`, `WS /live`). Writes back pins only. The phone app and lens app never talk directly — both hit the same API. The lens stays a dumb, fast glance layer. Auth: short-lived Bearer from phone-app QR pairing.

### 8.3 Screens
**Now (default, ambient):** only when recording — the lens must be able to show nothing. Top: "● LIVE" lime, breathing. Center: current scene summary, one large line ("Maya explaining Q3 numbers"). Bottom: mono "SCENE 12 · 4:32 PM". One focused action: "Pin this moment." 2-second read.

**Timeline:** vertical card stack, roving focus (swipe up/down moves, pinch opens). Card = thumbnail squircle + one-line summary + timestamp footer + lime tick if verified/pinned (Glass timeline-card anatomy: image, text, footer). Past ~20 cards collapse to "+14 earlier." Empty: "No scenes yet. The day is young."

**Ask:** prompt screen ("Ask about today" + "or hold to dictate") → focus input + pinch opens Composer dictation → answer immersion (takes over, dismisses back to Timeline): one-line answer, then receipt card (thumbnail + timestamp + verbatim quote). Swipe down = back. Pinch receipt = pin. Staged disclosure always: answer → receipt → (pinch) full scene. Never a wall of text.

**Pin confirm:** transient "Pinned ✓" overlay, 1.2s. Pinning must feel instant.

**Navigation:** Timeline is the persistent layer; Ask answers are immersions that dismiss back. Back always returns to Timeline.

### 8.4 Gesture map
| Gesture | Timeline | Now | Ask answer |
|---|---|---|---|
| Swipe up/down | Move between cards | — | Scroll receipt |
| Swipe left/right | — (reserved) | — | — (reserved) |
| Index pinch (Enter) | Open focused scene | Pin this moment | Pin receipt / activate |
| Middle tap | Back (system) | Back (system) | Back to Timeline |
| Dictation (Composer) | — | — | Enter query |

### 8.5 The 7 hard lens rules
1. Black is transparent — bright-on-dark everything.
2. One glance, one message, 2–3 seconds max. Longer belongs on the phone.
3. Max 3–4 focus targets per screen. Focus ring is the only affordance.
4. Type is the interface: body ≥16px, key content 20–24px, bold over bigger, short declarative lines, no paragraphs.
5. Progressive disclosure: answer → receipt → scene.
6. Ambient by default, takeover on demand. The lens can show nothing.
7. No haptics, no hover, no fine motor. Destructive actions get an explicit focused confirm step.

**Butter translation for the lens:** saturated colors work (they emit light); white floods glare. Keep block color-coding as chips/ticks, lime for verified/pinned, big bold type, drop large white surfaces. The toy-block feel becomes typographic.

### 8.6 Core code
```js
// The entire band input contract. No SDK.
const cards = [...document.querySelectorAll('[data-focusable]')];
let fi = 0;
const render = () => {
  cards.forEach((c, i) => c.classList.toggle('focused', i === fi));
  cards[fi]?.scrollIntoView({ block: 'nearest' });
};
document.addEventListener('keydown', (e) => {
  if (e.key === 'ArrowDown') { fi = Math.min(cards.length - 1, fi + 1); render(); }
  if (e.key === 'ArrowUp')   { fi = Math.max(0, fi - 1); render(); }
  if (e.key === 'Enter')     { activate(cards[fi]); }
});
```
```js
// Live scenes
const ws = new WebSocket('wss://api.helloscene.xyz/api/v1/live?token=' + TOKEN);
ws.onmessage = (m) => {
  const { event, scene } = JSON.parse(m.data);
  if (event === 'scene') prependSceneCard(scene); // newest-first, cap 20, then collapse
};
```
```js
// Optional voice tool (WebMCP, off by default — feature-detect)
if (document.modelContext) {
  await document.modelContext.registerTool({
    name: 'pin_moment',
    description: "Pins the current moment to the wearer's memory timeline.",
    inputSchema: { type: 'object', properties: { note: { type: 'string' } } },
    async execute({ note }, { signal }) {
      await fetch('/api/v1/pin', { method: 'POST', body: JSON.stringify({ note }), signal });
      return { pinned: true, next_action: 'Tell the wearer the moment was pinned.' };
    }
  });
}
// Gotchas: primitives only (objects arrive as JSON strings); enum/minimum/default
// silently dropped — validate inside execute(); 10s deadline; names ≤57 chars;
// unregister via AbortSignal on context change.
```

### 8.7 Lens build plan (~1 focused day)
1. Scaffold (30 min): fork `lr-rbm-demos` app or Meta's Snake example. 600x600 viewport, dark base, focus-ring styles.
2. Mock backend (1 hr): static JSON, 8 fake scenes. Timeline + focus nav working with arrow keys on desktop.
3. Simulator pass (1 hr): Meta Chrome simulator, bright environments, fix contrast/type.
4. Wire real API (2 hrs): swap mock for §4.5 contract; WS live scenes; pin + ask end to end.
5. Hardware test (1 hr): QR sideload in Developer Mode; verify swipe = arrows, pinch = Enter, focus order.
6. Harden: offline fallback (Service Worker caches today's scenes), kill-switch confirm, idle "show nothing" state.

### 8.8 The 60-second lens demo (word for word)
1. (0s) Wearing the glasses. "My glasses have been recording today."
2. (10s) "In my lens right now: today's timeline." Swipe thumb through 3 scene cards — judges see your hand, you narrate what you see.
3. (25s) "What did Maya promise me?" — dictate. Beat. "There it is: 'the Q3 numbers by Friday,' 2:14 PM, with the video frame." Pinch to pin.
4. (45s) "And if I want it to forget —" deliberate stop gesture. "It's off. That's the whole product: it remembers everything, until you say otherwise."
5. Never touch the phone. That is the demo.

---

## 9. Setup code (copy-paste)

### 9.1 Tailwind v4 theme (`app/globals.css`)
```css
@theme {
  --color-true-black: #0F0F0F;
  --color-ink: #1E1E1E;
  --color-charcoal: #3C3C3C;
  --color-paper: #FAFAFA;
  --color-off-white: #F7F7F7;
  --color-pill: #EDEDED;
  --color-hairline: #E2E2E2;
  --color-accent: #BCF015;       /* lime: primary accent */
  --color-butter-yellow: #E9D352;
  --color-block-blue: #4DC5E5;
  --color-block-green: #63AD45;
  --color-block-pink: #F9ABFF;
  --color-danger: #FF3333;
  --color-hot-pink: #EB3C8B;
  --font-display: "Archivo", sans-serif;
  --font-body: "Inter", sans-serif;
  --font-mono: "JetBrains Mono", monospace;
  --ease-butter-out: cubic-bezier(0.200, 0.715, 0.205, 0.990);
  --ease-butter-in-out: cubic-bezier(0.835, 0.120, 0.225, 0.770);
  --ease-overshoot: cubic-bezier(0.34, 1.35, 0.64, 1);
  --radius-butter: 1rem;
  --radius-pill: 1.6rem;
}
```

### 9.2 Motion springs (web, `lib/springs.ts`)
```ts
export const springs = {
  press:  { type: "spring", stiffness: 550, damping: 35 },
  snappy: { type: "spring", stiffness: 320, damping: 26 },
  pop:    { type: "spring", stiffness: 260, damping: 17 },
  jelly:  { type: "spring", stiffness: 190, damping: 12 },
  drift:  { type: "spring", stiffness: 130, damping: 22 },
} as const;
export const squashPress = { scaleX: 1.12, scaleY: 0.88 };
export const squashRelease = { scaleX: 0.95, scaleY: 1.05 };
```

### 9.3 SwiftUI tokens (`ButterTheme.swift`)
```swift
import SwiftUI

enum ButterSpring {
    static let press  = Animation.spring(response: 0.22, dampingFraction: 0.9)
    static let snappy = Animation.spring(response: 0.35, dampingFraction: 0.72)
    static let pop    = Animation.spring(response: 0.45, dampingFraction: 0.55)
    static let jelly  = Animation.spring(response: 0.6,  dampingFraction: 0.38)
    static let drift  = Animation.spring(response: 0.5,  dampingFraction: 1.0)
}

enum ButterColor {
    static let trueBlack = Color(hex: "0F0F0F")
    static let ink       = Color(hex: "1E1E1E")
    static let charcoal  = Color(hex: "3C3C3C")
    static let paper     = Color(hex: "FAFAFA")
    static let pill      = Color(hex: "EDEDED")
    static let hairline  = Color(hex: "E2E2E2")
    static let accent    = Color(hex: "BCF015")
    static let yellow    = Color(hex: "E9D352")
    static let blue      = Color(hex: "4DC5E5")
    static let green     = Color(hex: "63AD45")
    static let pink      = Color(hex: "F9ABFF")
    static let danger    = Color(hex: "FF3333")
}

struct SceneBlock: View {
    let color: Color
    let label: String
    let time: String
    @GestureState private var pressing = false

    var body: some View {
        ZStack(alignment: .bottomLeading) {
            RoundedRectangle(cornerRadius: 28, style: .continuous).fill(color)
            RoundedRectangle(cornerRadius: 28, style: .continuous)
                .fill(LinearGradient(colors: [.white.opacity(0.35), .clear],
                                     startPoint: .top, endPoint: .center))
            VStack(alignment: .leading) {
                Text(label).font(.custom("JetBrainsMono-Regular", size: 11)).opacity(0.7)
                Text(time).font(.custom("Archivo-Black", size: 17))
            }
            .foregroundColor(.black).padding(12)
        }
        .frame(width: 112, height: 112)
        .scaleEffect(x: pressing ? 1.12 : 1.0, y: pressing ? 0.88 : 1.0)
        .animation(pressing ? ButterSpring.press : ButterSpring.pop, value: pressing)
        .gesture(DragGesture(minimumDistance: 0)
            .updating($pressing) { _, state, _ in state = true })
        .sensoryFeedback(.impact(weight: .light), trigger: pressing)
    }
}
```

### 9.4 Butter button glow (web CSS)
```css
.butter-btn { position: relative; border-radius: 1rem; padding: 0.8rem 1.5rem; }
.butter-btn::after {
  content: ""; position: absolute; inset: 0; z-index: -1;
  background: #1E1E1E; border-radius: inherit;
}
.butter-btn::before {
  content: ""; position: absolute; inset: 0; z-index: -1; border-radius: inherit;
  background: #4DC5E5; opacity: 0; transform: scaleY(0.9);
  transition: opacity .25s, transform .25s;
}
.butter-btn:hover::before {
  opacity: 1; transform: scaleY(1);
  animation: hue-cycle 2s linear infinite;
}
@keyframes hue-cycle { to { filter: hue-rotate(360deg); } }
.butter-btn:focus-visible { outline: 0.3rem solid #4DC5E5; outline-offset: 0.3rem; }
```

### 9.5 Scene block (web, `components/scene-block.tsx`)
```tsx
"use client";
import { motion } from "motion/react";
import { springs, squashPress } from "@/lib/springs";

export function SceneBlock({ color, thumbnail, label, time, onTap, layoutId }: {
  color: string; thumbnail?: string; label: string; time: string;
  onTap: () => void; layoutId: string;
}) {
  return (
    <motion.button
      layoutId={layoutId}
      onClick={onTap}
      className="scene-block"
      style={{ background: color, clipPath: "url(#squircle)" }}
      whileTap={{ ...squashPress, transition: springs.press }}
      whileHover={{ scale: 1.04, transition: springs.snappy }}
      transition={springs.pop}
    >
      {thumbnail && <img src={thumbnail} alt="" />}
      <span className="block-label">{label}</span>
      <span className="block-time">{time}</span>
      <span className="block-inflate" aria-hidden />
    </motion.button>
  );
}
```
```css
.scene-block { position: relative; }
.scene-block .block-inflate {
  position: absolute; inset: 0; border-radius: 22.4%;
  box-shadow: inset 0 0 calc(var(--bw, 120px) * 0.15) rgba(255,255,255,1);
  pointer-events: none;
}
.block-label {
  font-family: var(--font-mono); font-size: 12px;
  letter-spacing: 0.036em; opacity: 0.7;
}
```

---

## 10. Demo scripts

### 10.1 Stage demo — phone app (2 minutes, word for word)
1. (0s) Glasses on. "My glasses have been recording today."
2. (15s) **Live screen.** Point at the room; Argon sticker-blocks pop. "It sees what I see. Every person, every object, labeled live."
3. (40s) **Memory.** Scrub the block ribbon. "Every thirty seconds becomes a block. My whole day, as toys."
4. (70s) **Ask.** "What did Maya promise me?" Beat. Answer + video receipt. "Memory lies. Footage doesn't."
5. (100s) Pinch the band — lens flashes "Pinned ✓". "Pinned, without touching my phone."
6. (110s) Kill switch. "And when I want it to forget —" deliberate gesture "— it's off. It remembers everything, until you say otherwise."

### 10.2 Lens demo (60 seconds)
§8.8. The hands-free version. Same beats, phone never touched.

### 10.3 Lines for hard questions
- "How is this different from Mira?" → "Mira hears your day. Scene sees it."
- "How is this different from InSight?" → "They bridged with Instagram Live and FFmpeg. We do it in one API call — and we understand video, not just transcripts."
- "What does it cost to run?" → Point at the Session screen spend ticker. "Thirty-second chunks, about 120 Argon calls an hour. Here's today's number." (Have the number ready.)
- "Isn't this surveillance?" → "Everyone I record with is enrolled and consented. Uncertain attributions are never asserted — the system says 'Unknown' instead of guessing. And the kill switch wipes the day." (Say this in the same breath as the demo, before they ask — the I-XRAY lesson: name the fear before critics do.)
- "Does it work offline?" → "Capture buffers on the phone; the lens serves cached scenes. Indexing catches up when we're back."

---

## 11. Build plan

**Rule: no precoding the hackathon build.** This spec is the planning; the repo stays inspiration-only until build day.

### 11.1 Before the event (allowed: planning, accounts, environments)
- Argon API key + budget cap. Meta Developer account + DAT access. Vercel project. helloscene.xyz decision (purchase pending Nayan's tap: $1.99 first year, $13 renewal).
- Read: recallai (pipeline), LightMem-Ego (memory schema), DAT CameraAccess sample, lr-rbm-demos baseplate.
- Meta's live docs MCP (`mcp.developer.meta.com`) wired into the build environment.
- This spec = the build bible. Print it or keep it open.

### 11.2 Build day — phase order
1. **Backend skeleton (first hours):** Postgres + ChromaDB schemas (§4.2), chunk upload endpoint, 30s chunking, **mock Argon responses** so app teams build against the API contract (§4.5) immediately. Mock scene JSON must match the real contract exactly.
2. **Intelligence:** real Argon calls (§4.1 prompt), whisperX, face+voice attribution, embeddings, fact extraction, MCP server (§4.6).
3. **Phone app:** 5 screens (§6) against the real API. Build Memory + Ask first (the demo screens), Live overlays last (they need real scenes).
4. **Scene Lens:** fork baseplate → mock → simulator → wire API → hardware sideload (§8.7).
5. **Dashboard:** read-only Overview + Timeline first, Ask panel second (§7).
6. **Demo hardening:** offline fallback, kill switch, the uncut 60-second video (§10.2), pitch rehearsal (§10.1), spend ticker verified with a real number.

### 11.3 Team split (2 people)
- **Nayan:** backend + capture + demo. The pipeline, the Argon calls, the bridge, the stage.
- **Isabella:** phone app + dashboard + Scene Lens styling. Her spreadsheet-audit spec shows she thinks in verification — put her on Ask receipts and the confidence badges.

### 11.4 Definition of done (demo-day checklist)
- [ ] Glasses record → chunks → scenes appear in Memory within ~60s of capture.
- [ ] Ask answers a personal question with a video receipt, live, uncut.
- [ ] Lens: timeline scrubs, Ask works by voice, pinch pins, kill switch kills.
- [ ] Spend ticker shows a real number.
- [ ] 60-second uncut video filmed and posted the same night.
- [ ] MCP server public on GitHub.

---

## 12. Judge-impress checklist

**First 30 seconds:** app opens with the onboarding cascade (blocks drop `jelly`, stagger 0.07, headline rises, CTA pops last — one 1.2s choreographed moment, then quiet). Land on Live: full-bleed feed, giant clock, an Argon sticker-block pops within 3 seconds. The judge sees feed + label before you say a word. Tap sticker → squish → Memory ribbon → tap block → shared-element expand into the quote. That three-tap sequence IS the pitch.

**Wow interactions (ranked):** 1. squish-press on every scene block — if one thing is perfect, this. 2. tap → shared-element expand ("pick up the brick"). 3. drag-to-pin with jelly drop + haptics. 4. Live labels spring-popping like stickers, 0.04 stagger. 5. kill-switch buzzer: long press travel, overshoot release, heavy thunk. 6. pull-to-refresh ribbon stretch. 7. flyout domino cascades. 8. button rainbow-glow hover (web only).

**Polish:** every changing number overshoots (springy tickers). Loading is never a spinner. Empty states are toys ("No blocks yet. Go live a little." + bouncing squircle). Haptics on iOS for every pop/jelly — non-negotiable. `prefers-reduced-motion` on web. No purple-blue gradients, no SaaS card grids, no lorem ipsum, no "seamless".

---

## 13. Risks and open questions

- **Name:** Scene vs Footage unresolved. helloscene.xyz available — purchase pending Nayan's tap.
- **Age rule:** 18+ minimum unconfirmed; the application bot never answered. Backup: Meta global AI hackathon, Oct 26–Nov 4, remote, $1M.
- **Argon cost:** intro pricing ends Nov 30, then doubles. Budget cap from minute one; spend ticker visible.
- **Capture path:** iOS bridge vs DAT-native — decide before build day (§3.2).
- **Web Apps preview status:** APIs may change; pin the docs version you build against.
- **Battery/heat:** all-day recording is the real-world constraint; the demo needs 30 minutes.
- **Attribution honesty:** REVIEW vs VERIFIED is the product's integrity — and a judging criterion at glasses hackathons (privacy/data handling were explicit checkpoints at AI Glasses Brazil).
- **Event rules:** Luma link not yet provided; confirm power, wifi, and time slot when it lands.
- **Isabella's reply:** her response to the glasses pitch is still pending; the team split (§11.3) assumes she's in.

---

*Sources: Butter production CSS + manifesto + Awwwards SOTD data; Meta Wearables developer docs; facebook/meta-wearables-dat-ios; levin-riegner/lr-rbm-demos; 5-agent repo recon (recallai, LightMem-Ego, omi, talk-vid, whisperX, VideoRAG); naming arena verdict; Cerebral Valley precedent research (Open Glass, InSight, I-XRAY/Mira). Update this file when decisions change — it is the single source of truth.*



