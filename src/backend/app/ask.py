"""Ask + facts (module 4).

Built to ~/workspace/scene-backend/INTERFACES.md (locked coordinator
interfaces). Where the module plan (``_plans/04-ask.md``) disagreed with
INTERFACES.md, INTERFACES.md wins; see the deviation note at the bottom
of this docstring.

Stdlib only, plain dicts, no HTTP in this module. Routes stay thin and
serialize the dicts returned here to the contract shapes.

Deviation flagged (built to the locked version anyway): plan section (f)
named Store methods ``get_facts`` / ``get_scenes`` / ``get_transcripts``.
The locked Store surface is ``list_facts(actor, query, limit,
session_id)``, ``list_scenes_for_session(session_id)`` and
``add_spend(amount_usd)``; transcripts live inside the scene dicts, so
this module builds them from ``scene["transcript"]`` instead of a
separate transcript store method.
"""

import difflib
import re
from typing import Protocol

NO_RECORD = "I don't have a record of that."
DEFAULT_SPEND_USD = 0.12
FUZZY_THRESHOLD = 0.80

_PROMISE_ANSWER = "Maya promised to send the Q3 numbers by Friday."
_PROMISE_QUOTE = "I'll send the Q3 numbers by Friday"


def _normalize(text):
    """Lowercase + collapse whitespace, for fuzzy quote matching."""
    return re.sub(r"\s+", " ", str(text).lower()).strip()


def _transcript_lines(scene):
    """Transcript lines of a scene dict, as (text, line-dict) pairs."""
    lines = scene.get("transcript") or []
    out = []
    for line in lines:
        if isinstance(line, dict):
            out.append((line.get("text") or "", line))
        elif isinstance(line, str):
            out.append((line, {"text": line}))
    return out


def _quote_matches_scene(quote, scene):
    """Verbatim or >= 0.80 fuzzy match of ``quote`` against a scene's
    transcript (same rule as the per-answer Critic)."""
    lines = _transcript_lines(scene)
    if not lines:
        return False
    if any(quote and quote in text for text, _ in lines):
        return True
    joined = " ".join(text for text, _ in lines)
    if quote and quote in joined:
        return True
    norm_quote = _normalize(quote)
    if not norm_quote:
        return False
    candidates = [_normalize(text) for text, _ in lines]
    candidates.append(_normalize(joined))
    return any(
        difflib.SequenceMatcher(None, norm_quote, cand).ratio() >= FUZZY_THRESHOLD
        for cand in candidates
    )


class ReasoningBackend(Protocol):
    def reason(self, context, query):
        """Return {"answer", "receipts": [{scene_id, timestamp, quote,
        thumb_url}], "sources": ["fact:<id>" | "scene:<id>"],
        "spend_usd"? (optional)}."""


class FactExtractor(Protocol):
    def extract_facts(self, scene):
        """Return facts [{"id", "text", "scene_id", "actors",
        "extracted_at"}]."""


class MockReasoning:
    """Preserves the old mock exactly: "promise" in query.lower() -> the
    Maya Q3 answer with the promise-scene receipt and fact:/scene:
    sources; anything else -> no-record with empty receipts/sources.
    Spend 0.12. No other query gets a canned answer."""

    def reason(self, context, query):
        if "promise" not in (query or "").lower():
            return {"answer": NO_RECORD, "receipts": [],
                    "sources": [], "spend_usd": 0.12}
        promise_scene = None
        for scene in context.get("scenes") or []:
            if scene.get("quote") == _PROMISE_QUOTE or any(
                    _PROMISE_QUOTE in text
                    for text, _ in _transcript_lines(scene)):
                promise_scene = scene
                break
        if promise_scene is None:
            return {"answer": NO_RECORD, "receipts": [],
                    "sources": [], "spend_usd": 0.12}
        sources = ["scene:%s" % promise_scene["id"]]
        facts = context.get("facts") or []
        if facts:
            sources = ["fact:%s" % facts[0]["id"]] + sources
        return {
            "answer": _PROMISE_ANSWER,
            "receipts": [{
                "scene_id": promise_scene["id"],
                "timestamp": promise_scene.get("start_ts"),
                "quote": _PROMISE_QUOTE,
                "thumb_url": promise_scene.get("thumb_url"),
            }],
            "sources": sources,
            "spend_usd": 0.12,
        }


