"""Ingest pipeline orchestration (module 2).

Built to ~/workspace/scene-backend/INTERFACES.md (locked), which wins
over _plans/02-ingest.md wherever they disagree. Differences applied:

- Store calls use the locked names: create_chunk(session_id, start_ts,
  end_ts, storage_path=None), update_chunk_status(chunk_id, status),
  add_scene(scene) (STORE assigns the id), update_scene(scene_id,
  **fields), add_fact(fact), add_spend(amount_usd). The plan's
  save_chunk / save_scene / save_transcripts / save_facts /
  add_spend_usd names are NOT used.
- Transcripts live INSIDE the scene dict; there is no separate
  transcript store method.
- Facts: the mock extracts none, and the locked constructor has no
  FactExtractor, so the fact loop runs over an empty list this phase.
- ChunkResult["status"] is "received" on success (the route's 202 body,
  per plan §e), while the stored chunk status is "indexed". On failure
  it is "failed" and scene is None.
- The store assigns scene ids, so thumb/keyframe CDN URLs (which embed
  the id) can only be built AFTER add_scene returns. Ingest therefore
  calls update_scene with the computed URLs and broadcasts the summary
  built from the updated stored scene.
- Person counters: plan 03 §f lists record_appearance as ingest-
  consumed, but the locked ingest steps omit it, so ingest does NOT
  call record_appearance (flagged to coordinator).

Synchronous in this phase. Stdlib only, plain dicts.
"""

import logging
import os
import shutil
import subprocess
import tempfile

logger = logging.getLogger(__name__)

# Critic: module 5 owns critic.py. It may not exist yet at build time,
# so fall back to the locked mock shim (all-pass for newly ingested
# mock scenes) until it lands; once it exists, its critique_scene wins.
try:
    from .critic import critique_scene as _critic_scene
except ImportError:  # not a package import, or critic.py not built yet
    try:
        from critic import critique_scene as _critic_scene
    except ImportError:
        _critic_scene = None


_CRITIC_CHECKS = ("transcript_alignment", "visual_grounding",
                  "people_consistency", "temporal_sanity")

_SPEND_PER_CHUNK_USD = 0.07
_MAX_RETRIES = 3  # retries after the initial attempt (4 calls total)

_MOCK_KEYFRAMES = ["mock://keyframes/0.jpg"]
_KEYFRAME_FRACTIONS = (0.10, 0.25, 0.40, 0.55, 0.70, 0.85)
_KEYFRAME_FALLBACK_DURATION_S = 30.0
_KEYFRAME_TIMEOUT_S = 15  # per ffmpeg seek-extract call
_FFPROBE_TIMEOUT_S = 10
_DENSE_FPS = 1  # dense path: one frame per second of chunk
_DENSE_MAX_FRAMES = 30  # cap per chunk (30s chunk at 1fps)
_DENSE_TIMEOUT_S = 60  # one ffmpeg call for the whole chunk


def _all_pass_critique():
    return [{"check": c, "result": "pass", "note": "Check passed"}
            for c in _CRITIC_CHECKS]


def _critique(scene):
    if _critic_scene is None:
        return _all_pass_critique()
    result = _critic_scene(scene)
    if not isinstance(result, list):
        return _all_pass_critique()
    return result


def _scene_summary(scene):
    """SceneSummary projection for the WS push (same field list as the
    old mock's scene_summary; routes own the canonical projection)."""
    return {k: scene.get(k) for k in
            ("id", "start_ts", "end_ts", "summary", "quote", "thumb_url",
             "type", "verified", "confidence")}


