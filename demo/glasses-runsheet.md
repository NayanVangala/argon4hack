# Scene glasses run sheet (one page, follow in order)

Current state assumed: backend already up on Nayan's Mac, Isabella's phone already connected via LAN, live Argon Ask already proven. This sheet covers ONLY the glasses + band track. Glasses pair to the demo phone, never to the Mac. No keys in this sheet; fill placeholders live.
Backend LAN (last known, re-verify live): `http://10.1.63.33:8000` (Mac: `ipconfig getifaddr en0`).

## 0. Preconditions (do not skip)
- [ ] Demo phone DECIDED: Isabella's phone. Glasses pair to that phone (Meta AI app + SceneBridge on that phone), not the Mac.
- [ ] Demo phone + Mac on the SAME venue Wi-Fi for the whole demo. A phone on cellular cannot reach the Mac LAN address. If the phone changes, redo phone setup from scratch; Developer settings live on the phone, not in the repo.
- [ ] Phone set so it does not auto-lock mid-demo (Settings > Display > Auto-Lock > Never, or keep it on charge with screen on). If it locks mid-stream, unlock and check the preview; if frames do not resume, stop, wait, restart at step 4.
- [ ] Band charger packed. No charger, no band in the demo.

## 1. Meta AI Developer Mode ritual (demo phone, Meta AI app, before registering)
- [ ] Open Meta AI. If Developer Mode is not already enabled, enable it with 7 taps on the Developer Mode entry (same entry, 7 times in a row).
- [ ] Toggle Developer Mode OFF, then back ON.
- [ ] If an Install prompt/button is shown, tap Install.
- [ ] Leave and re-enter the screen; confirm the toggle stays ON.
- [ ] Toggle does NOT appear at all: force-quit Meta AI completely (swipe away from app switcher), reopen, retry the 7 taps. Do not keep tapping a screen that never shows the toggle.
- [ ] Toggle flips itself back OFF: repeat OFF then ON once. If it still will not stay ON, STOP and escalate. Do not proceed to registration.
- [ ] NEVER toggle Dev Mode OFF as a reset. OFF then ON above is the ritual, not a reset step.

## 2. Glasses WITHOUT the band first
- [ ] Band powered OFF or out of range when registering or updating registration. Pair and register glasses alone.
- [ ] If registration fails or the device list shows the wrong device while the band is connected: disconnect band, force-quit Meta AI, redo registration with glasses only. Do not debug a glasses problem while the band is attached.

## 3. Force-quit Meta AI before the bridge
- [ ] After registration, force-quit Meta AI completely (swipe away) BEFORE opening SceneBridge.
- [ ] Why: Meta AI and the bridge fight over the same Bluetooth channel. This is the single most likely cause of a device that registered fine but never appears in the bridge.
- [ ] If bridge shows "No glasses found yet" or stream never starts, check first whether Meta AI relaunched in the background; force-quit again and retry.

## 4. Bridge order (SceneBridge, exact order, do not reorder)
- [ ] Launch SceneBridge on the demo phone.
- [ ] Tap "Register glasses". Wait for registration state to change from Unknown to a registered state. Complete any Meta AI callback that appears.
- [ ] Grant camera permission: tap "Request" if needed, then "Check" until it reads granted. Devices appear ONLY after registration AND camera permission are both done.
- [ ] Camera denied: iOS will not re-prompt on a second tap. Go to phone Settings for SceneBridge, grant Camera there, return, tap "Check".
- [ ] Wait for glasses in the "Glasses" list. Tap the glasses entry to open the Live screen.
- [ ] Tap "Start stream". Behind it the code runs, in order: createSession, session start, wait up to 10s for started state, addCamera with stream config, then stream start. Subscriptions to video, audio, state attach BEFORE stream start.
- [ ] Success: "Start stream" flips to "Stop stream", stream state moves off Idle.
- [ ] Fail "Session did not reach started state in 10s" or "addCamera returned nil": stop, count to 3 (see step 6), tap "Start stream" again. If it fails twice with the same error, go to step 8 ladder rung 1.

## 5. Frame proof (the only proof that counts)
- [ ] Watch the Live preview area, NOT just the state line.
- [ ] PASS: black preview box fills with a LIVE camera image (frame callback firing).
- [ ] FAIL: state says streaming but preview still reads "No frame yet" after 10s. This is NOT streaming. Do NOT start recording: recording with no frames makes empty 30s windows that upload nothing useful. Stop, wait (step 6), retry.
- [ ] Frames arrive but freeze: stop and restart the stream. A frozen frame is a stale callback, not live.

