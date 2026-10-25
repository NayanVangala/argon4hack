# Scene Fallback Plan: LAN + SQLite Demo

**Workflow:** scene-cloudsql-deploy (worker 6, fallback planner)
**Purpose:** If the Cloud SQL + Cloud Run deploy stalls, the demo still runs. The Mac backend with SQLite over venue LAN is a full demo, not a degraded one.
**Rule:** Do not touch the Cloud SQL attempt until the cutoff in §5. This plan is pre-written so switching costs minutes, not a re-decision.

## 0. What is already true (no setup needed)

- The backend that actually runs lives on Nayan's Mac at `~/scene-backend/`. That is the copy to use. Do not use the workspace copy at `~/workspace/scene-backend/` for the live demo.
- Default store is SQLite: `scene.db` next to `server.py`. It seeds demo data only when empty, so restarting does not wipe a seeded day.
- Default port is 8000.
- The phone app and the lens already know how to reach a LAN backend. Nothing needs to be rebuilt for fallback, only re-pointed.

## 1. Fallback steps, in order

Do these in order. Stop at the first step that fails and fix it before moving on.

### Step 1. Confirm the Mac server is running (SQLite, port 8000)

On the Mac, in a terminal:

```bash
cd ~/scene-backend && python3 server.py
```

Confirm it stays up and is listening on port 8000. If the port is already taken by a stale server, do the kill/restart in §2 first, then run this.

Do not set any store override for fallback. The SQLite default is the fallback. If a previous terminal exported a Cloud SQL / Postgres store variable, start a fresh terminal so the default applies.

### Step 2. Get the current LAN IP

On the Mac:

```bash
ipconfig getifaddr en0
```

That output is the Mac's current LAN address. Build the API base URL from it:

```
http://<LAN-IP>:8000/api/v1
```

Example only (from earlier today, may already be stale): `http://10.1.63.33:8000/api/v1`, WebSocket `ws://10.1.63.33:8000/api/v1/live`. Never reuse the example blindly. Always use the fresh `ipconfig` output.

### Step 3. Point the phone app at the Mac

1. Open the phone app.
2. Set the base URL field to the fresh LAN base URL from Step 2.
3. Turn the mock-mode toggle OFF. This is the most common silent failure: with mock on, the app looks fine but never talks to the real backend.
4. Reload / reopen the sessions view and confirm real sessions appear (not mock data).

### Step 4. Point the lens at the Mac

Set the lens URL params to the fresh LAN backend:

- `?api=` to the LAN base URL (same value as the phone app, e.g. `http://<LAN-IP>:8000/api/v1`)
- `?token=` to the session token, if the lens flow requires one (same token flow as the LAN setup used earlier today; fallback changes the host, not the auth flow)

Reload the lens page after changing params.

### Step 5. Verify with two calls

Do both, in this order, before declaring fallback ready:

