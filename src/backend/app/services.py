"""Service interfaces + deterministic mock implementations (module 2).

Built to ~/workspace/scene-backend/INTERFACES.md (locked). Plain dicts,
stdlib only, no SDK types. Real implementations swap in behind these
same interfaces; call sites never change.
"""

import hashlib

# ---------------------------------------------------------------------------
# Interfaces
# ---------------------------------------------------------------------------


class Transcriber:
    """Transcribe audio into segments with word timestamps + diarization."""

    def transcribe(self, audio_path):
        """-> list[Segment]: {speaker_label, text, start_ts, end_ts,
        word_timestamps: [{word, start_ts, end_ts}]}"""
        raise NotImplementedError


class SceneAnalyzer:
    """Analyze keyframes into a scene draft."""

    def analyze(self, keyframe_paths):
        """-> SceneDraft: {summary, objects[], people[], actions[],
        visible_text[], type, confidence}"""
        raise NotImplementedError


class Attributor:
    """Attribute transcribed segments to named speakers (or Unknown)."""

    def attribute(self, segments, keyframe_paths, scene_people):
        """-> list[AttributedSegment]: {segment, speaker_name, confidence}.
        face+voice agree -> verified, one signal -> review, no speech ->
        silence. Never guess a name."""
        raise NotImplementedError


class Embedder:
    """Text + image embeddings into the two memory collections."""

    def embed(self, text):
        """-> list[float]"""
        raise NotImplementedError

    def embed_image(self, keyframe_path):
        """-> list[float]"""
        raise NotImplementedError

    @staticmethod
    def collection_names():
        return ("text_memories", "visual_memories")


# ---------------------------------------------------------------------------
# Deterministic mocks
# ---------------------------------------------------------------------------

_MOCK_TEXT = "Live segment (mock transcript)."
_MOCK_SUMMARY = "Live chunk indexed (mock scene)"
_EMBED_DIM = 16


def _pseudo_vector(seed_text):
    """Fixed-dim sha256 pseudo-vector, floats in [0, 1). Deterministic."""
    digest = hashlib.sha256(seed_text.encode("utf-8")).digest()
    return [b / 255.0 for b in digest[:_EMBED_DIM]]


class MockTranscriber(Transcriber):
    """One segment, speaker Unknown, fixed text.

    Interface note (flagged to coordinator): transcribe(audio_path)
    carries no chunk timestamps, so the mock cannot itself stamp the
    segment with the chunk window. It returns None timestamps and the
    pipeline backfills them from the chunk start/end (see ingest.py).
    """

    def transcribe(self, audio_path):
        words = _MOCK_TEXT.split()
        return [{
            "speaker_label": "Unknown",
            "text": _MOCK_TEXT,
            "start_ts": None,
            "end_ts": None,
            "word_timestamps": [
                {"word": w, "start_ts": None, "end_ts": None}
                for w in words
            ],
        }]


class MockSceneAnalyzer(SceneAnalyzer):
    """Fixed mock scene draft (INTERFACES mock behavior, wins over the
    plan's people[{count, description}] draft shape)."""

    def analyze(self, keyframe_paths):
        return {
            "summary": _MOCK_SUMMARY,
            "objects": [],
            "people": [{"name": "Unknown", "confidence": "review"}],
            "actions": ["talking"],
            "visible_text": [],
            "type": "conversation",
            "confidence": "review",
        }


class MockAttributor(Attributor):
    """Always Unknown / review, never a guessed name."""

    def attribute(self, segments, keyframe_paths, scene_people):
        return [
            {"segment": seg, "speaker_name": "Unknown", "confidence": "review"}
            for seg in segments
        ]


class MockEmbedder(Embedder):
    """sha256 pseudo-vectors. Computed by ingest, NOT persisted in this
    phase: the stored scene keeps embedding_refs=None."""

    def embed(self, text):
        return _pseudo_vector(text)

    def embed_image(self, keyframe_path):
        return _pseudo_vector("image:" + str(keyframe_path))


def make_mock_services():
    """-> (Transcriber, SceneAnalyzer, Attributor, Embedder)."""
    return (MockTranscriber(), MockSceneAnalyzer(), MockAttributor(),
            MockEmbedder())


