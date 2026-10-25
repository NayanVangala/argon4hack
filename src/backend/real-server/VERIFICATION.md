# Verification log (Oct 25, 2026)

- Automated: `pytest -q` -> 30 passed (fake model transport; tests server logic, not model accuracy).
- Live, local (127.0.0.1, real `gemini-4-argon` with the event API key):
  - Pasted 8-line staged transcript (deck 3 PM corrected to 2 PM, 20-minute check-in with Maya tomorrow 10 AM, budget by Friday 5 PM under $500).
  - Argon returned exactly 3 commitments for Nayan: email (deck, due 2 PM today, corrected deadline applied), calendar (20 minutes, Oct 26 10:00 AM), to-do (budget, Oct 30 5 PM).
  - Approving the to-do saved it on the server; calendar approval produced a Google Calendar form link (20-minute slot); email approval was blocked until a real recipient address was entered, then produced a Gmail compose link. Nothing was sent or saved in Google.
  - Ask returned literal transcript quotes as sources.
- Not tested: video/audio upload against Argon, the iPhone app or bridge against this server, any hosted deployment.
