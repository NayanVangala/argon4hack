# Scene - Submission Checklist

Hackathon: Gemini 4 Argon hackathon, Oct 25, 2026, San Francisco, 9am-10pm PDT.
Feature freeze: 7:30 PM PDT. Submission: 10:00 PM PDT.
Repo: https://github.com/NayanVangala/argon4hack

Status key: ready = done and verified, in-progress = work underway or unproven, to-confirm = unknown field or open decision, do not fill with invented text.

No field below has been filled with invented submission-form wording. Where the exact form field is unknown, it is marked to-confirm.

## 1. Project description

Status: in-progress (draft text below is ready to paste once the team confirms it; final submission copy still to-confirm against the actual form).

Draft description (promises problem + whole-day Argon + verification loop):

> Scene is a glasses-based day-memory app. You make promises all day in conversation and forget half of them. Scene watches your day, Argon understands the whole day at once, and it makes sure you follow through on what you promised. The whole session is loaded into one 1M-token Argon context, with no retrieval step. A Critic checks understanding itself, quote verification is done by code where the LLM proposes and code disposes, failures go to needs_review, and nothing sends without a tap.

- [ ] Team confirms this description text before pasting.
- [ ] Description mentions only features built during the hackathon (see rule reminders below).

## 2. Google products used

- Argon Interactions, live: in-progress / proven in part.
  - Live Argon Ask proven (whole-session reasoning over a seeded session, with verbatim-quote receipts). Live analyzer over real frames and live transcription via a real video chunk test are still open, so do not describe Argon as fully proven end to end until those tests pass.
- Managed Agents wrapper: in-progress, NOT done.
  - Status flagged honestly: the Managed Agents wrapper is still open at time of writing. Do not list it as complete. If the form asks for Managed Agents use, describe only what is actually running at submission time, or mark it in-progress if the form allows it. Exact form wording for this field: to-confirm.
- Cloud SQL: in-progress, NOT provisioned.
  - Status flagged honestly: Cloud SQL Postgres was planned (Postgres 16, Cloud Run host, app-level Bearer auth) but nothing was provisioned at time of writing. The fallback cutoff in the plan was 6:30 PM: if cloud is not working end to end by then, abandon for LAN + SQLite. Do not list Cloud SQL as the running demo backend unless it is actually provisioned and connected at submission time. If the demo runs on LAN + SQLite, say so.
- Other Google products / fields: to-confirm. Do not invent additional product names beyond Argon, Managed Agents, and Cloud SQL as named in the brief.

## 3. Team

- Nayan: ready (team member).
- Isabella: ready (team member).
- Srijan: to-confirm, OPEN QUESTION, do not decide here.
  - Confirm member vs contributor status on the submission form before submitting. Srijan contributed work (including logo/app icon and parallel backend work), but whether he is listed as a team member or as a contributor on the form is unresolved in this brief. Flag it to the team, do not pick one side in this checklist.
- Team size limit in the brief: max 4. Confirm the submitted roster fits that limit: to-confirm at submission time.
- Other team-form fields (roles, contact details, etc.): to-confirm. Do not fill with invented text.

## 4. Repo

- Repo URL: https://github.com/NayanVangala/argon4hack
- Status: ready on the URL itself; final submission-time HEAD to-confirm (repo moves during the day; verify the pushed HEAD at submission time, do not copy an old commit hash here).
- [ ] Repo is public at submission time (required).
- [ ] Submission links the public repo URL above, not a private or local copy.

## 5. Demo video

- Spec: 60 seconds, uncut lens video. See VIDEO-SHOT-LIST.md.
- Status: in-progress. The shot list is ready; the recorded take itself is not yet confirmed done.
- [ ] One continuous 60-second take, no cuts or edits.
- [ ] Shows, in order: pin, timeline scroll, back, and a live scene appearing.
- [ ] If glasses fail, the fallback is stated on camera (seeded + chunk-upload demo for the live pitch; phone fallback for the video take), not hidden.

## 6. Pitch

- Spec: 3 minutes, no slides. See PITCH-SCRIPT.md.
- Status: ready (script written); delivery/rehearsal: to-confirm.
- [ ] Script rehearsed to 3:00 or under before the pitch slot.

## 7. Rule reminders (check all before submitting)

- [ ] Repo must be public.
- [ ] Demo must only highlight features built DURING the hackathon. Prior scaffolding (including OnRecord prior work) must be clearly distinguished, not presented as built today.
- [ ] Dashboard must not be the demo lead. Dashboard is backup only; the demo lead is glasses + phone + live Ask + follow-up approval.
- [ ] Avoid-list items are not the demo lead: no basic RAG app framing, no dashboard-as-main-feature, no image-analyzer framing, no education chatbot, no medical advice. Scene's framing is whole-day 1M-context Ask with no retrieval step.
- [ ] No invented rubric wording, prize amounts, or submission fields beyond the brief. Prizes in the brief: $20K total (1st $7,500 / 2nd $5,000 / 3rd $2,500 / Best use of Managed Agents $5,000). Rubric in the brief: live demo 50%, problem + usefulness 25%, originality 15%, pitch clarity 10%.

## 8. Fields unknown at time of writing (to-confirm, do not invent)

- Exact submission form field names, required vs optional flags, and character limits.
- Exact wording the form wants for Google products used, including whether in-progress items can be listed as in-progress.
- Team form structure for member vs contributor.
- Demo video upload method, file format, and size limits.
- Any organizer confirmation fields (for example age/ID checks, which were still unconfirmed in the brief).

## To-confirm list (summary)

1. Final project description copy as pasted into the actual form.
2. Managed Agents wrapper: final status at submission time (in-progress vs done).
3. Cloud SQL: final status at submission time (provisioned and running vs LAN + SQLite fallback).
4. Srijan: member vs contributor on the form.
5. Submitted roster fits the max-4 team limit.
6. Repo HEAD at submission time.
7. Demo video recorded take (60s uncut) completed.
8. Pitch rehearsed to 3:00 or under.
9. All exact submission form fields, formats, and limits.
10. Any organizer confirmation fields beyond the brief.
