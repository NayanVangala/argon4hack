"""Standalone auto conversation detection for Scene.

Speech-presence plus dialogue-pattern detection only. No diarization,
no speaker identity, no new models, Python standard library only.

Where this sits in the pipeline
--------------------------------
The bridge slices a recording into ~30s chunks. faster-whisper
transcribes each chunk (speaker always "Unknown") and Argon analyzes
each chunk. This module runs between transcription and analysis and
answers one question: is this chunk worth an Argon call?

Routing (fixed, do not change without updating the integration guide):
    conversation -> analyze        (dialogue is the core Scene input)
    monologue    -> analyze        (a solo speaker can state a promise)
    ambient      -> mark_and_skip  (noise, no content worth ~$0.019)
    silent       -> mark_and_skip  (nothing recorded at all)

"mark_and_skip" means the chunk still gets a minimal scene record so
the timeline stays complete, but the Argon call is skipped. This
module only outputs the routing decision; creating the minimal scene
is the integration guide's concern. Everything that path needs is in
the returned dict: label, confidence, reasons, word_count,
speech_seconds.

Real faster-whisper output shape (verified 2026-10-25 in
~/workspace/scene-backend/app/services.py, FasterWhisperTranscriber,
and app/ingest.py)
-------------------------------------------------------------------
transcribe(audio_path) returns a list of segment dicts::

    {
        "speaker_label": "Unknown",   # always Unknown, no diarization
        "text": "...",                # segment transcript text
        "start_ts": float | None,     # segment start, seconds
        "end_ts": float | None,       # segment end, seconds
        "word_timestamps": [           # one dict per word
            {"word": "...", "start_ts": float | None,
             "end_ts": float | None},
            ...
        ],
    }

Differences from the brief's shorthand, and how this module handles
them:

1. Field names are ``start_ts`` / ``end_ts``, not ``start`` / ``end``.
   This module accepts BOTH spellings (and ``word`` or ``text`` for
   the token), so it works whether the caller passes raw
   ``word_timestamps`` dicts or normalized ``start``/``end`` dicts.
   See ``words_from_segments()`` for the flattening helper.
2. Timestamps can be ``None``. The mock transcriber returns None for
   every timestamp and ingest.py backfills them from the chunk
   window; a failed real transcribe also falls back to the mock
   shape. So missing timestamps must never crash detection and must
   never by themselves force a skip: when timestamps are missing,
   speech duration is unknown and the decision falls back to word
   count and transcript structure (see below).
3. The segment list is NOT the input to ``detect()``. The contract
   input ``words`` is the flattened word list for one chunk. Use
   ``words_from_segments(segments)`` to build it.

Honest limits (read before trusting the label)
----------------------------------------------
Without diarization, dialogue detection is a heuristic over
transcript structure and word-timing gaps, not speaker identity:

- One speaker doing Q and A ("What did I promise? I promised to
  call.") can look like dialogue.
- Two speakers taking long turns can look like monologue.
- Rapid back-and-forth with sub-2s gaps can look like monologue.

All three failure directions are acceptable here because the failure
behavior defaults to ``analyze``: conversation and monologue share a
route, so a mislabel between them costs nothing. Only the skip
route (ambient/silent) can lose content, so the skip thresholds are
deliberately conservative: a chunk is skipped only when it has
almost no words AND almost no speech duration (or nothing at all).
Anything uncertain routes to ``analyze``.

Failure behavior
----------------
``detect()`` never raises on bad input. Structurally malformed input
(wrong types, missing keys, word entries that are not dicts or carry
no text) is sanitized and, when it would otherwise produce a skip
decision, defaults to label ``monologue`` with route ``analyze``
and confidence 0.5, with a reason saying so. An unusable chunk
duration alone (None, NaN, inf, <= 0) is NOT structural malformation:
it just falls back to 30.0s and cannot by itself force analyze, so a
low-word chunk with unknown duration can still be skipped on count.
Negative or reversed timestamps are dropped per word, not fatal. A
chunk is never silently dropped.

Public API
----------
    detect(transcript, words, chunk_duration_s) -> dict
    words_from_segments(segments) -> list

``detect()`` return dict keys (exactly these):
    label          one of: conversation, monologue, ambient, silent
    confidence     float in [0.0, 1.0]
    reasons        list of short human-readable strings
    route          one of: analyze, mark_and_skip
    speech_seconds float, total word duration in seconds (0.0 when
                   no usable timestamps; see reasons)
    word_count     int, effective word count (see below)
    turn_count     int, inferred turns (gap-based, or punctuation
                   utterances when no usable timestamps)

Run ``python3 autodetect.py`` for a built-in self-test.
"""