1. **Status call:** Hit the backend status/health endpoint at the LAN base URL and confirm it answers. If it does not answer, the clients are pointed at the wrong IP or the server is not up. Go back to Steps 1-2.
2. **Ask call:** Ask one real question over a seeded session (a whole-session reasoning question, the demo's core path) and confirm a real answer comes back with verbatim-quote receipts and scene sources. If Ask answers from mock data or errors, check the phone app mock toggle (Step 3) and that `GEMINI_API_KEY` is exported in the server terminal (§2).

Fallback is ready only when both calls pass. A status pass alone is not enough.

## 2. Kill / restart procedure and the API key gotcha

### Kill and restart

If the server is stale, hung, or on the wrong store, kill it by port and rerun:

```bash
lsof -ti:8000 | xargs kill
cd ~/scene-backend && python3 server.py
```

If `lsof` returns nothing, nothing was listening; just run the server command.

Restarting the server does NOT require restarting the phone app or the lens, as long as the LAN IP has not changed. Clients reconnect to the same base URL. Restarting does NOT wipe SQLite data: the seed only fills an empty database.

### GEMINI_API_KEY re-export gotcha (read this before every restart)

`GEMINI_API_KEY` is exported per terminal on the Mac. A new terminal does not inherit it. Every time the server is started in a new terminal, re-export the key in that terminal before running `server.py`, or Ask and the analyzer will fail even though status looks healthy.

Checklist for every server start:

1. New terminal? Re-export the key first.
2. Then `cd ~/scene-backend && python3 server.py`.
3. Then run the Ask verification call in §1 Step 5. If Ask fails but status passes, the missing key export is the first suspect.

No key value is written in this plan, and none should be added. Keep the key in the terminal only.

## 3. If the LAN IP changes mid-demo

Venue Wi-Fi can reassign the Mac's address. This is expected, not a disaster. Fix it in this order and restart nothing else:

1. On the Mac, re-run:
   ```bash
   ipconfig getifaddr en0
   ```
2. Update the phone app base URL field to the new `http://<NEW-LAN-IP>:8000/api/v1`.
3. Update the lens `?api=` param to the new base URL and reload the lens page.
4. Re-run the two verification calls from §1 Step 5 (status, then Ask).
5. Restart nothing else. Do NOT restart the Mac server for an IP change alone: the server is already listening on the new address, and a restart risks losing nothing but wastes demo time and re-triggers the key re-export step.

Prevention, if there is a spare minute before the demo: keep the Mac awake, keep it on the same venue network, and do not switch networks mid-demo. Do not chase a static IP unless venue staff offers one; the re-point procedure above is faster than network surgery during judging.

## 4. Second fallback: cloudflared tunnel (only if LAN itself fails)

Use this only if LAN itself fails (phone/lens cannot reach the Mac on the LAN at all, e.g. client isolation on venue Wi-Fi). Do not reach for it for a mere IP change; §3 handles that.

### Install note

`cloudflared` is NOT installed on the Mac as of this writing. Install it first (official Cloudflare install for macOS; Homebrew is the usual route if Homebrew is present). This is the only install step in the fallback chain, and it is the reason this is second, not first.

### Run command shape

From a Mac terminal, with the backend already running on port 8000:

```bash
cloudflared tunnel --url http://localhost:8000
```

That prints a public `https://<something>.trycloudflare.com` URL. That public URL is the new base. Append the API path the same way as the LAN base (the `/api/v1` suffix and the WS path follow the same shape, now over the tunnel host).

### URL swap in clients

1. Phone app: replace the base URL field with the tunnel URL's API base. Mock toggle stays OFF.
2. Lens: replace the `?api=` param with the tunnel URL's API base, keep `?token=` as before, reload.
3. Re-run the two verification calls from §1 Step 5 (status, then Ask) against the tunnel URL.
4. Keep the tunnel terminal open for the whole demo. Closing it kills public access instantly, while the LAN backend keeps running underneath.

Note the tradeoff: the tunnel fixes client isolation, but it adds a dependency (the tunnel process and Cloudflare's edge) on top of the LAN backend. If LAN works, skip it.

## 5. Decision rule: when to abandon Cloud SQL

**Feature freeze: 7:30pm.**

**Cutoff: abandon the Cloud SQL attempt and go LAN if the cloud deploy is not working end to end by 6:30pm (one hour before freeze).**

"Working end to end" means all of: cloud backend reachable at its public URL, phone app pointed at it with mock OFF, lens pointed at it, and both verification calls (status + a real Ask with receipts) passing through the cloud URL. Anything less at 6:30pm is not working.

**Who makes the call:** Nayan makes it. He is the one at the venue with the Mac, the phone, and the judges' clock. Anyone on the team can flag that the cutoff is approaching, but the switch decision is his, and once he calls it, the team executes §1 immediately with no further debate about reviving cloud.

**Why 6:30pm:** Switching to LAN takes minutes if this plan is followed, but the team needs the remaining hour for a full demo rehearsal on the fallback path (both verification calls, a lens pass, a follow-through pass) plus buffer for one IP change or one server restart. Cutting over later than 6:30pm trades rehearsal time for cloud hope.

**Earlier is fine:** If Cloud SQL is clearly blocked (not just slow) well before 6:30pm, Nayan can call the switch early. The cutoff is a latest time, not an earliest time. What is not allowed is drifting past 6:30pm on a half-working cloud deploy.

**After the call:** Stop all Cloud SQL work. No parallel "one more try" while the demo rehearsal runs. Cloud can be revisited only after the demo is rehearsed and passing on LAN, and only if Nayan says so.

## 6. What the demo loses and does NOT lose on fallback

### Loses

- **No public URL.** Judges and anyone off the venue network cannot open the backend directly. The demo must be shown on the venue LAN devices (phone + lens on the same network as the Mac).
- **LAN fragility.** The demo depends on venue Wi-Fi: IP changes (§3), client isolation (the §4 trigger), and the Mac staying awake and on-network. All three have a written fix above, but all three are risks the cloud deploy would have removed.
- **No cloud resilience.** If the Mac sleeps, crashes, or leaves the network, the demo backend goes with it. There is no remote copy serving traffic.

### Does NOT lose

Everything that is actually judged still works, because none of it depends on where the server runs:

- **Scenes:** real sessions, real scenes, real transcripts and keyframes served from SQLite.
- **Ask:** whole-session Argon reasoning over the full session context, with verbatim-quote receipts and scene sources, exactly as on cloud. (Subject to the key re-export in §2.)
- **Follow-Through Agent:** promise finding, quote verification, and approve/edit/dismiss flow unchanged; nothing sends without a tap, same as the cloud path.
- **The Critic:** per-scene and per-answer checks, contradiction and open-loop scans, and the fix/downgrade routing unchanged.
- **Demo story:** the 1M-context Argon overload pitch, the live demo rubric weight (real inputs, real verification loop), and the "built today" framing are all intact. The host changing from cloud to LAN is not a feature change and should not be presented as one to judges unless asked.

Bottom line: fallback is not a lesser demo. It is the same demo on a shorter wire.
