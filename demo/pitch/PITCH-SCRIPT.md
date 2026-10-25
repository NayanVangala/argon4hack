# Scene - 3-Minute Pitch Script (No Slides)

Hackathon: Gemini 4 Argon hackathon, Oct 25, 2026, San Francisco, 9am-10pm PDT.
Format: 3 minutes, no slides. Talk, then demo live.
Feature freeze: 7:30 PM PDT. Submission: 10:00 PM PDT.

How to read this script: each beat has a time mark and the rubric weight it serves.
Weights given in the brief: live demo 50, problem + usefulness 25, originality 15, pitch clarity 10.
Total time: 0:00 to 3:00. Do not run over. If a demo beat stalls, cut words, not the demo.

---

## 0:00-0:25 - The problem [Problem + usefulness, 25]

> "You make promises all day in conversation, and you forget half of them.
>
> Not big promises. Small ones. 'I'll send you that file.' 'I'll book that table.' 'I'll follow up tomorrow.'
>
> They live in your head, or in a transcript you will never re-read, and then they just disappear. The person waiting on you notices before you do."

Beat notes: one concrete problem, one specific person hurt by it. No stats, no invented numbers. Keep it to promises made in conversation.

## 0:25-0:50 - The spine [Problem + usefulness, 25 / Pitch clarity, 10]

> "Scene is a glasses-based day-memory app. It watches your day, it understands the whole day at once, and it makes sure you follow through on what you promised.
>
> Three parts. Scene watches your day. Argon understands the whole day at once. Scene makes sure you follow through."

Beat notes: say the spine verbatim. This is the one sentence the judges should remember if they remember nothing else:
Scene watches your day, Argon understands the whole day at once, it makes sure you follow through on what you promised.

## 0:50-1:05 - The originality line, said out loud [Originality, 15]

> "Here is what is different. We do not retrieve chunks and hope we got the right ones. The whole session is loaded into one 1M-token Argon context, with NO retrieval step.
>
> Ask does not search your day. It reasons over your entire day at once."

Beat notes: say "NO retrieval step" out loud, plainly. Do not soften it to "less retrieval" or "smarter retrieval." If asked later, the contrast is: whole-session reasoning vs chunk retrieval. Do not claim native video input as proven; that is unproven and is not in this script.

## 1:05-1:20 - The verification loop [Live demo, 50 / Problem + usefulness, 25]

> "And we do not trust the model to check itself. The Critic checks understanding itself: transcript alignment, visual grounding, people consistency, temporal sanity.
>
> For follow-ups, quote verification is done by code. The LLM proposes, code disposes. If a quote does not check out, it goes to needs_review. It never becomes a draft on a guess.
>
> And nothing sends without a tap. You approve, edit, or dismiss every follow-up."

Beat notes: this is the trust claim. Keep the three mechanics in order: Critic checks understanding, code verifies quotes, human approves before anything sends.

## 1:20-2:45 - Live demo, in order [Live demo, 50]

Do these beats in this order. Narrate what is happening, do not narrate ahead of it.

### 1:20-1:40 - Glasses recording

> "This is live. The glasses are recording right now."

Show the glasses recording. If the audience cannot see the glasses feed, say what the glasses see and show the phone or lens view that mirrors it. Do not pretend a recording is live.

### 1:40-2:00 - Scenes appearing

> "Scenes appear as the day is understood, not at the end of the day."

Show scenes appearing from the live or just-recorded input. Name one scene in plain words.

### 2:00-2:25 - Ask with verbatim receipts

> "Now I ask about the whole day at once."

Ask one reasoning question, not a lookup question. Good shape: an open promise, a contradiction, or a decision reconstruction. Then point at the receipts on screen: verbatim quotes, not paraphrases. Read one quote out loud, exactly as shown.

### 2:25-2:45 - Follow-up approve tap

> "And here is the follow-through. Scene found a promise, verified the quote, and drafted this. I approve it with one tap. Nothing sent before this tap."

Tap approve on camera. If the follow-up is a draft only, say so: "This is a draft. Nothing has been sent." Do not claim delivery (for example email sending) unless it actually happened live.

## 2:45-3:00 - Close [Pitch clarity, 10]

> "Scene watches your day, Argon understands the whole day at once, and it makes sure you follow through on what you promised. Thank you."

Beat notes: repeat the spine, then stop. Do not add a feature list, a roadmap, or a dashboard tour. The dashboard is backup only, never the demo lead.

---

## Fallback line (use only if glasses fail live)

Say this once, plainly, without hiding the failure:

> "The glasses feed just failed live, so I am showing the same flow on a seeded session plus a chunk upload instead, and the glasses failure is part of what you are seeing, not edited out."

Then run the same four demo beats in the same order on the seeded + chunk-upload path: recording equivalent (chunk upload), scenes appearing, Ask with verbatim receipts, follow-up approve tap. Do not claim the seeded demo is live glasses footage.

## Do not say

- Do not claim Managed Agents is done. It is in progress (see SUBMISSION-CHECKLIST.md).
- Do not claim Cloud SQL is running the demo unless it is actually provisioned and connected at demo time.
- Do not claim native video input is proven.
- Do not claim anything sent (email or otherwise) unless it actually sent live.
- Do not lead with or tour the dashboard.
- Do not claim a feature was built during the hackathon unless it was. Demo must only highlight features built DURING the hackathon.