import math
import re

__all__ = ["detect", "words_from_segments"]

# ---------------------------------------------------------------------------
# Threshold constants (tuned for the standard 30s chunk; see justifications)
# ---------------------------------------------------------------------------

# Fallback chunk length when chunk_duration_s is missing or unusable.
# Only used to cap speech_seconds; the skip thresholds below are
# absolute, not scaled to chunk length, so this value cannot cause a
# skip by itself.
CHUNK_DURATION_DEFAULT_S = 30.0

# Minimum words for a chunk to count as real speech.
# Justification: conversational speech runs ~150 words/minute, so 10
# words is roughly 4 seconds of talking. Whisper hallucinations on
# noise, music, or silence typically produce 1-5 stray words ("you",
# "thank you", "music"). 10 sits above the hallucination band with
# margin, while still being low enough that a short real utterance
# is not dismissed on count alone (it must ALSO fail the duration
# test below before it can be skipped).
MIN_WORDS_FOR_SPEECH = 10

# Minimum total speech seconds for a chunk to count as real speech.
# Justification: 10 words at a typical ~0.3s per word is ~3 seconds.
# Below 3 seconds of detected speech there is no room for a clause
# that could carry a promise, a decision, or a fact worth analyzing;
# it is a fragment, a cough, a door, or a hallucinated snippet. A
# chunk must fail BOTH the word test and this duration test (when
# duration is known) before it is skipped, so a short-but-clear
# utterance ("I promise to send it tomorrow", 7 words over ~3-4s)
# still routes to analyze via the duration leg.
MIN_SPEECH_SECONDS = 3.0

# Word gap (seconds) that marks a turn boundary.
# Justification: within-turn pauses (breath, hesitation, thinking)
# are usually under ~1 second. A silence over 2 seconds between word
# groups usually marks a turn change or a topic break. This is
# deliberately conservative: rapid dialogue with sub-2s gaps will
# undercount turns and may label as monologue, which is safe because
# monologue still routes to analyze. The threshold only shapes the
# label, never the skip decision.
TURN_GAP_SECONDS = 2.0

# Maximum words in a "short" utterance/turn.
# Justification: back-and-forth dialogue turns ("Yeah, I'll be
# there", "What time should we meet?") typically run under ~12
# words, while monologue sentences and lecture-style turns usually
# run longer. 12 separates exchanges from exposition without
# pretending to identify speakers.
SHORT_UTTERANCE_MAX_WORDS = 12

# Minimum inferred turns for a conversation label.
# Justification: 3 turns is the smallest pattern that shows exchange
# rather than a single interruption (A speaks, B interjects, A
# resumes is 3 turns but only 1 short one, so it still needs the
# short-turn test below). Fewer than 3 turns is one flow.
MIN_TURNS_FOR_CONVERSATION = 3

# Minimum short turns for a conversation label.
# Justification: at least 2 short turns must be present so that one
# long speech plus one short interjection does not count as a
# dialogue. Combined with MIN_TURNS_FOR_CONVERSATION, the pattern
# required is genuine alternation, not a single aside.
MIN_SHORT_TURNS_FOR_CONVERSATION = 2

