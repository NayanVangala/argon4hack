"""Critic pure functions (module 5).

Built to ~/workspace/scene-backend/INTERFACES.md (locked). Stdlib only,
no I/O, no LLM calls, no side effects: every function takes plain dicts
and returns plain data. Callers execute fixes; this module never calls
Argon.

Mock shim (locked): when keyframe/face annotations are absent (all mock
data), visual_grounding and people_consistency preserve the scene's
seeded critique entry instead of inventing a pass. Seeded scenes keep
their seeded critique; newly ingested mock scenes (no seeded entry)
get all-pass from the shim.
"""

import difflib
import re
from datetime import datetime

FUZZY_THRESHOLD = 0.80
TOKEN_COVERAGE_FLOOR = 0.50
RELEVANCE_FLOOR = 0.25

_STOPWORDS = {
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "i", "you", "he", "she", "it", "we", "they", "me", "him", "her", "us",
    "them", "my", "your", "his", "its", "our", "their", "this", "that",
    "these", "those", "am", "do", "does", "did", "have", "has", "had",
    "will", "would", "can", "could", "should", "of", "in", "on", "at",
    "to", "for", "with", "by", "from", "as", "and", "or", "but", "not",
    "no", "so", "if", "then", "than", "into", "about", "over", "after",
    "before", "just", "only", "also", "very", "how", "what", "when",
    "where", "who", "why", "ll", "re", "ve", "don", "t",
}
_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday",
         "saturday", "sunday", "today", "tomorrow", "yesterday")
_OPPOSING_PAIRS = (
    ("leads with glasses", "leads with dashboard"),
    ("will send", "will not send"),
    ("will send", "won't send"),
)
_PROMISE_RE = re.compile(r"\b(promis|commit|decid)", re.IGNORECASE)
_NO_RECORD = "i don't have a record of that"


def _normalize(text):
    return _NON_ALNUM.sub(" ", (text or "").lower()).strip()


def _tokens(text):
    return [t for t in _normalize(text).split() if t not in _STOPWORDS]


def _fuzzy(a, b):
    return difflib.SequenceMatcher(None, _normalize(a), _normalize(b)).ratio()


def _parse_ts(value):
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _check(check, result, note):
    return {"check": check, "result": result, "note": note}


def _transcript_lines(scene):
    lines = []
    for item in (scene or {}).get("transcript") or []:
        if isinstance(item, str):
            lines.append({"text": item, "start_ts": None, "end_ts": None})
        elif isinstance(item, dict):
            lines.append({
                "text": item.get("text") or "",
                "speaker": item.get("speaker"),
                "start_ts": item.get("start_ts"),
                "end_ts": item.get("end_ts"),
            })
    return lines


def _transcript_text(scene):
    return " ".join(line["text"] for line in _transcript_lines(scene))


def _seeded_entry(scene, check):
    for entry in (scene or {}).get("critique") or []:
        if isinstance(entry, dict) and entry.get("check") == check:
            return _check(check, entry.get("result", "pass"),
                          entry.get("note", ""))
    return None


def _annotation_text(scene):
    """Normalized keyframe-annotation text, or None when absent."""
    annotations = (scene or {}).get("keyframe_annotations")
    if not annotations:
        return None
    parts = []
    for item in annotations:
        if isinstance(item, str):
            parts.append(item)
        elif isinstance(item, dict):
            for key in ("objects", "visible_text", "text", "labels", "people"):
                value = item.get(key)
                if isinstance(value, list):
                    parts.extend(str(v) for v in value)
                elif value:
                    parts.append(str(value))
    text = _normalize(" ".join(parts))
    return text or None


def _item_grounded(item, annotation_text):
    norm = _normalize(item)
    if not norm:
        return True
    if norm in annotation_text:
        return True
    return all(tok in annotation_text for tok in norm.split())


# -- per-scene -----------------------------------------------------------