# ---------------------------------------------------------------------------
# Real implementations (design, locked to INTERFACES.md)
# ---------------------------------------------------------------------------
# DESIGN (agreed before code; INTERFACES.md wins over any disagreement):
# - Transcriber.transcribe(audio_path) -> list of {speaker_label, text,
#   start_ts, end_ts, word_timestamps: [{word, start_ts, end_ts}]}.
#   Ingest backfills only None timestamps, so real timestamps pass
#   through untouched. speaker_label is "Unknown" unless diarization
#   actually runs; no diarization is wired here, so it is always
#   "Unknown". Never fake a speaker.
# - SceneAnalyzer.analyze(keyframe_paths) -> {summary, objects[],
#   people[{name, confidence}], actions[], visible_text[], type,
#   confidence}. ONE Argon interactions.create call per chunk, over up
#   to 30 dense frames (1 fps, chronological; sampled down only if
#   more arrive), existing local files only ("mock://" placeholders
#   skipped). Zero real frames -> mock draft,
#   never a fabricated scene. The analyzer describes, it does not
#   identify: people names are forced to "Unknown" and confidence is
#   capped at "review" (only the Attributor can verify a name).
# - ReasoningBackend.reason(context, query) -> {answer, receipts:
#   [{scene_id, timestamp, quote, thumb_url}], sources:
#   ["fact:<id>" | "scene:<id>"], spend_usd?}. Whole-session context
#   exactly as given (facts first, scenes chronological, transcripts),
#   no retrieval, no top_k. Argon must answer ONLY from that context
#   with verbatim quotes; ask.py drops non-matching receipts and forces
#   no-record when receipts/sources are empty. spend_usd is included
#   ONLY if the API returns an explicit dollar cost, else omitted
#   (ask.py then defaults to 0.12).
# - Attributor.attribute(segments, keyframe_paths, scene_people) ->
#   [{segment, speaker_name, confidence}]. face+voice agree ->
#   verified, one signal -> review, no speech -> silence, NEVER guess.
#   Real ArcFace + ECAPA fusion is NOT wired (see FaceVoiceAttributor);
#   the stub preserves Unknown/review-or-silence behavior.
# - Embedder is NOT replaced: MockEmbedder stays, ChromaDB persistence
#   belongs to the data orchestrator.
# - GUARDED / LAZY imports: this module imports stdlib only at top
#   level. faster-whisper and google-genai are imported inside methods,
#   so importing this module with zero third-party packages installed
#   still succeeds and make_mock_services() still works.
# - Interactions API (builder guide): google-genai >= 2.3.0,
#   client.interactions.create, model "gemini-4-argon",
#   generation_config={"thinking_level": ...} only. NO temperature,
#   top_p, top_k (ignored/deprecated on Argon). Key from env ONLY via
#   genai.Client() default env read; never hardcoded, never written
#   to any file.

import json
import logging
import mimetypes
import os
import re

logger = logging.getLogger(__name__)

_ARGON_MODEL = "gemini-4-argon"
_MOCK_DRAFT_KEYS = ("summary", "objects", "people", "actions",
                    "visible_text", "type", "confidence")


def _mock_draft():
    """Fresh mock scene draft (same shape/values as MockSceneAnalyzer)."""
    return MockSceneAnalyzer().analyze([])


def _mock_segments():
    """Fresh mock transcript segments (same shape as MockTranscriber)."""
    return MockTranscriber().transcribe(None)


def _has_gemini_key():
    """True only if the SDK's default env read can find a key.

    genai.Client() reads GEMINI_API_KEY (and GOOGLE_API_KEY) from the
    environment; checking here lets us degrade to the mock with a
    clear log instead of failing inside an API call. The key value is
    never read into a variable, logged, or written anywhere.
    """
    return bool(os.environ.get("GEMINI_API_KEY") or
                os.environ.get("GOOGLE_API_KEY"))


def _strip_code_fence(text):
    """Remove a surrounding ```json / ``` fence from model output."""
    text = (text or "").strip()
    match = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL)
    return match.group(1).strip() if match else text