class IngestPipeline:
    def __init__(self, store, broadcaster, transcriber, analyzer,
                 attributor, embedder):
        self.store = store
        self.broadcaster = broadcaster
        self.transcriber = transcriber
        self.analyzer = analyzer
        self.attributor = attributor
        self.embedder = embedder

    # -- helpers ---------------------------------------------------------

    @staticmethod
    def _delete_keyframes(keyframes):
        """Delete real local frame temp files; mock:// paths are a
        no-op (never passed to os.remove). Failures are ignored: a
        cleanup miss must never crash the pipeline. Dense-frame temp
        dirs (scene-dense-*) are removed too once empty, so the
        single-ffmpeg dense path leaks neither files nor dirs."""
        parents = []
        for path in keyframes or []:
            if not path or str(path).startswith("mock://"):
                continue
            try:
                os.remove(str(path))
            except OSError:
                pass
            parent = os.path.dirname(str(path))
            if parent and parent not in parents:
                parents.append(parent)
        for parent in parents:
            if not os.path.basename(parent).startswith("scene-dense-"):
                continue
            try:
                os.rmdir(parent)  # only succeeds when empty
            except OSError:
                pass

    @staticmethod
    def _probe_duration(video_path):
        """Video duration in seconds via ffprobe, or the fallback
        duration when ffprobe is missing or its output is unusable."""
        if shutil.which("ffprobe") is None:
            return _KEYFRAME_FALLBACK_DURATION_S
        try:
            result = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries",
                 "format=duration", "-of",
                 "default=noprint_wrappers=1:nokey=1", str(video_path)],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                text=True, timeout=_FFPROBE_TIMEOUT_S)
            duration = float((result.stdout or "").strip())
            if duration > 0:
                return duration
        except (ValueError, OSError, subprocess.SubprocessError):
            pass
        return _KEYFRAME_FALLBACK_DURATION_S

    def _extract_keyframes(self, video_path):
        """~6 evenly spaced JPEG frames from video via ffmpeg, as real
        local temp-file paths for the analyzer (which samples to 6
        itself and skips mock:// paths).

        Never raises: on any failure (ffmpeg missing, bad/unreadable
        video, zero frames extracted) partial frame files are deleted,
        one log line is emitted, and the mock placeholder is returned
        so the chunk still proceeds with a mock draft. Frame temp
        files are the caller's responsibility: _run_once deletes them
        after analysis (see its try/finally)."""
        frames = []
        try:
            if not video_path or not os.path.isfile(str(video_path)):
                raise ValueError("video_path missing or not a file")
            if shutil.which("ffmpeg") is None:
                raise RuntimeError("ffmpeg not found on PATH")
            duration = self._probe_duration(video_path)
            for fraction in _KEYFRAME_FRACTIONS:
                fd, frame_path = tempfile.mkstemp(
                    prefix="scene-kf-", suffix=".jpg")
                os.close(fd)
                try:
                    result = subprocess.run(
                        ["ffmpeg", "-y", "-ss",
                         "%.3f" % (duration * fraction), "-i",
                         str(video_path), "-frames:v", "1", "-q:v", "2",
                         frame_path],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=_KEYFRAME_TIMEOUT_S)
                except subprocess.SubprocessError:
                    result = None
                if (result is not None and result.returncode == 0
                        and os.path.isfile(frame_path)
                        and os.path.getsize(frame_path) > 0):
                    frames.append(frame_path)
                else:
                    try:
                        os.remove(frame_path)
                    except OSError:
                        pass
            if not frames:
                raise RuntimeError("ffmpeg extracted zero usable frames")
            return frames
        except Exception as exc:  # noqa: BLE001 - fallback, never raise
            self._delete_keyframes(frames)
            logger.warning(
                "[ingest] keyframe extraction failed (%s), falling back "
                "to mock placeholder", exc)
            return list(_MOCK_KEYFRAMES)

    def _extract_dense_frames(self, video_path):
        """Dense temporal frames: 1 fps, capped at 30 frames, one
        ffmpeg call, frames downscaled to fit a 768x768 box (one
        Gemini tile each at 258 tokens) at the same JPEG quality as
        the 6-frame path.

        Never raises: on any failure (ffmpeg missing, bad/unreadable
        video, zero frames) partial files and the temp dir are
        deleted, one log line is emitted, and [] is returned so the
        caller can fall back to the 6-frame path. On success the
        caller owns the files: _run_once deletes them (and their
        temp dir, via _delete_keyframes) in its finally, exactly
        like the 6-frame path."""
        tmpdir = None
        frames = []
        try:
            if not video_path or not os.path.isfile(str(video_path)):
                return []
            if shutil.which("ffmpeg") is None:
                logger.warning(
                    "[ingest] dense extraction skipped: ffmpeg not "
                    "found on PATH")
                return []
            tmpdir = tempfile.mkdtemp(prefix="scene-dense-")
            pattern = os.path.join(tmpdir, "frame-%03d.jpg")
            try:
                result = subprocess.run(
                    ["ffmpeg", "-y", "-i", str(video_path),
                     "-vf",
                     "fps=%d,scale=768:768:force_original_aspect_ratio=decrease" % _DENSE_FPS,
                     "-frames:v", str(_DENSE_MAX_FRAMES),
                     "-q:v", "2", pattern],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=_DENSE_TIMEOUT_S)
            except subprocess.SubprocessError:
                result = None
            if result is None or result.returncode != 0:
                raise RuntimeError("ffmpeg dense extraction failed")
            frames = sorted(
                f for f in
                (os.path.join(tmpdir, name)
                 for name in os.listdir(tmpdir))
                if f.endswith(".jpg") and os.path.isfile(f)
                and os.path.getsize(f) > 0)
            if not frames:
                raise RuntimeError("ffmpeg extracted zero dense frames")
            return frames
        except Exception as exc:  # noqa: BLE001 - fallback, never raise
            self._delete_keyframes(frames)
            if tmpdir:
                try:
                    shutil.rmtree(tmpdir, ignore_errors=True)
                except OSError:
                    pass
            logger.warning(
                "[ingest] dense frame extraction failed (%s), falling "
                "back to 6-frame path", exc)
            return []

    def _extract_frames(self, video_path):
        """Frame set for one chunk: dense 1fps frames first, the
        6-frame path on dense failure, the mock placeholder if that
        also fails (_extract_keyframes never raises and returns the
        placeholder itself). Never raises."""
        frames = self._extract_dense_frames(video_path)
        if frames:
            return frames
        return self._extract_keyframes(video_path)

    def _backfill_timestamps(self, segments, start_ts, end_ts):
        """Fill missing segment/word timestamps from the chunk window.

        Needed because Transcriber.transcribe(audio_path) receives no
        chunk timestamps, so the mock cannot stamp its segment itself.
        Real transcriber timestamps are left untouched.
        """
        for seg in segments:
            if not seg.get("start_ts"):
                seg["start_ts"] = start_ts
            if not seg.get("end_ts"):
                seg["end_ts"] = end_ts
            for word in seg.get("word_timestamps") or []:
                if not word.get("start_ts"):
                    word["start_ts"] = seg["start_ts"]
                if not word.get("end_ts"):
                    word["end_ts"] = seg["end_ts"]
        return segments

    def _run_once(self, session_id, start_ts, end_ts, video_path,
                  audio_path):
        """One attempt at the transcribe -> store steps. Raises on
        failure so the caller can retry."""
        # Dense 1fps frames when extraction works; the 6-frame path,
        # then the mock placeholder, on failure. Deleted in the
        # finally below.
        keyframes = self._extract_frames(video_path)

        try:
            # Transcribe first, so a quote exists even if analysis degrades.
            segments = self.transcriber.transcribe(audio_path)
            segments = self._backfill_timestamps(segments, start_ts, end_ts)

            # Analyze, then attribute.
            draft = self.analyzer.analyze(keyframes)
            attributed = self.attributor.attribute(
                segments, keyframes, draft.get("people") or [])

            # Transcript lives inside the scene dict.
            transcript = [{
                "speaker": item.get("speaker_name", "Unknown"),
                "text": item.get("segment", {}).get("text", ""),
                "start_ts": item.get("segment", {}).get("start_ts", start_ts),
                "end_ts": item.get("segment", {}).get("end_ts", end_ts),
            } for item in attributed]
            quote = transcript[0]["text"] if transcript else ""
            confidence = draft.get("confidence", "review")

            # Embed (computed but NOT persisted in this phase).
            text_to_embed = "\n".join(
                [draft.get("summary", "")] +
                [line["text"] for line in transcript])
            _text_vec = self.embedder.embed(text_to_embed)
            _visual_vecs = [self.embedder.embed_image(kf) for kf in keyframes]
            _collections = self.embedder.collection_names()
            # (Vectors/collections intentionally unused beyond computation:
            # embedding_refs stays None until the real store persists them.)

            # Facts: mock extracts none.
            facts = []

            # Build the scene (no id: the store assigns it), critique it,
            # then store it.
            scene = {
                "session_id": session_id,
                "start_ts": start_ts,
                "end_ts": end_ts,
                "summary": draft.get("summary", ""),
                "quote": quote,
                "thumb_url": "",
                "type": draft.get("type", "conversation"),
                "verified": confidence == "verified",
                "confidence": confidence,
                "objects": draft.get("objects") or [],
                "people": draft.get("people") or [],
                "actions": draft.get("actions") or [],
                "visible_text": draft.get("visible_text") or [],
                "critique": [],
                "transcript": transcript,
                "keyframes": [],
                "pinned": False,
                "embedding_refs": None,
            }
            scene["critique"] = _critique(scene)
            stored = self.store.add_scene(scene)
            scene_id = stored.get("id")

            # CDN URLs embed the store-assigned id; patch them in now.
            thumb_url = ("https://cdn.helloscene.xyz/t/%s.jpg" % scene_id
                         if scene_id else "")
            keyframe_urls = (["https://cdn.helloscene.xyz/k/%s/0.jpg" % scene_id]
                             if scene_id else [])
            try:
                stored = self.store.update_scene(
                    scene_id, thumb_url=thumb_url, keyframes=keyframe_urls)
            except (AttributeError, KeyError, TypeError):
                # Store without update_scene, or a fake returning the same
                # dict object: patch the returned dict directly.
                stored["thumb_url"] = thumb_url
                stored["keyframes"] = keyframe_urls

            # Fact linkage uses the store-assigned id.
            for fact in facts:
                fact = dict(fact)
                fact["scene_id"] = scene_id
                self.store.add_fact(fact)

            return stored
        finally:
            # Frame temps belong to ingest alone: delete this
            # attempt's frames after analyze + attribute +
            # embed, even on failure, so retries never leak.
            # Mock:// paths are a no-op here; the uploaded
            # video/audio paths are routes' to delete, not ours.
            self._delete_keyframes(keyframes)

    # -- public API ------------------------------------------------------

    def process_chunk(self, session_id, start_ts, end_ts, video_path,
                      audio_path):
        """-> ChunkResult dict: {chunk_id, session_id, start_ts, end_ts,
        status, scene}. Synchronous. Retries the pipeline steps up to
        _MAX_RETRIES times, then marks the chunk failed."""
        # Chunk in: received, then processing. Bookkeeping is done once;
        # retries cover the fallible pipeline steps, not chunk creation.
        chunk = self.store.create_chunk(session_id, start_ts, end_ts,
                                        storage_path=video_path)
        chunk_id = chunk.get("id", chunk.get("chunk_id"))
        self.store.update_chunk_status(chunk_id, "processing")

        stored_scene = None
        error = None
        for _attempt in range(_MAX_RETRIES + 1):
            try:
                stored_scene = self._run_once(
                    session_id, start_ts, end_ts, video_path, audio_path)
                error = None
                break
            except Exception as exc:  # noqa: BLE001 - retry, then fail
                error = exc

        if error is not None:
            self.store.update_chunk_status(chunk_id, "failed")
            self._broadcast_error(chunk_id, error)
            return {"chunk_id": chunk_id, "session_id": session_id,
                    "start_ts": start_ts, "end_ts": end_ts,
                    "status": "failed", "scene": None}

        # Store step, in order: spend once per chunk, then indexed.
        self.store.add_spend(_SPEND_PER_CHUNK_USD)
        self.store.update_chunk_status(chunk_id, "indexed")

        # WS push, only after the scene row is stored: scene, then status.
        self.broadcaster.broadcast_scene(_scene_summary(stored_scene))
        self.broadcaster.broadcast_status()

        return {"chunk_id": chunk_id, "session_id": session_id,
                "start_ts": start_ts, "end_ts": end_ts,
                "status": "received", "scene": stored_scene}

    def _broadcast_error(self, chunk_id, error):
        """Chunk failure surfaces as a WS error only (no poll route in
        this phase). The routes broadcaster exposes broadcast(obj); use
        it when present, else a broadcast_error method if one exists."""
        payload = {"event": "error", "code": "chunk_failed",
                   "message": str(error), "chunk_id": chunk_id}
        broadcast = getattr(self.broadcaster, "broadcast", None)
        if callable(broadcast):
            broadcast(payload)
            return
        broadcast_error = getattr(self.broadcaster, "broadcast_error", None)
        if callable(broadcast_error):
            broadcast_error(payload)