def critique_scene(scene):
    """Four checks -> [{check, result, note}], in contract order."""
    scene = scene or {}
    lines = _transcript_lines(scene)
    transcript = _transcript_text(scene)
    quote = scene.get("quote") or ""
    summary = scene.get("summary") or ""

    # transcript_alignment: quote/summary key tokens in transcript,
    # or fuzzy similarity >= 0.80.
    if not lines:
        if not quote:
            alignment = _check("transcript_alignment", "pass",
                               "No speech in scene; nothing to align")
        else:
            alignment = _check("transcript_alignment", "fail",
                               "Scene claims a quote but has no transcript")
    else:
        best = max((_fuzzy(quote, line["text"]) for line in lines),
                   default=0.0) if quote else 0.0
        key_tokens = _tokens(quote) or _tokens(summary)
        coverage = (sum(1 for t in key_tokens if t in _normalize(transcript))
                    / len(key_tokens)) if key_tokens else 0.0
        if best >= FUZZY_THRESHOLD or coverage >= TOKEN_COVERAGE_FLOOR:
            alignment = _check(
                "transcript_alignment", "pass",
                "Quote matches transcript (fuzzy %.2f, token coverage %.2f)"
                % (best, coverage))
        else:
            alignment = _check(
                "transcript_alignment", "fail",
                "Summary/quote key claims not found in transcript "
                "(fuzzy %.2f, token coverage %.2f)" % (best, coverage))

    # visual_grounding: annotations when present, else seeded entry (shim).
    annotation_text = _annotation_text(scene)
    if annotation_text is not None:
        claimed = list(scene.get("objects") or []) + \
            list(scene.get("visible_text") or [])
        missing = [c for c in claimed if not _item_grounded(c, annotation_text)]
        if missing:
            grounding = _check("visual_grounding", "fail",
                               "Claimed but not in keyframes: %s" % ", ".join(missing))
        else:
            grounding = _check("visual_grounding", "pass",
                               "Claimed objects/text appear in keyframes")
    else:
        grounding = _seeded_entry(scene, "visual_grounding") or _check(
            "visual_grounding", "pass",
            "No keyframe annotations; no grounding claim to check")

    # people_consistency: face annotations when present, else shim.
    face_annotations = scene.get("face_annotations")
    if face_annotations:
        speakers = {line["speaker"] for line in lines if line.get("speaker")}
        people = scene.get("people") or []
        named = [p.get("name") for p in people
                 if isinstance(p, dict) and p.get("name") not in (None, "Unknown")]
        unmatched = [n for n in named if n not in speakers]
        counts = [a.get("face_count") for a in face_annotations
                  if isinstance(a, dict) and a.get("face_count") is not None]
        if unmatched:
            people_check = _check("people_consistency", "fail",
                                  "People not heard as speakers: %s"
                                  % ", ".join(unmatched))
        elif counts and any(c != len(people) for c in counts):
            people_check = _check("people_consistency", "fail",
                                  "People count %d does not match face count %s"
                                  % (len(people), counts))
        else:
            people_check = _check("people_consistency", "pass",
                                  "People match transcript speakers and face counts")
    else:
        people_check = _seeded_entry(scene, "people_consistency") or _check(
            "people_consistency", "pass",
            "No face annotations; no consistency claim to check")

    # temporal_sanity: start <= end, lines ordered, inside window, no overlap.
    start = _parse_ts(scene.get("start_ts"))
    end = _parse_ts(scene.get("end_ts"))
    problems = []
    if start is None or end is None:
        problems.append("scene timestamps missing or unparsable")
    elif start > end:
        problems.append("start_ts is after end_ts")
    prev = None
    for line in lines:
        line_start, line_end = _parse_ts(line.get("start_ts")), _parse_ts(line.get("end_ts"))
        if line_start is None or line_end is None:
            continue
        if prev is not None and line_start < prev[0]:
            problems.append("transcript lines out of order")
        if prev is not None and line_start < prev[1]:
            problems.append("transcript lines overlap")
        if start is not None and line_start < start:
            problems.append("transcript line starts before scene window")
        if end is not None and line_end > end:
            problems.append("transcript line ends after scene window")
        prev = (line_start, line_end)
    if problems:
        temporal = _check("temporal_sanity", "fail", "; ".join(dict.fromkeys(problems)))
    else:
        temporal = _check("temporal_sanity", "pass", "Timestamps in order")
    return [alignment, grounding, people_check, temporal]


# -- per-answer ------------------------------------------------------------

def critique_answer(query, answer, receipts, scenes):
    """Three checks -> [{check, result, note}], in contract order."""
    receipts = receipts or []
    by_id = {s.get("id"): s for s in (scenes or []) if s.get("id")}
    no_record = _normalize(answer) == _normalize(_NO_RECORD)

    unknown = [r.get("scene_id") for r in receipts if r.get("scene_id") not in by_id]
    if no_record:
        coverage = _check("receipt_coverage", "pass",
                          "No-record fallback needs no receipts")
    elif not receipts:
        coverage = _check("receipt_coverage", "fail",
                          "Factual claims present but no receipts")
    elif unknown:
        coverage = _check("receipt_coverage", "fail",
                          "Receipts point to unknown scenes: %s" % ", ".join(unknown))
    else:
        coverage = _check("receipt_coverage", "pass",
                          "%d receipt(s) map to known scenes" % len(receipts))

    failures = []
    for receipt in receipts:
        scene = by_id.get(receipt.get("scene_id"))
        quote = receipt.get("quote") or ""
        if scene is None:
            failures.append("%s (unknown scene)" % receipt.get("scene_id"))
            continue
        if not quote:
            continue
        lines = _transcript_lines(scene)
        best = max((_fuzzy(quote, line["text"]) for line in lines),
                   default=0.0)
        joined = max(best, _fuzzy(quote, _transcript_text(scene)))
        if joined < FUZZY_THRESHOLD:
            failures.append("%s (fuzzy %.2f)" % (receipt.get("scene_id"), joined))
    if failures:
        verbatim = _check("verbatim_quotes", "fail",
                          "Quotes not supported by transcript: %s" % "; ".join(failures))
    else:
        verbatim = _check("verbatim_quotes", "pass",
                          "All receipt quotes match their transcripts")

    if no_record:
        relevance = _check("relevance", "pass", "No-record fallback")
    else:
        query_tokens = set(_tokens(query))
        answer_tokens = set(_tokens(answer))
        for receipt in receipts:
            answer_tokens |= set(_tokens(receipt.get("quote") or ""))
        if not query_tokens:
            relevance = _check("relevance", "pass", "Empty query")
        else:
            ratio = len(query_tokens & answer_tokens) / len(query_tokens)
            if ratio >= RELEVANCE_FLOOR:
                relevance = _check("relevance", "pass",
                                   "Query token coverage %.2f" % ratio)
            else:
                relevance = _check("relevance", "fail",
                                   "Answer does not address the query "
                                   "(token coverage %.2f)" % ratio)
    return [coverage, verbatim, relevance]