class MockFactExtractor:
    """Returns the canned fact set unchanged; no extraction runs.

    The canned set is injected at construction (in the real wiring it is
    the seeded fact set); ``extract_facts`` ignores the scene argument
    and returns that set, unmodified, every time."""

    def __init__(self, canned_facts=None):
        self._canned_facts = list(canned_facts) if canned_facts else []

    def extract_facts(self, scene):
        return list(self._canned_facts)


class AskService:
    def __init__(self, store, backend):
        self.store = store
        self.backend = backend

    def build_session_context(self, session_id):
        """{facts, scenes, transcripts}: facts first, then scenes
        chronological, then transcripts in the same scene order, each
        line attached to its scene_id and timestamps. No retrieval, no
        top-K. Empty session yields empty lists, not an error."""
        facts = self._facts_for_session(session_id)
        scenes = list(self.store.list_scenes_for_session(session_id))
        # Locked store already returns oldest-first; sort defensively so
        # the order holds even if a store implementation does not.
        scenes.sort(key=lambda s: s.get("start_ts") or "")
        transcripts = []
        for scene in scenes:
            for _, line in _transcript_lines(scene):
                entry = dict(line)
                entry["scene_id"] = scene.get("id")
                transcripts.append(entry)
        return {"facts": facts, "scenes": scenes, "transcripts": transcripts}

    def _facts_for_session(self, session_id):
        try:
            return list(self.store.list_facts(session_id=session_id))
        except TypeError:
            # Store without the session_id parameter: filter by the
            # session's scene ids instead.
            scene_ids = {
                s.get("id")
                for s in self.store.list_scenes_for_session(session_id)
            }
            return [f for f in self.store.list_facts()
                    if f.get("scene_id") in scene_ids]

    def list_facts(self, actor=None, limit=20):
        """GET /facts contract dict: {"facts": [...]}. Actor filter is
        a case-insensitive substring over ``actors``; stored order is
        preserved and the result is capped at ``limit``."""
        facts = list(self.store.list_facts(actor=actor, limit=limit))
        if actor is not None:
            needle = actor.lower()
            facts = [f for f in facts
                     if any(needle in str(a).lower()
                            for a in (f.get("actors") or []))]
        return {"facts": facts[:limit]}

    def ask(self, query, session_id, top_k=8):
        """POST /ask contract dict: {"answer", "receipts", "sources"}.

        ``top_k`` is accepted and ignored (whole-session context, no
        retrieval). Cite-or-say-no-record is enforced AFTER reason():
        empty receipts+sources force no-record; a receipt whose quote
        does not match its scene's transcript (verbatim or 0.80 fuzzy)
        is dropped; if none remain, fall back to no-record. Spend is
        reason()'s spend_usd when present, else 0.12 flat, on EVERY
        call including no-record answers."""
        _ = top_k  # accepted and ignored by design
        context = self.build_session_context(session_id)
        result = self.backend.reason(context, query)
        answer = result.get("answer") or ""
        receipts = list(result.get("receipts") or [])
        sources = list(result.get("sources") or [])
        if not receipts and not sources:
            answer, receipts, sources = NO_RECORD, [], []
        elif receipts:
            scenes_by_id = {s.get("id"): s
                            for s in context.get("scenes") or []}
            kept = []
            for receipt in receipts:
                scene = scenes_by_id.get(receipt.get("scene_id"))
                if scene is not None and _quote_matches_scene(
                        receipt.get("quote") or "", scene):
                    kept.append(receipt)
            if not kept:
                answer, receipts, sources = NO_RECORD, [], []
            else:
                receipts = kept
        spend = result.get("spend_usd")
        if spend is None:
            spend = DEFAULT_SPEND_USD
        self.store.add_spend(spend)
        return {"answer": answer, "receipts": receipts, "sources": sources}