# Per-word duration clamp (seconds). A single "word" spanning longer
# than this is a timestamp error (e.g. a backfilled chunk window or
# garbage), not a spoken word; clamping keeps one bad timestamp from
# inflating speech_seconds past the whole chunk.
MAX_WORD_DURATION_S = 30.0

# Fixed routing table (contract).
_ROUTE = {
    "conversation": "analyze",
    "monologue": "analyze",
    "ambient": "mark_and_skip",
    "silent": "mark_and_skip",
}

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
_QUESTION_RE = re.compile(r"\?\s*[\"'\)\]]*\s*$")


# ---------------------------------------------------------------------------
# Input normalization (never raises)
# ---------------------------------------------------------------------------

def _as_float(value):
    """Float or None for numeric, finite-or-not values. Bools rejected."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        try:
            return float(value)
        except (TypeError, ValueError, OverflowError):
            return None
    return None


def _clean_word(entry):
    """Normalize one word dict to (text, start, end).

    Accepts start/end and start_ts/end_ts spellings, and word/text
    spellings for the token. Returns (text, start_or_None,
    end_or_None) with start/end sanitized: negative starts dropped,
    end before start dropped, absurd per-word durations clamped.
    Entries that are not dicts yield ("", None, None).
    """
    if not isinstance(entry, dict):
        return ("", None, None)
    token = entry.get("word", entry.get("text", ""))
    text = token.strip() if isinstance(token, str) else ""
    start = _as_float(entry.get("start_ts", entry.get("start")))
    end = _as_float(entry.get("end_ts", entry.get("end")))
    if start is not None and (math.isnan(start) or math.isinf(start)
                              or start < 0):
        start = None
    if end is not None and (math.isnan(end) or math.isinf(end)
                            or end < 0):
        end = None
    if start is not None and end is not None:
        if end < start:
            start, end = None, None
        elif end - start > MAX_WORD_DURATION_S:
            end = start + MAX_WORD_DURATION_S
    return (text, start, end)


def _clean_duration(value):
    """Usable chunk duration in seconds, or the default."""
    duration = _as_float(value)
    if duration is None or math.isnan(duration) or math.isinf(duration) \
            or duration <= 0:
        return CHUNK_DURATION_DEFAULT_S
    return duration


def words_from_segments(segments):
    """Flatten faster-whisper segment dicts into ``detect()`` words.

    Input: the list returned by FasterWhisperTranscriber.transcribe()
    (or the mock shape): each segment has ``word_timestamps`` items
    with ``word`` / ``start_ts`` / ``end_ts``. Output: a flat list of
    dicts with ``word``, ``start``, ``end`` keys, in segment order.
    Words with empty text are skipped; words with None timestamps are
    kept (their duration is unknown, handled by ``detect()``).
    Segments without ``word_timestamps`` contribute nothing here;
    their ``text`` is still visible to ``detect()`` via the transcript
    argument if the caller passes the joined segment texts.

    Never raises: non-list input yields [], malformed segments yield
    whatever clean words could be extracted.
    """
    if not isinstance(segments, (list, tuple)):
        return []
    words = []
    for seg in segments:
        if not isinstance(seg, dict):
            continue
        stamps = seg.get("word_timestamps")
        if not isinstance(stamps, (list, tuple)):
            continue
        for entry in stamps:
            if not isinstance(entry, dict):
                continue
            text, start, end = _clean_word(entry)
            if text:
                words.append({"word": text, "start": start, "end": end})
    return words


# ---------------------------------------------------------------------------
# Turn / utterance inference (no speaker identity anywhere)
# ---------------------------------------------------------------------------

def _split_utterances(text):
    """Split transcript text into utterances on sentence punctuation.

    Returns a list of (utterance_text, word_count) pairs, dropping
    empties. Punctuation inside a word (e.g. "e.g.") is not split
    because the regex requires sentence-ending punctuation followed
    by whitespace. A transcript with no sentence punctuation is one
    utterance.
    """
    if not text or not text.strip():
        return []
    parts = _SENTENCE_SPLIT_RE.split(text.strip())
    out = []
    for part in parts:
        stripped = part.strip()
        if stripped:
            out.append((stripped, len(stripped.split())))
    return out


def _gap_turns(cleaned_words):
    """Split timestamped words into turns at gaps > TURN_GAP_SECONDS.

    Returns a list of word-count-per-turn, or None when there are no
    usable timestamps (caller falls back to punctuation utterances).
    Words without timestamps break the chain: the gap to the next
    timestamped word is unknown, so such words extend the current
    turn rather than starting a new one.
    """
    timed = [(text, s, e) for (text, s, e) in cleaned_words
             if text and s is not None and e is not None]
    if not timed:
        return None
    turns = []
    current = 0
    prev_end = None
    for _text, start, end in timed:
        if prev_end is not None and start - prev_end > TURN_GAP_SECONDS:
            turns.append(current)
            current = 0
        current += 1
        prev_end = end if prev_end is None else max(prev_end, end)
    turns.append(current)
    # Words without timestamps that were skipped above belong to the
    # flow too; fold them into the turn count by word count only when
    # they exist, without inventing boundaries: they extend the last
    # turn. (Counted in word_count regardless; see detect().)
    untimed = sum(1 for (text, s, e) in cleaned_words
                  if text and (s is None or e is None))
    if untimed and turns:
        turns[-1] += untimed
    return turns


def _has_question_answer(utterances):
    """True when a '?' utterance is followed by a non-empty answer.

    A question followed by any further utterance (even one word,
    e.g. "Yeah.") counts as a question-answer pair. This is the
    strongest dialogue signal available without speakers, and it is
    also the most honestly limited: a solo speaker asking and
    answering their own question triggers it too. That mislabel is
    safe (conversation still routes to analyze).
    """
    for i, (text, _count) in enumerate(utterances[:-1]):
        if _QUESTION_RE.search(text.strip()):
            nxt_text, nxt_count = utterances[i + 1]
            if nxt_text.strip() and nxt_count >= 1:
                return True
    return False


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def detect(transcript, words, chunk_duration_s):
    """Classify one transcribed chunk and route it.

    Args:
        transcript: chunk transcript text (str). May be "" when the
            caller only has words, or non-empty when words are empty.
        words: list of word dicts with start/end timestamps in
            seconds, as produced by faster-whisper (see module
            docstring: ``start_ts``/``end_ts`` spellings also
            accepted). May be [] or None.
        chunk_duration_s: chunk length in seconds (float, ~30.0).
            Missing or unusable values fall back to 30.0.

    Returns a dict with exactly these keys: label, confidence,
    reasons, route, speech_seconds, word_count, turn_count.
    Never raises: any unexpected input shape falls back to the safe
    default (monologue / analyze) with a reason saying so.
    """
    try:
        return _detect_inner(transcript, words, chunk_duration_s)
    except Exception as exc:  # noqa: BLE001 - contract: never raise
        return {
            "label": "monologue",
            "confidence": 0.5,
            "reasons": ["detection failed (%s); defaulting to analyze "
                        "so the chunk is never dropped" % exc],
            "route": "analyze",
            "speech_seconds": 0.0,
            "word_count": 0,
            "turn_count": 0,
        }


def _detect_inner(transcript, words, chunk_duration_s):
    reasons = []
    malformed = False

    # -- sanitize inputs ------------------------------------------------
    if transcript is None:
        transcript = ""
        malformed = True
    elif not isinstance(transcript, str):
        try:
            transcript = str(transcript)
        except Exception:
            transcript = ""
        malformed = True
    transcript = transcript.strip()

    if words is None:
        words = []
        malformed = True
    elif not isinstance(words, (list, tuple)):
        words = []
        malformed = True
        reasons.append("words input was not a list; treated as empty")

    # Unusable duration falls back to 30.0s (see _clean_duration);
    # it is not structural malformation and cannot force analyze.
    duration = _clean_duration(chunk_duration_s)

    cleaned = []
    for entry in words:
        text, start, end = _clean_word(entry)
        if not isinstance(entry, dict) or not text:
            # A word entry with no usable text is malformed input,
            # not evidence of silence: it must not help skip a chunk.
            malformed = True
        cleaned.append((text, start, end))
    word_texts = [text for (text, _s, _e) in cleaned if text]
    word_count = len(word_texts)

    # Speech duration: sum of usable word durations, capped at the
    # chunk length. duration_known is False when no word carries a
    # usable timestamp pair (mock shape, backfilled None, or missing
    # words); in that case duration must not be used to skip.
    speech_seconds = 0.0
    timed_pairs = 0
    for (_text, start, end) in cleaned:
        if start is not None and end is not None:
            speech_seconds += end - start
            timed_pairs += 1
    duration_known = timed_pairs > 0
    if speech_seconds > duration:
        speech_seconds = duration
    speech_seconds = round(speech_seconds, 3)

    # Effective text and count: words win when present; transcript
    # fills in when words are empty, and vice versa.
    transcript_word_count = len(transcript.split()) if transcript else 0
    if word_count == 0 and transcript_word_count > 0:
        word_count = transcript_word_count
        reasons.append("no word timestamps; counted %d words from "
                       "transcript text" % word_count)
    elif word_count > 0 and transcript_word_count == 0:
        transcript = " ".join(word_texts)
        reasons.append("empty transcript; used word list as text")
    elif word_count > 0 and transcript_word_count > 0 \
            and abs(word_count - transcript_word_count) > \
            max(5, int(0.5 * max(word_count, transcript_word_count))):
        reasons.append("transcript and word counts differ; used word "
                       "count (%d)" % word_count)

    # -- silent ---------------------------------------------------------
    if word_count == 0:
        if malformed:
            reasons.append("input was malformed; defaulting to "
                           "analyze so the chunk is never dropped")
            return _result("monologue", 0.5, reasons, speech_seconds,
                           word_count, 0)
        reasons.append("no words detected and transcript is empty")
        return _result("silent", 0.95, reasons, speech_seconds,
                       word_count, 0)

    # -- ambient: few words AND (short speech or unknown duration) ----
    # Both legs required when duration is known, so a short-but-clear
    # utterance is never skipped on count alone. When duration is
    # unknown (mock shape), count alone decides, because there is no
    # second leg to consult; a sub-10-word chunk with no timing is
    # far more likely to be a noise hallucination than a promise.
    if word_count < MIN_WORDS_FOR_SPEECH and (
            not duration_known or speech_seconds < MIN_SPEECH_SECONDS):
        if malformed:
            # Skip decisions need clean evidence. Structurally
            # malformed input defaults to analyze, never to a skip.
            reasons.append("input was malformed; defaulting to "
                           "analyze so the chunk is never dropped")
            return _result("monologue", 0.5, reasons, speech_seconds,
                           word_count, 0)
        if duration_known:
            reasons.append(
                "%d words under %d-word minimum and %.1fs speech "
                "under %.1fs minimum; looks like noise or a "
                "hallucinated fragment, not speech content"
                % (word_count, MIN_WORDS_FOR_SPEECH, speech_seconds,
                   MIN_SPEECH_SECONDS))
        else:
            reasons.append(
                "%d words under %d-word minimum with no usable word "
                "timestamps; looks like noise or a hallucinated "
                "fragment" % (word_count, MIN_WORDS_FOR_SPEECH))
        confidence = 0.85 if word_count <= 5 else 0.75
        return _result("ambient", confidence, reasons, speech_seconds,
                       word_count, 0)

    # -- speech present: conversation vs monologue ----------------------
    # Turn inference: gap-based turns when timestamps exist, else
    # punctuation utterances. Utterances (for Q-A) always come from
    # the effective transcript text.
    utterances = _split_utterances(transcript)
    gap_turn_counts = _gap_turns(cleaned)
    if gap_turn_counts is not None:
        turn_counts = gap_turn_counts
        turn_count = len(turn_counts)
        turn_basis = "word-timing gaps over %.1fs" % TURN_GAP_SECONDS
    else:
        turn_counts = [count for (_t, count) in utterances]
        turn_count = len(turn_counts)
        turn_basis = ("sentence punctuation (no usable word "
                      "timestamps)")
        if word_count > 0 and not transcript:
            turn_count = 1
    short_turns = sum(1 for c in turn_counts
                      if 0 < c <= SHORT_UTTERANCE_MAX_WORDS)
    qa_pair = _has_question_answer(utterances)

    signals = []
    if qa_pair:
        signals.append("question-answer pair in transcript")
    if turn_count >= MIN_TURNS_FOR_CONVERSATION and \
            short_turns >= MIN_SHORT_TURNS_FOR_CONVERSATION:
        signals.append(
            "%d turns with %d short turns (alternating short "
            "utterances)" % (turn_count, short_turns))
    if signals:
        reasons.append("dialogue pattern via %s" % "; ".join(signals))
        reasons.append("turns inferred from %s; without diarization "
                       "this is a heuristic, not speaker identity"
                       % turn_basis)
        confidence = 0.85 if len(signals) >= 2 else 0.75
        return _result("conversation", confidence, reasons,
                       speech_seconds, word_count, turn_count)

    reasons.append(
        "sustained speech (%d words, %.1fs) with no dialogue "
        "pattern: %d turn(s), %d short, no question-answer pair"
        % (word_count, speech_seconds, turn_count, short_turns))
    reasons.append("turns inferred from %s; without diarization a "
                   "two-speaker exchange with long turns can look "
                   "like monologue, which still routes to analyze"
                   % turn_basis)
    confidence = 0.8
    if malformed:
        confidence = 0.6
        reasons.append("input had malformed parts; confidence "
                       "lowered but chunk still routes to analyze")
    return _result("monologue", confidence, reasons, speech_seconds,
                   word_count, turn_count)


def _result(label, confidence, reasons, speech_seconds, word_count,
            turn_count):
    """Assemble the contract dict with clamped confidence."""
    confidence = max(0.0, min(1.0, float(confidence)))
    return {
        "label": label,
        "confidence": round(confidence, 3),
        "reasons": list(reasons),
        "route": _ROUTE[label],
        "speech_seconds": float(speech_seconds),
        "word_count": int(word_count),
        "turn_count": int(turn_count),
    }


# ---------------------------------------------------------------------------
# Self-test: python3 autodetect.py (prints pass/fail per case)
# ---------------------------------------------------------------------------

def _make_words(phrases_with_gaps):
    """Build a synthetic word list.

    phrases_with_gaps: list of (text, start_s, gap_after_s). Words in
    a phrase are spaced 0.3s apart starting at start_s; gap_after_s
    is the silence before the next phrase. Returns (words, text)
    where text joins phrases with ". " and a trailing "." so the
    punctuation path sees the same utterances as the timing path.
    """
    words = []
    texts = []
    for text, start, _gap in phrases_with_gaps:
        tokens = text.split()
        for i, token in enumerate(tokens):
            s = start + i * 0.3
            words.append({"word": token, "start": s, "end": s + 0.25})
        texts.append(text)
    return words, ". ".join(texts) + "."


def _check(name, result, label, route):
    ok = result["label"] == label and result["route"] == route
    status = "PASS" if ok else "FAIL"
    print("%s %s: label=%s (want %s) route=%s (want %s) "
          "confidence=%.2f words=%d speech=%.1fs turns=%d" % (
              status, name, result["label"], label, result["route"],
              route, result["confidence"], result["word_count"],
              result["speech_seconds"], result["turn_count"]))
    for reason in result["reasons"]:
        print("      - %s" % reason)
    return ok


def self_test():
    """Synthetic cases, no audio, no network. Returns True if all pass."""
    print("autodetect self-test (synthetic, stdlib only)")
    passed = 0
    total = 0

    # 1. Silent: no words, empty transcript.
    total += 1
    passed += _check("silent",
                     detect("", [], 30.0), "silent", "mark_and_skip")

    # 2. Ambient: few words, very short speech duration.
    total += 1
    ambient_words = [
        {"word": "yeah", "start": 5.0, "end": 5.3},
        {"word": "uh", "start": 5.4, "end": 5.6},
        {"word": "noise", "start": 20.0, "end": 20.2},
    ]
    passed += _check("ambient",
                     detect("yeah uh noise", ambient_words, 30.0),
                     "ambient", "mark_and_skip")

    # 3. Monologue: sustained speech, one flow, no turn alternation,
    #    no question, gaps under the turn threshold.
    total += 1
    mono_text = (
        "I spent the morning working on the quarterly report and "
        "then I walked through the whole draft again to check every "
        "number against the source spreadsheet before sending it to "
        "the team for review this afternoon")
    mono_words = []
    t = 1.0
    for token in mono_text.split():
        mono_words.append({"word": token, "start": t, "end": t + 0.25})
        t += 0.35
    passed += _check("monologue",
                     detect(mono_text + ".", mono_words, 30.0),
                     "monologue", "analyze")

    # 4. Dialogue: alternating short utterances plus a Q-A pair,
    #    with >2s gaps between turns.
    total += 1
    dialog_words, dialog_text = _make_words([
        ("Hey are you coming tomorrow", 1.0, 2.5),
        ("Yeah I will be there", 6.0, 2.5),
        ("What time should we meet", 11.0, 2.5),
        ("Let us say nine in the morning", 16.0, 0.0),
    ])
    # Put the question mark back: _make_words strips it, so rebuild
    # the transcript with real punctuation for the Q-A signal.
    dialog_text = ("Hey, are you coming tomorrow? Yeah, I will be "
                   "there. What time should we meet? Let us say nine "
                   "in the morning.")
    passed += _check("dialogue",
                     detect(dialog_text, dialog_words, 30.0),
                     "conversation", "analyze")

    # 5. Malformed input defaults to analyze, never raises.
    total += 1
    try:
        result = detect(None, "not-a-list", float("nan"))
        passed += _check("malformed-defaults",
                         result, "monologue", "analyze")
    except Exception as exc:  # noqa: BLE001 - self-test must report
        print("FAIL malformed-defaults: raised %s" % exc)

    # 6. Empty transcript with words present: words carry it.
    total += 1
    passed += _check("words-without-transcript",
                     detect("", mono_words, 30.0),
                     "monologue", "analyze")

    # 7. Words empty with a real transcript: transcript carries it.
    total += 1
    passed += _check("transcript-without-words",
                     detect(mono_text + ".", [], 30.0),
                     "monologue", "analyze")

    # 8. Real faster-whisper spelling (start_ts/end_ts) works.
    total += 1
    ts_words = [{"word": w["word"], "start_ts": w["start"],
                 "end_ts": w["end"]} for w in mono_words]
    passed += _check("start_ts-spelling",
                     detect(mono_text + ".", ts_words, 30.0),
                     "monologue", "analyze")

    # 9. words_from_segments flattens the real segment shape.
    total += 1
    segments = [{
        "speaker_label": "Unknown",
        "text": mono_text,
        "start_ts": 1.0,
        "end_ts": 20.0,
        "word_timestamps": ts_words,
    }]
    flat = words_from_segments(segments)
    result = detect(mono_text + ".", flat, 30.0)
    ok = len(flat) == len(mono_words) and result["label"] == "monologue"
    print("%s segments-flatten: %d words (want %d) label=%s" % (
        "PASS" if ok else "FAIL", len(flat), len(mono_words),
        result["label"]))
    passed += 1 if ok else 0

    print("self-test: %d/%d passed" % (passed, total))
    return passed == total


if __name__ == "__main__":
    raise SystemExit(0 if self_test() else 1)