# -- day-level ---------------------------------------------------------------

def scan_day(scenes, facts, followups):
    """Contradiction + open-loop entries for the Day Digest.

    Returns both plural and singular keys (same lists) because the
    locked interface names the entries "contradiction + open_loop"
    without fixing plurality.
    """
    facts = facts or []
    followups = followups or []
    contradictions = []
    for i, first in enumerate(facts):
        actors_first = set(first.get("actors") or [])
        text_first = _normalize(first.get("text") or "")
        days_first = {d for d in _DAYS if d in text_first.split()}
        for second in facts[i + 1:]:
            if not (actors_first & set(second.get("actors") or [])):
                continue
            text_second = _normalize(second.get("text") or "")
            days_second = {d for d in _DAYS if d in text_second.split()}
            shared = set(_tokens(first.get("text") or "")) & \
                set(_tokens(second.get("text") or ""))
            shared -= days_first | days_second
            conflict = None
            if days_first and days_second and days_first != days_second and shared:
                conflict = "conflicting days %s vs %s" % (
                    sorted(days_first), sorted(days_second))
            else:
                for left, right in _OPPOSING_PAIRS:
                    if left in text_first and right in text_second:
                        conflict = "'%s' vs '%s'" % (left, right)
                        break
                    if right in text_first and left in text_second:
                        conflict = "'%s' vs '%s'" % (right, left)
                        break
            if conflict:
                contradictions.append({
                    "type": "contradiction",
                    "actor": sorted(actors_first & set(second.get("actors") or []))[0],
                    "facts": [first.get("id"), second.get("id")],
                    "note": conflict,
                })

    open_loops = []
    for fact in facts:
        if not _PROMISE_RE.search(fact.get("text") or ""):
            continue
        covered = False
        for followup in followups:
            if followup.get("status") not in ("pending", "approved"):
                continue
            if followup.get("scene_id") and followup.get("scene_id") == fact.get("scene_id"):
                covered = True
                break
            overlap = set(_tokens(followup.get("promise") or "")) & \
                set(_tokens(fact.get("text") or ""))
            denom = max(1, len(set(_tokens(fact.get("text") or ""))))
            if overlap and len(overlap) / denom >= TOKEN_COVERAGE_FLOOR:
                covered = True
                break
        if not covered:
            open_loops.append({
                "type": "open_loop",
                "fact_id": fact.get("id"),
                "actor": (fact.get("actors") or [None])[0],
                "text": fact.get("text"),
                "scene_id": fact.get("scene_id"),
                "note": "Promise with no pending/approved follow-up",
            })
    return {"contradictions": contradictions, "open_loops": open_loops,
            "contradiction": contradictions, "open_loop": open_loops}


# -- fix policy ---------------------------------------------------------------

def decide_fix(critique, kind="scene", rerun=False):
    """Pure fix decision: {action, constraints, regenerate_once}.

    All pass -> keep. Any fail -> downgrade (scene confidence -> review;
    answer -> verified subset only) plus constraints = failed checks with
    notes for a re-run prompt. `rerun=True` means a re-run already
    happened and still fails -> needs_review (scene routed out of
    memory; answer falls back to no-record). Per-answer: at most one
    regenerate, so a first-failure answer carries regenerate_once=True
    and a re-run failure carries False, never an unverified answer.
    """
    failed = [c for c in (critique or []) if c.get("result") != "pass"]
    if not failed:
        return {"action": "keep", "constraints": [], "regenerate_once": False}
    constraints = [{"check": c.get("check"), "note": c.get("note", "")}
                   for c in failed]
    if rerun:
        return {"action": "needs_review", "constraints": constraints,
                "regenerate_once": False}
    return {"action": "downgrade", "constraints": constraints,
            "regenerate_once": kind == "answer"}
