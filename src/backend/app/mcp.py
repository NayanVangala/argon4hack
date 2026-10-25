"""MCP tools for Scene (module 6).

Plain functions over the store, no transport knowledge: no JSON-RPC,
no stdio, no SSE. A future transport only lists TOOL_SCHEMAS and
dispatches call_tool(store, name, arguments).

Locked contract: INTERFACES.md (MCP section). Where plan 06 disagreed
with INTERFACES.md, INTERFACES.md wins; see DEVIATIONS in the module
docstring notes at the bottom of this file.

Rules enforced here:
- Read-only: only get_scene, list_scenes_today (paged to exhaustion),
  list_scenes_by_person, list_people, list_facts are ever called.
- Every return is a copy.deepcopy of store data.
- Tools never raise for bad input: bad input -> {"error":
  {"code": "invalid_argument", ...}}, unknown scene id ->
  {"error": {"code": "scene_not_found", ...}}, unknown tool ->
  {"error": {"code": "unknown_tool", ...}}.
- Every result item carries scene_id + timestamp (error dicts excepted).
- search_scenes uses keyword/token ranking as the phase-1 stand-in for
  embedding retrieval; the swap happens inside search_scenes only.
"""

import copy
import re
from datetime import datetime, timezone

__all__ = [
    "search_scenes",
    "get_scene",
    "list_people",
    "list_interactions_with_person",
    "get_facts",
    "TOOLS",
    "TOOL_SCHEMAS",
    "call_tool",
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SUMMARY_FIELDS = (
    "id", "start_ts", "end_ts", "summary", "quote", "thumb_url",
    "type", "verified", "confidence",
)

_DETAIL_FIELDS = (
    "id", "session_id", "start_ts", "end_ts", "summary", "objects",
    "people", "actions", "visible_text", "type", "confidence",
    "critique", "transcript", "keyframes", "pinned",
)

_PERSON_FIELDS = (
    "id", "name", "photo_thumb", "last_seen", "scene_count",
    "quote_count", "verified",
)

_FACT_FIELDS = ("id", "text", "scene_id", "actors", "extracted_at")

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _err(code, message):
    return {"error": {"code": code, "message": message}}


def _invalid(message):
    return _err("invalid_argument", message)


def _is_int(value):
    # bool is an int subclass; it is not a valid limit here.
    return isinstance(value, int) and not isinstance(value, bool)


def _clamp_limit(value, default, minimum, maximum):
    """Return (clamped_int, error_dict_or_None)."""
    if value is None:
        return default, None
    if not _is_int(value):
        return None, _invalid("limit must be an integer")
    return max(minimum, min(maximum, value)), None


def _require_nonempty_str(value, field):
    """Return (value, error_dict_or_None)."""
    if not isinstance(value, str) or not value.strip():
        return None, _invalid("%s must be a non-empty string" % field)
    return value, None


def _optional_str(value, field):
    """Return (value_or_None, error_dict_or_None)."""
    if value is None:
        return None, None
    if not isinstance(value, str):
        return None, _invalid("%s must be a string" % field)
    return value, None


def _parse_ts(value):
    """Parse an ISO 8601 string to an aware datetime, or None."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _ts_sort_key(value):
    parsed = _parse_ts(value)
    if parsed is None:
        return datetime.min.replace(tzinfo=timezone.utc)
    return parsed


def _scene_summary(scene):
    """Contract SceneSummary + scene_id/timestamp aliases, deep-copied."""
    scene = copy.deepcopy(scene)
    out = {field: copy.deepcopy(scene.get(field)) for field in _SUMMARY_FIELDS}
    out["scene_id"] = out["id"]
    out["timestamp"] = out["start_ts"]
    return out


def _scene_detail(scene):
    """Contract scene detail + scene_id/timestamp aliases, deep-copied."""
    scene = copy.deepcopy(scene)
    out = {field: copy.deepcopy(scene.get(field)) for field in _DETAIL_FIELDS}
    out["scene_id"] = out["id"]
    out["timestamp"] = out["start_ts"]
    return out


def _all_scenes_newest_first(store):
    """Page list_scenes_today to exhaustion (newest-first)."""
    scenes = []
    before = None
    seen_befores = set()
    while True:
        result = store.list_scenes_today(limit=50, before=before)
        if isinstance(result, tuple):
            page, next_before = result
        else:  # defensive: a store returning just a list
            page, next_before = result, None
        scenes.extend(copy.deepcopy(page) if page else [])
        if not next_before or next_before in seen_befores:
            break
        seen_befores.add(next_before)
        before = next_before
    return scenes


def _scenes_by_person(store, name, limit):
    """Newest-first scenes for a person (case-insensitive match).

    Primary path is the store's list_scenes_by_person; if it comes back
    empty (e.g. a case-sensitive store implementation) fall back to a
    full scan filtered case-insensitively here, so the contract's
    case-insensitive rule holds either way.
    """
    fn = getattr(store, "list_scenes_by_person", None)
    if callable(fn):
        try:
            found = fn(name, limit=limit)
        except TypeError:
            found = fn(name)
        found = copy.deepcopy(found) if found else []
        if found:
            kept = [s for s in found
                    if any(isinstance(p, dict)
                           and str(p.get("name", "")).lower() == name.lower()
                           for p in (s.get("people") or []))]
            # If the store already filtered (usual case), kept == found.
            # If the store returned unfiltered rows, kept is the correction.
            # Only trust kept when it is non-empty; otherwise fall through
            # to the scan so a differently-cased store cannot hide rows.
            if kept:
                return kept[:limit]
    lowered = name.lower()
    out = []
    for scene in _all_scenes_newest_first(store):
        if any(isinstance(p, dict)
               and str(p.get("name", "")).lower() == lowered
               for p in (scene.get("people") or [])):
            out.append(scene)
            if len(out) >= limit:
                break
    return out


def _newest_scene_id_for_person(store, name):
    rows = _scenes_by_person(store, name, limit=1)
    if rows:
        return rows[0].get("id")
    return None


def _tokens(text):
    return [t for t in _TOKEN_RE.findall((text or "").lower()) if len(t) >= 2]


def _scene_search_text(scene):
    parts = [scene.get("summary") or "", scene.get("quote") or ""]
    parts.extend(scene.get("visible_text") or [])
    for line in scene.get("transcript") or []:
        if isinstance(line, dict):
            parts.append(line.get("text") or "")
    for person in scene.get("people") or []:
        if isinstance(person, dict):
            parts.append(person.get("name") or "")
    return " ".join(str(p) for p in parts).lower()


# ---------------------------------------------------------------------------
# Tool functions (store first, then contract arguments)
# ---------------------------------------------------------------------------

def search_scenes(store, query, top_k=8, person=None, since=None):
    query, err = _require_nonempty_str(query, "query")
    if err is not None:
        return err
    top_k, err = _clamp_limit(top_k, 8, 1, 25)
    if err is not None:
        return err
    person, err = _optional_str(person, "person")
    if err is not None:
        return err
    if person is not None and not person.strip():
        return _invalid("person must be a non-empty string")
    since, err = _optional_str(since, "since")
    if err is not None:
        return err
    since_dt = None
    if since is not None:
        since_dt = _parse_ts(since)
        if since_dt is None:
            return _invalid("since must be an ISO 8601 timestamp")

    query_tokens = set(_tokens(query))
    if not query_tokens:
        return _invalid("query must contain searchable text")

    person_lower = person.lower() if person is not None else None
    scored = []
    for scene in _all_scenes_newest_first(store):
        if person_lower is not None:
            names = [str(p.get("name", "")).lower()
                     for p in (scene.get("people") or [])
                     if isinstance(p, dict)]
            if person_lower not in names:
                continue
        if since_dt is not None:
            start = _parse_ts(scene.get("start_ts"))
            if start is None or start < since_dt:
                continue
        haystack = _scene_search_text(scene)
        matches = sum(1 for tok in query_tokens if tok in haystack)
        if matches == 0:
            continue
        scored.append((matches, _ts_sort_key(scene.get("start_ts")), scene))
    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return {"scenes": [_scene_summary(s) for _, _, s in scored[:top_k]]}


def get_scene(store, scene_id):
    scene_id, err = _require_nonempty_str(scene_id, "scene_id")
    if err is not None:
        return err
    scene = store.get_scene(scene_id)
    if scene is None:
        return _err("scene_not_found",
                    "no scene with id %s" % scene_id)
    return _scene_detail(scene)


def list_people(store):
    people = copy.deepcopy(store.list_people() or [])
    out = []
    for person in people:
        item = {field: copy.deepcopy(person.get(field))
                for field in _PERSON_FIELDS}
        name = person.get("name")
        if isinstance(name, str) and (person.get("scene_count") or 0) > 0:
            item["scene_id"] = _newest_scene_id_for_person(store, name)
        else:
            item["scene_id"] = None
        item["timestamp"] = item["last_seen"]
        out.append(item)
    return {"people": out}


def list_interactions_with_person(store, name, limit=10):
    name, err = _require_nonempty_str(name, "name")
    if err is not None:
        return err
    limit, err = _clamp_limit(limit, 10, 1, 50)
    if err is not None:
        return err
    scenes = _scenes_by_person(store, name, limit)
    out = []
    for scene in scenes[:limit]:
        scene = copy.deepcopy(scene)
        out.append({
            "scene_id": scene.get("id"),
            "timestamp": scene.get("start_ts"),
            "summary": scene.get("summary"),
            "type": scene.get("type"),
            "confidence": scene.get("confidence"),
            "verified": scene.get("verified"),
            "quote": scene.get("quote"),
        })
    return {"scenes": out}


def get_facts(store, actor=None, query=None, limit=20):
    actor, err = _optional_str(actor, "actor")
    if err is not None:
        return err
    query, err = _optional_str(query, "query")
    if err is not None:
        return err
    limit, err = _clamp_limit(limit, 20, 1, 50)
    if err is not None:
        return err

    def _matches(fact):
        if actor is not None:
            actors = [str(a).lower() for a in (fact.get("actors") or [])]
            if not any(actor.lower() in a for a in actors):
                return False
        if query is not None:
            if query.lower() not in (fact.get("text") or "").lower():
                return False
        return True

    try:
        facts = store.list_facts(actor=actor, query=query, limit=limit)
    except TypeError:
        facts = store.list_facts(limit=limit)
    facts = copy.deepcopy(facts) if facts else []
    kept = [f for f in facts if _matches(f)]
    if not kept and (actor is not None or query is not None):
        # Store filter may be stricter than the contract (e.g. exact
        # match); re-fetch unfiltered and apply the contract filters here.
        try:
            raw = store.list_facts(limit=50)
        except TypeError:
            raw = store.list_facts()
        kept = [f for f in (copy.deepcopy(raw) if raw else []) if _matches(f)]
    out = []
    for fact in kept[:limit]:
        item = {field: copy.deepcopy(fact.get(field)) for field in _FACT_FIELDS}
        item["timestamp"] = item["extracted_at"]
        out.append(item)
    return {"facts": out}


# ---------------------------------------------------------------------------
# Registry + dispatcher (transport's only entry points)
# ---------------------------------------------------------------------------

TOOLS = {
    "search_scenes": search_scenes,
    "get_scene": get_scene,
    "list_people": list_people,
    "list_interactions_with_person": list_interactions_with_person,
    "get_facts": get_facts,
}

TOOL_SCHEMAS = {
    "search_scenes": {
        "name": "search_scenes",
        "description": "Search the wearer's recorded scenes by natural language. "
                       "Returns scenes with timestamps. Always cite scene_id "
                       "and timestamp for any claim.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Natural language question, e.g. 'what did Maya promise'",
                },
                "top_k": {"type": "integer", "default": 8,
                          "minimum": 1, "maximum": 25},
                "person": {
                    "type": "string",
                    "description": "Filter to scenes with this person",
                },
                "since": {
                    "type": "string",
                    "description": "ISO 8601 lower bound",
                },
            },
            "required": ["query"],
        },
    },
    "get_scene": {
        "name": "get_scene",
        "description": "Full detail for one scene: summary, transcript with "
                       "speakers, keyframes, objects, confidence.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "scene_id": {"type": "string"},
            },
            "required": ["scene_id"],
        },
    },
    "list_people": {
        "name": "list_people",
        "description": "Enrolled speakers with interaction counts and "
                       "last-seen timestamps.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    "list_interactions_with_person": {
        "name": "list_interactions_with_person",
        "description": "Scenes featuring a person, newest first, each with a "
                       "one-line summary and timestamp.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "limit": {"type": "integer", "default": 10,
                          "minimum": 1, "maximum": 50},
            },
            "required": ["name"],
        },
    },
    "get_facts": {
        "name": "get_facts",
        "description": "Durable extracted facts (promises, commitments, "
                       "decisions) with source scenes. Check this first for "
                       "'what did X promise/decide' questions.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "actor": {"type": "string", "description": "Filter by person"},
                "query": {"type": "string",
                          "description": "Keyword filter over fact text"},
                "limit": {"type": "integer", "default": 20,
                          "minimum": 1, "maximum": 50},
            },
        },
    },
}


def call_tool(store, name, arguments):
    if name not in TOOLS:
        return _err("unknown_tool", "no tool named %s" % (name,))
    if arguments is None:
        arguments = {}
    if not isinstance(arguments, dict):
        return _invalid("arguments must be an object")
    try:
        return TOOLS[name](store, **arguments)
    except TypeError as exc:
        # Missing, unexpected, or mistyped keyword arguments: bad input,
        # not a crash. (Tools validate their own values and return
        # invalid_argument dicts; TypeError here means the call shape
        # itself was wrong.)
        return _invalid("bad arguments for %s: %s" % (name, exc))