## 6. Backend session + Record, teardown gap, retry cap
- [ ] ONLY after the stream is running: tap "Start session" (backend session), then "Record" to begin 30s chunking. Recording is disabled in the UI until the stream runs; do not fight that gate. Stream first, record second.
- [ ] During the demo: one continuous session. Do NOT tap Stop/Start between chunks, and do NOT end/restart the backend session to "refresh" it. The 30s windows roll inside the same stream and session. End the session only when the demo beat is done.
- [ ] Teardown gap: after "Stop stream", count to 3 before "Start stream" again. Code enforces at least 2.0s since last stop before createSession, or glasses may refuse with sessionAlreadyExists. Do NOT force-quit/relaunch the bridge to "speed up" a restart; impatience breaks it.
- [ ] Retry cap: at most 3 stream-start attempts total, with the gap between each. After the 3rd failure, STOP retrying and work the step 8 ladder. Looping past 3 hides a stuck broadcast.

## 7. Band ONLY after glasses work (steps 4-5 pass with glasses alone)
- [ ] Bring the charger (see step 0). Check LED before pairing: green solid = over 80%, good to demo; orange solid = 20-80%, usable, charge if time before the slot; blinking orange = under 20%, charge first, do NOT demo on it. No low-battery workaround.
- [ ] Power band on, connect it to the glasses setup.
- [ ] Band gestures reach Scene Lens as ArrowKeys + Enter. Test EACH gesture once against the lens before the demo run and confirm the lens responds to each (pinch, swipe, tap as mapped).
- [ ] A gesture does nothing: re-check the glasses stream is still live (step 5) before blaming the band. If glasses work and one gesture still does nothing, DROP that gesture from the script and use the phone fallback for that action. Do not debug band gestures live in front of judges.

## 8. Firmware 129 warnings (apply with or without the band)
- [ ] WARNING 1, Back tap ends the session: a band Back tap can END a session despite consumeBack; the guard does not reliably stop it on firmware 129. NEVER make Back the only navigation path. Every screen/demo beat Back can reach must also be reachable another way (forward gesture, tap, or phone). Rehearse with Back disabled in your head; if any step strands you, rewrite it before the demo.
- [ ] WARNING 2, zero frames, open issue, NO workaround: stream can report streaming state while no frame callback ever fires (step 5). Test frame delivery EARLY: before judges, before full rehearsal, before anything depends on it. If the first stream test of the day shows state but no frames, retrying the same steps in the same order is NOT a fix; work the step 9 ladder and re-test frame delivery after each rung. If frames never arrive, live glasses video is out; decide early, not on stage.

## 9. Stuck-broadcast recovery ladder (in order, stop at first rung that fixes it, re-test step 5 after each rung)
- [ ] Rung 1, Meta AI Stop/End: open Meta AI, find the live broadcast/session, tap Stop or End. If no Stop/End button is visible, go to rung 2.
- [ ] Rung 2, hold glasses capture button 8-10s: press and hold a full 8-10s, release. Success = glasses stop broadcasting (LED/app state confirms idle). If still broadcasting, rung 3.
- [ ] Rung 3, glasses in case, lid closed, 30-60s: put glasses in case, close lid, wait a FULL 30-60s. Do NOT open early to peek. On reopening, glasses should be idle and visible fresh in the bridge. If still stuck after a full minute, rung 4.
- [ ] Rung 4, force-quit Meta AI + Bluetooth toggle: force-quit Meta AI completely, toggle phone Bluetooth OFF, wait a few seconds, toggle back ON. Retry the bridge. If still cannot connect, rung 5.
- [ ] Rung 5, forget device + re-register, LAST RESORT ONLY: in phone Bluetooth settings AND in Meta AI, forget the glasses. Then redo from step 1 (Dev Mode check) through step 4 (register, camera, device, session, start, camera), band disconnected per step 2. Cost: wipes the pairing, costs the most time, never first. If even a clean re-register fails, the problem is not a stuck broadcast; escalate instead of looping the ladder.

## 10. Done looks like this
- [ ] Dev Mode ON and stable; glasses registered alone; Meta AI force-quit; bridge shows registered + camera granted + glasses in list.
- [ ] "Start stream" flipped to "Stop stream" AND preview shows a live moving image (not "No frame yet").
- [ ] Backend session started, Record on, 30s windows rolling in one continuous stream/session.
- [ ] Band (if used): LED green/orange solid, every demo gesture confirmed against the lens, plus a non-Back path for every beat.
- [ ] End state: stream stopped cleanly, session ended, glasses idle, Meta AI still force-quit until the next run, band charger packed.
- [ ] NEXT RUN restarts at step 3 (force-quit Meta AI before the bridge), NOT at step 0, unless the demo phone changed. If the phone changed, restart at step 0.

## 11. Fallback: 30-minute rule
- [ ] If glasses fight for MORE than 30 minutes, STOP the glasses track. Fall back to seeded + chunk-upload testing (seeded scenes/Ask/follow-ups already proven, plus real chunk upload) for the demo. Do not burn the demo slot on a pairing fight, and do not discover the zero-frames issue on stage.
