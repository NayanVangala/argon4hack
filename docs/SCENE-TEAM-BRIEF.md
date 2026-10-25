# SCENE — Team Brief
## What we're building, why we win, and who's doing what

**One-liner:** Your glasses remember everything you see and hear. Ask about any of it, with video proof.

**The pitch:** "Memory lies. Footage doesn't. Scene is a second mind on your glasses. It watches what you watch, reasons over your entire day at once, and answers anything: 'What did Maya promise me?' — with the video receipt. I'm Nayan, and this is Scene."

---

## Why we win (the rubric, answered)

| Criterion (weight) | Our answer |
|---|---|
| Live demo (50%) | Glasses record → scenes appear in the timeline within ~60s → we ask live questions about our real day on stage. Every answer carries a video receipt (frame + timestamp + verbatim quote). Confidence badges (verified / review / unknown) are the verification loop. |
| Problem + usefulness (25%) | For people whose work is conversations and who can't afford to forget. Demo persona: us, the builders. Afterlife: open-source MCP server + in-lens app. |
| Originality (15%) | The entire day lives in **one Argon 1M-token context window**. No retrieval, no chunk boundaries. Only possible on a 1M-context video-native model. |
| Pitch clarity (10%) | 3 minutes, no slides: record → timeline → ask → pin → kill switch. |

## The Argon edge (read this twice)

Most memory systems chop your day into chunks, embed them, and retrieve fragments. We do something only Argon can: **the whole session — every scene description, transcript, and keyframe manifest — goes into a single 1M-token context, and the model reasons over all of it at once.**

That means our demo questions are reasoning questions, not lookups:
- "What did I promise people today that I haven't followed up on?"
- "Did anyone contradict themselves today?"
- "Reconstruct every decision we made, in order."

Vector search cannot do these. A 1M-context model can. That's the 15%.

## The three surfaces

1. **Backend** — ingest (30s chunks → Argon scene descriptions → transcripts → speaker attribution), Postgres + ChromaDB, REST API + MCP server. The Ask path loads the full day into one Argon context.
2. **Phone app** — Live / Memory / Ask / People / Session. Butter theme (playful toy-block design, lime accent). The main UI.
3. **Scene Lens** — web app on the glasses' in-lens display (600x600). Timeline, voice Ask, pinch-to-pin via the Neural Band. The hands-free demo.

Plus: the **Ask agent runs on Managed Agents** (Google's sandbox agent runtime) — it calls our MCP tools, runs analysis code, and exports results. That's our shot at the $5,000 Best Use of Managed Agents prize on top of the main prizes.

## Architecture (30 seconds)

```
Glasses → iPhone bridge → Backend (Argon → Postgres + ChromaDB)
                                              ↓
                        Phone app ←→ API ←→ Scene Lens (in-lens web app)
                                              ↓
                        Ask: full day → one Argon 1M context → answer + receipts
```

Full API contract (exact JSON for every endpoint + all 5 MCP tools): `SCENE-API-CONTRACT.md`
Full build spec (724 lines, everything): `SCENE-FINAL-SPEC.md`

## Build day plan (Sun Oct 25, 9am–10pm)

1. **Backend skeleton first** — schemas, chunk upload, API contract live with mock data so nobody blocks.
2. **Intelligence** — real Argon calls, transcription, attribution, whole-day-context Ask.
3. **Phone app** — Memory + Ask first (the demo screens), Live overlays last.
4. **Scene Lens** — fork the baseplate, wire the API, simulator pass, sideload to glasses.
5. **Harden** — offline fallback, kill switch, film the 60-second uncut video, rehearse the pitch.

## Roles

- **Nayan** — backend + capture + the stage demo.
- **Isabella** — phone app + Scene Lens styling + Ask receipts and confidence badges + the Follow-Through Agent (Managed Agents sandbox: promise extraction, code-verified quotes, draft follow-ups) and its approval screens.
- **2 slots open** (max team size 4) — dashboard + demo support.

## The 60-second demo

Glasses on. "My glasses have been recording today." Swipe the timeline in the lens. "What did Maya promise me?" — dictated, answered with the video frame, pinched to pin. "And if I want it to forget —" kill switch. "It remembers everything, until you say otherwise." Phone never touched.

## Event facts

Sun Oct 25, 9am–10pm PDT, San Francisco, in-person. $20K: $7,500 / $5,000 / $2,500 + $5,000 Best Use of Managed Agents. DeepMind judging in person. Application + approval required — apply now.
