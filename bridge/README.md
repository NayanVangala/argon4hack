# Scene iOS Bridge (built 2026-10-25, hackathon day)

Fresh scaffold for Scene. Streams Ray-Ban Meta glasses camera+mic through the
official Meta Wearables DAT iOS SDK and uploads 30-second chunks to the Scene
backend. Written today for the Gemini 4 Argon hackathon; the older OnRecord
bridge was used only as a pattern reference, no files were copied from it.

## App flow

Launch -> `Wearables.configure()` once -> registration state -> device list ->
connect -> live camera preview (`StreamView`) -> Record -> 30s windows ->
multipart `POST /chunks` -> session end. Failed uploads buffer to disk and
flush on the next launch / session start.

## Setup

1. **Xcode**: open `SceneBridge.xcodeproj`. First open resolves the Swift
   Package. If it does not, use File > Add Package Dependencies with
   `https://github.com/facebook/meta-wearables-dat-ios` and link
   `MWDATCore`, `MWDATCamera`, `MWDATMockDevice` (already in the project).
2. **Signing**: pick your Development Team in Signing & Capabilities.
   Bundle ID is `com.scene.bridge`; change it if it collides.
3. **Meta App ID**: in `SceneBridge/Info.plist`, replace `YOUR_META_APP_ID`
   in the `MWDAT` dict with your Wearables Developer Center app ID.
4. **Backend**: in `SceneBridge/Config.swift`, set `baseURL` to the deployed
   backend and paste a dev Bearer token. Never commit a real token.
5. **Meta AI app**: enable Developer Mode in the Meta AI app, register the
   app there, and **force-quit the Meta AI app before running the bridge**.
   The Meta AI app and the bridge fight over the same Bluetooth channel.
6. **Run on a real device.** Bluetooth + glasses streaming does not work in
   the simulator. For no-hardware testing, wire `MWDATMockDevice` (linked
   but unused in this scaffold) per the DAT MockDeviceKit docs.
7. **Build**: `xcodebuild -scheme SceneBridge -destination 'generic/platform=iOS'`
   or just Run in Xcode. Fix every `// VERIFY` item the compiler flags first;
   they are the only guessed API surfaces.

## VERIFY list (unconfirmed API details — check against the DAT sample)

- `StreamSession` initializer + `StreamSessionConfig` members (codec,
  resolution, framerate) in `StreamViewModel`. Pattern confirmed from the
  CameraAccess sample; exact member names were not visible verbatim.
- Audio frame publisher name in `MWDATCamera`. The DAT README confirms PCM
  audio arrives through the Camera Stream; `ingestAudioPCM(_:)` is ready to
  connect once the publisher name is confirmed.
- DAT PCM sample rate / channel count in `ChunkWriter` (scaffold: 16kHz mono).
- Whether `StreamSession` needs the `createSession` device session or manages
  its own link (see `WearablesViewModel.startDeviceSession`).
- Exact `MWDAT` plist key name for the Meta App ID, DAT Bonjour service
  types, and the Meta AI callback URL scheme (placeholders in Info.plist).
- SPM minimum version pin (scaffold: 1.0.0, up to next major). Pick the
  latest release in Xcode if that fails to resolve.
- If the camera stream dies at ~30s: the DAT camera path has historically
  needed SoftAP Wi-Fi entitlements (`com.apple.developer.networking.wifi-info`
  + HotspotConfiguration) on top of Bluetooth. Add them if you see that failure.

## Known scaffold gaps (finish in this order)

1. Resolve all `// VERIFY` items against the CameraAccess sample.
2. Connect the real audio publisher to `ingestAudioPCM`.
3. Re-associate buffered chunks saved before a session existed
   (`PendingUploadStore` "unassigned" items) instead of uploading them raw.
4. Replace the pasted dev token with QR-pairing token provisioning.
5. Add a LaunchScreen storyboard (the plist references one; Xcode generates
   a default, but add a real one before demo).

## API contract

`../goals/gemini-4-argon-hackathon/files/scene-final-spec/SCENE-API-CONTRACT.md`
in the workspace (paths and shapes are frozen; mocks must match field-for-field).