def _parse_json_object(text):
    """Parse model output as a JSON object; None on any failure."""
    try:
        parsed = json.loads(_strip_code_fence(text))
    except (ValueError, TypeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _str_list(value):
    return [str(v) for v in value if isinstance(v, (str, int, float))] \
        if isinstance(value, list) else []


def _interaction_text(interaction):
    """Best-effort text extraction from an Interactions response."""
    text = getattr(interaction, "output_text", None)
    if isinstance(text, str) and text.strip():
        return text
    # Fallbacks for SDK response shapes (outputs / output items).
    for attr in ("outputs", "output"):
        items = getattr(interaction, attr, None)
        if isinstance(items, (list, tuple)):
            chunks = []
            for item in items:
                chunk = getattr(item, "text", None) or (
                    item.get("text") if isinstance(item, dict) else None)
                if isinstance(chunk, str):
                    chunks.append(chunk)
            if chunks:
                return "\n".join(chunks)
    return ""


def _explicit_spend_usd(interaction):
    """Dollar cost from usage metadata, if the API returns one.

    Returns None unless the response exposes an explicit dollar field
    (spend_usd / cost_usd / total_cost_usd). Raw token counts alone
    do NOT produce a spend figure here, so ask.py's 0.12 default
    applies instead of an invented price calculation.
    """
    usage = getattr(interaction, "usage", None)
    if usage is None:
        usage = getattr(interaction, "usage_metadata", None)
    if usage is None:
        return None
    if isinstance(usage, dict):
        raw = usage
    else:
        raw = {k: getattr(usage, k) for k in
               ("spend_usd", "cost_usd", "total_cost_usd",
                "total_cost", "cost")
               if hasattr(usage, k)}
    for key in ("spend_usd", "cost_usd", "total_cost_usd", "total_cost",
                "cost"):
        value = raw.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
    return None


def _argon_interaction(prompt, thinking_level, image_paths=()):
    """One client.interactions.create call. Raises on any failure.

    Verified against google-genai 2.33.0: Interactions input is a
    string OR a list of Content dicts (TextContentParam /
    ImageContentParam), NOT generate_content-style Part/Content
    objects. Images are sent as base64 data blocks alongside the text
    block. If construction fails, the caller falls back to the mock
    rather than sending a text-only call that never saw the frames.
    """
    import base64  # stdlib, local to this lazy path

    from google import genai  # lazy: module import must not need it

    client = genai.Client()  # default env read only, no hardcoded key
    kwargs = {"model": _ARGON_MODEL,
              "generation_config": {"thinking_level": thinking_level}}
    if image_paths:
        blocks = [{"type": "text", "text": prompt}]
        for path in image_paths:
            mime, _ = mimetypes.guess_type(path)
            with open(path, "rb") as fh:
                data = base64.b64encode(fh.read()).decode("ascii")
            blocks.append({"type": "image", "data": data,
                           "mime_type": mime or "image/jpeg"})
        kwargs["input"] = blocks
    else:
        kwargs["input"] = prompt
    return client.interactions.create(**kwargs)


# ---------------------------------------------------------------------------
# Real transcriber: faster-whisper, real word timestamps
# ---------------------------------------------------------------------------


class FasterWhisperTranscriber(Transcriber):
    """faster-whisper transcription with REAL word timestamps.

    Model size from WHISPER_MODEL (default "base"), device from
    WHISPER_DEVICE (default "cpu"), compute type from
    WHISPER_COMPUTE_TYPE (default "int8"). The model loads lazily on
    the first transcribe() call, so constructing this class never
    requires the library. No diarization runs here, so speaker_label
    is always "Unknown": faking speaker labels is worse than none.
    Any load/transcribe failure logs clearly and falls back to
    MockTranscriber behavior (same shape; ingest backfills the None
    timestamps from the chunk window).
    """

    def __init__(self, model_size=None, device=None, compute_type=None):
        self.model_size = (model_size or
                           os.environ.get("WHISPER_MODEL") or "base")
        self.device = device or os.environ.get("WHISPER_DEVICE") or "cpu"
        self.compute_type = (compute_type or
                             os.environ.get("WHISPER_COMPUTE_TYPE")
                             or "int8")
        self._model = None
        self._load_failed = False

    def _load_model(self):
        if self._model is not None or self._load_failed:
            return self._model
        try:
            from faster_whisper import WhisperModel
            self._model = WhisperModel(
                self.model_size, device=self.device,
                compute_type=self.compute_type)
        except Exception as exc:  # noqa: BLE001 - degrade, don't crash
            self._load_failed = True
            logger.warning(
                "FasterWhisperTranscriber: faster-whisper/model "
                "unavailable (%s); falling back to mock transcript.",
                exc)
        return self._model

    def transcribe(self, audio_path):
        model = self._load_model()
        if model is None or not audio_path or not os.path.isfile(
                str(audio_path)):
            if model is not None:
                logger.warning(
                    "FasterWhisperTranscriber: audio path %r missing; "
                    "falling back to mock transcript.", audio_path)
            return _mock_segments()
        try:
            segments, _info = model.transcribe(
                str(audio_path), word_timestamps=True)
            out = []
            for seg in segments:
                words = []
                for word in (getattr(seg, "words", None) or []):
                    words.append({
                        "word": getattr(word, "word", ""),
                        "start_ts": getattr(word, "start", None),
                        "end_ts": getattr(word, "end", None),
                    })
                out.append({
                    "speaker_label": "Unknown",
                    "text": (getattr(seg, "text", "") or "").strip(),
                    "start_ts": getattr(seg, "start", None),
                    "end_ts": getattr(seg, "end", None),
                    "word_timestamps": words,
                })
            return out
        except Exception as exc:  # noqa: BLE001 - degrade, don't crash
            logger.warning(
                "FasterWhisperTranscriber: transcribe failed (%s); "
                "falling back to mock transcript.", exc)
            return _mock_segments()


# ---------------------------------------------------------------------------
# Real scene analyzer: Argon over keyframes, one call per chunk
# ---------------------------------------------------------------------------


class ArgonSceneAnalyzer(SceneAnalyzer):
    """Argon scene analysis over up to 30 dense frames (1 fps,
    chronological), one Interactions call per chunk, thinking_level
    low. Frames beyond max_frames are evenly sampled down by
    _sample_frames; ingest normally supplies at most 30.

    Only existing local files are passed; "mock://" placeholder paths
    are skipped. Zero real frames -> mock draft (never a fabricated
    scene). No GEMINI_API_KEY/GOOGLE_API_KEY -> mock draft + clear log.
    Parse failure or any API failure -> log + mock draft. People are
    never identified here: names are forced to "Unknown" and confidence
    capped at "review" (verification is the Attributor's job).
    """

    def __init__(self, thinking_level="low", max_frames=30):
        self.thinking_level = thinking_level
        self.max_frames = max_frames

    @staticmethod
    def _real_frames(keyframe_paths):
        return [str(p) for p in (keyframe_paths or [])
                if p and not str(p).startswith("mock://")
                and os.path.isfile(str(p))]

    def _sample_frames(self, frames):
        if len(frames) <= self.max_frames:
            return frames
        step = (len(frames) - 1) / (self.max_frames - 1)
        return [frames[round(i * step)] for i in range(self.max_frames)]

    def analyze(self, keyframe_paths):
        frames = self._sample_frames(self._real_frames(keyframe_paths))
        if not frames:
            logger.warning(
                "ArgonSceneAnalyzer: zero real frames (placeholders "
                "only); returning mock draft.")
            return _mock_draft()
        if not _has_gemini_key():
            logger.warning(
                "ArgonSceneAnalyzer: no GEMINI_API_KEY/GOOGLE_API_KEY in "
                "environment; returning mock draft.")
            return _mock_draft()
        prompt = (
            "You are given a SEQUENCE of frames from one continuous "
            "30-second scene, in chronological order, one frame per "
            "second (frame 1 is the first second, frame 30 the last). "
            "Reason over the sequence in order, not over any single "
            "frame: track motion and actions as they unfold, who "
            "enters or leaves the view, handoffs of objects between "
            "people, and how the scene changes over time. Reply with "
            "JSON ONLY, no other text, with exactly these keys: "
            "summary (string, one or two sentences covering the whole "
            "sequence), objects (list of strings), people (list of "
            "{name, confidence} objects; use name \"Unknown\" for "
            "every person, you must not identify anyone), actions "
            "(list of strings, in the order they happen), "
            "visible_text (list of strings), type (string, e.g. "
            "conversation), confidence (one of verified, review, "
            "silence; use review unless the scene is silent). "
            "Describe only what is visible across the sequence; do "
            "not invent people, objects, or dialogue."
        )
        try:
            interaction = _argon_interaction(
                prompt, self.thinking_level, image_paths=frames)
            parsed = _parse_json_object(_interaction_text(interaction))
            if parsed is None:
                raise ValueError("Argon reply was not a JSON object")
            draft = {
                "summary": str(parsed.get("summary") or ""),
                "objects": _str_list(parsed.get("objects")),
                "people": self._sanitize_people(parsed.get("people")),
                "actions": _str_list(parsed.get("actions")),
                "visible_text": _str_list(parsed.get("visible_text")),
                "type": str(parsed.get("type") or "conversation"),
                "confidence": self._sanitize_confidence(
                    parsed.get("confidence")),
            }
            if not draft["summary"]:
                raise ValueError("Argon reply had an empty summary")
            return draft
        except Exception as exc:  # noqa: BLE001 - degrade, don't crash
            logger.warning(
                "ArgonSceneAnalyzer: Argon call/parse failed (%s); "
                "returning mock draft.", exc)
            return _mock_draft()

    @staticmethod
    def _sanitize_people(people):
        """Force Unknown names; cap confidence at review."""
        out = []
        if isinstance(people, list):
            for person in people:
                if isinstance(person, dict):
                    out.append({"name": "Unknown",
                                "confidence": "review"})
                elif isinstance(person, str):
                    out.append({"name": "Unknown",
                                "confidence": "review"})
        return out or [{"name": "Unknown", "confidence": "review"}]

    @staticmethod
    def _sanitize_confidence(value):
        if value == "silence":
            return "silence"
        # "verified" is not claimable from frames alone.
        return "review"


# ---------------------------------------------------------------------------
# Real reasoning backend: Argon whole-session reasoning (ask.py injection)
# ---------------------------------------------------------------------------


class ArgonReasoning:
    """Argon whole-session reasoning for AskService (constructor
    injection: AskService(store, ArgonReasoning())).

    Context is used exactly as given: facts first, scenes chronological,
    transcripts. No retrieval, no top_k. Argon must answer ONLY from
    that context with verbatim quotes + scene_id + timestamp per
    receipt; ask.py drops non-matching receipts and forces
    "I don't have a record of that." when receipts/sources are empty.
    thinking_level medium. spend_usd is included ONLY if the API
    returns an explicit dollar cost, else omitted (ask.py defaults
    to 0.12). No key, or any API/parse failure, delegates to
    MockReasoning (lazy import from .ask; ask.py never imports
    services.py, so there is no import cycle) with a clear log.
    """

    def __init__(self, thinking_level="medium"):
        self.thinking_level = thinking_level

    @staticmethod
    def _mock_backend():
        try:
            from .ask import MockReasoning
        except ImportError:  # not a package import
            from ask import MockReasoning  # type: ignore[no-redef]
        return MockReasoning()

    def _fallback(self, context, query, reason):
        logger.warning(
            "ArgonReasoning: %s; delegating to MockReasoning.", reason)
        return self._mock_backend().reason(context, query)

    def reason(self, context, query):
        if not _has_gemini_key():
            return self._fallback(
                context, query,
                "no GEMINI_API_KEY/GOOGLE_API_KEY in environment")
        prompt = self._build_prompt(context, query)
        try:
            interaction = _argon_interaction(prompt, self.thinking_level)
            parsed = _parse_json_object(_interaction_text(interaction))
            if parsed is None:
                return self._fallback(
                    context, query, "Argon reply was not a JSON object")
            answer = str(parsed.get("answer") or "")
            receipts = []
            for receipt in parsed.get("receipts") or []:
                if isinstance(receipt, dict) and receipt.get("scene_id"):
                    receipts.append({
                        "scene_id": str(receipt["scene_id"]),
                        "timestamp": receipt.get("timestamp"),
                        "quote": str(receipt.get("quote") or ""),
                        "thumb_url": receipt.get("thumb_url"),
                    })
            sources = [str(s) for s in (parsed.get("sources") or [])
                       if isinstance(s, str) and
                       (s.startswith("fact:") or s.startswith("scene:"))]
            if not answer:
                return self._fallback(context, query, "empty answer")
            result = {"answer": answer, "receipts": receipts,
                      "sources": sources}
            spend = _explicit_spend_usd(interaction)
            if spend is not None:
                result["spend_usd"] = spend
            return result
        except Exception as exc:  # noqa: BLE001 - degrade, don't crash
            return self._fallback(context, query,
                                  "Argon call failed (%s)" % exc)

    @staticmethod
    def _build_prompt(context, query):
        """Whole-session context as given, facts first, then scenes
        chronological, then transcripts. No retrieval, no filtering."""
        lines = [
            "You answer ONLY from the session context below. Do not "
            "use outside knowledge and do not invent quotes, people, "
            "or events. Every factual claim in your answer must be "
            "backed by a receipt whose quote is copied VERBATIM from "
            "a transcript line below, with that line's scene_id and "
            "timestamp. If the context does not record an answer, "
            "reply with answer \"I don't have a record of that.\" "
            "and empty receipts and sources.",
            "Reply with JSON ONLY, no other text, with exactly these "
            "keys: answer (string), receipts (list of {scene_id, "
            "timestamp, quote, thumb_url}), sources (list of strings, "
            "each \"fact:<id>\" or \"scene:<id>\").",
            "--- FACTS (first) ---",
        ]
        for fact in context.get("facts") or []:
            lines.append("- [%s] %s (actors: %s, scene: %s)" % (
                fact.get("id"), fact.get("text"),
                ", ".join(str(a) for a in fact.get("actors") or []),
                fact.get("scene_id")))
        lines.append("--- SCENES (chronological) ---")
        for scene in context.get("scenes") or []:
            lines.append("- [%s] %s..%s %s (type: %s)" % (
                scene.get("id"), scene.get("start_ts"),
                scene.get("end_ts"), scene.get("summary"),
                scene.get("type")))
        lines.append("--- TRANSCRIPTS (same scene order) ---")
        for line in context.get("transcripts") or []:
            lines.append("- scene %s @ %s: %s" % (
                line.get("scene_id"), line.get("start_ts"),
                line.get("text")))
        lines.append("--- QUESTION ---")
        lines.append(str(query))
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Attributor: documented stub (real ArcFace + ECAPA fusion NOT wired)
# ---------------------------------------------------------------------------


class FaceVoiceAttributor(Attributor):
    """Documented stub preserving mock behavior: Unknown + review,
    silence when a segment has no speech, NEVER a guessed name.

    WHAT REAL FUSION NEEDS (not implemented here, by design):
    1. Enrollment data the store does not yet carry: an ArcFace face
       embedding per enrolled person (from their enrollment photo)
       and an ECAPA-TDNN voice embedding per enrolled person (from
       their voice sample), keyed by person id/name.
    2. Per-segment signals: a face crop embedding from the scene's
       keyframes (ArcFace, e.g. insightface) and a speaker embedding
       from the diarized segment audio (ECAPA-TDNN, e.g. speechbrain),
       each with a cosine-similarity match against enrollment.
    3. Fusion rule (locked): face and voice agree on the same enrolled
       person -> {"speaker_name": name, "confidence": "verified"};
       exactly one signal matches -> review; neither matches, or the
       person is not enrolled -> Unknown/review; empty segment text
       (no speech) -> Unknown/silence.
    4. Libraries that would have to install AND run here: insightface
       (+ onnxruntime) for ArcFace and speechbrain (+ torch) for
       ECAPA. Neither is installed in this environment, and importing
       torch/speechbrain at module load would break the guarded-import
       rule, so this class checks only import specs lazily and still
       returns the stub result until steps 1-3 are actually built.
    """

    def __init__(self):
        import importlib.util
        self._arcface_available = (
            importlib.util.find_spec("insightface") is not None)
        self._ecapa_available = (
            importlib.util.find_spec("speechbrain") is not None)
        if not (self._arcface_available and self._ecapa_available):
            logger.warning(
                "FaceVoiceAttributor: real fusion unavailable "
                "(insightface present: %s, speechbrain present: %s); "
                "returning Unknown/review-or-silence stub.",
                self._arcface_available, self._ecapa_available)

    def attribute(self, segments, keyframe_paths, scene_people):
        out = []
        for seg in segments:
            text = (seg.get("text") or "").strip() \
                if isinstance(seg, dict) else ""
            confidence = "silence" if not text else "review"
            out.append({"segment": seg, "speaker_name": "Unknown",
                        "confidence": confidence})
        return out
