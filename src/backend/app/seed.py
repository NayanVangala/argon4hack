"""Canned seed data (module 3) — the old mock's data, verbatim.

``seed(store)`` builds one today session, then the old mock's 8 scenes
in chronological order (``add_scene`` inserts newest-first, so the
stored list ends up newest-first, exactly like the mock), 3 facts,
2 people, spend 1.84, live session ``None``, pins/followups empty.
The pinned flag on the 09:15 promise scene is seed state, not a pin
record.

Timestamps are the mock's hackathon-day PDT stamps (2026-10-25).
Critique notes are the mock's: all-pass scenes carry the descriptive
notes; the one failing scene (09:42, ``visual_grounding`` fail, "Face
partially occluded in keyframe") carries "Check passed" on its passing
checks, because the mock built it with no notes argument.

Runs exactly once per store (fresh store per process/test; no re-seed
guard, per plan 03).
"""

try:
    from app.store import InMemoryStore  # package import (server wiring)
except ImportError:  # pragma: no cover - direct-file / relative fallback
    try:
        from .store import InMemoryStore
    except ImportError:
        from store import InMemoryStore

from datetime import datetime, timedelta, timezone

PDT = timezone(timedelta(hours=-7))  # hackathon day offset, matches mock


def ts(hour, minute):
    """ISO 8601 timestamp on hackathon day (2026-10-25) in PDT."""
    return datetime(2026, 10, 25, hour, minute, tzinfo=PDT).isoformat(
        timespec="seconds")


def _critique_all_pass():
    return [
        {"check": "transcript_alignment", "result": "pass",
         "note": "Key claims appear in transcript"},
        {"check": "visual_grounding", "result": "pass",
         "note": "Keyframe matches scene description"},
        {"check": "people_consistency", "result": "pass",
         "note": "Speaker matches enrolled print"},
        {"check": "temporal_sanity", "result": "pass",
         "note": "Timestamps in order"},
    ]


def _critique_failing_visual():
    # Mock built this one with fails= only, so passing checks read
    # "Check passed" (the mock's default note).
    return [
        {"check": "transcript_alignment", "result": "pass",
         "note": "Check passed"},
        {"check": "visual_grounding", "result": "fail",
         "note": "Face partially occluded in keyframe"},
        {"check": "people_consistency", "result": "pass",
         "note": "Check passed"},
        {"check": "temporal_sanity", "result": "pass",
         "note": "Check passed"},
    ]


def _tline(speaker, text, start, end):
    return {"speaker": speaker, "text": text, "start_ts": start, "end_ts": end}


def seed(store):
    """Seed ``store`` with the old mock's canned data. Returns the session."""
    import uuid

    session = store._seed_session({
        "id": str(uuid.uuid4()),
        "started_at": ts(0, 0),
        "ended_at": None,
        "status": "ended",
    })
    session_id = session["id"]

    # Chronological seed; add_scene inserts newest-first.
    specs = [
        dict(start=ts(9, 15), end=ts(9, 15),
             summary="Maya explaining Q3 numbers at the whiteboard",
             quote="I'll send the Q3 numbers by Friday",
             stype="conversation", confidence="verified",
             people=[{"name": "Maya", "confidence": "verified"}],
             objects=["whiteboard", "laptop", "coffee cup"],
             actions=["pointing", "talking"],
             visible_text=["Q3 revenue $4.2M"],
             transcript=[_tline("Maya", "I'll send the Q3 numbers by Friday",
                                ts(9, 15), ts(9, 15))],
             pinned=True, critique=_critique_all_pass()),
        dict(start=ts(9, 42), end=ts(9, 42),
             summary="Unknown speaker asks about the demo flow",
             quote="So the demo starts with the glasses, right?",
             stype="conversation", confidence="review",
             people=[{"name": "Unknown", "confidence": "review"}],
             objects=["laptop"], actions=["talking"], visible_text=[],
             transcript=[_tline("Unknown",
                                "So the demo starts with the glasses, right?",
                                ts(9, 42), ts(9, 42))],
             pinned=False, critique=_critique_failing_visual()),
        dict(start=ts(10, 5), end=ts(10, 5),
             summary="Maya sketches the Ask flow on a napkin",
             quote="Ask loads the whole day, no retrieval step",
             stype="action", confidence="verified",
             people=[{"name": "Maya", "confidence": "verified"}],
             objects=["napkin", "pen"], actions=["sketching", "talking"],
             visible_text=["Ask -> whole day"],
             transcript=[_tline("Maya",
                                "Ask loads the whole day, no retrieval step",
                                ts(10, 5), ts(10, 5))],
             pinned=False, critique=_critique_all_pass()),
        dict(start=ts(10, 31), end=ts(10, 31),
             summary="Hallway, no conversation",
             quote="",
             stype="location", confidence="silence",
             people=[], objects=[], actions=[], visible_text=[],
             transcript=[], pinned=False, critique=_critique_all_pass()),
        dict(start=ts(11, 2), end=ts(11, 2),
             summary="Maya reviews the pitch rubric",
             quote="Live demo is half the score",
             stype="conversation", confidence="verified",
             people=[{"name": "Maya", "confidence": "verified"}],
             objects=["laptop"], actions=["talking"],
             visible_text=["Demo 50%"],
             transcript=[_tline("Maya", "Live demo is half the score",
                                ts(11, 2), ts(11, 2))],
             pinned=False, critique=_critique_all_pass()),
        dict(start=ts(11, 20), end=ts(11, 20),
             summary="Maya whiteboards the Scene pipeline",
             quote="The whole day goes into one context, no retrieval step",
             stype="conversation", confidence="verified",
             people=[{"name": "Maya", "confidence": "verified"}],
             objects=["whiteboard", "marker"],
             actions=["pointing", "talking"],
             visible_text=["chunk -> scene -> Ask"],
             transcript=[_tline(
                 "Maya",
                 "The whole day goes into one context, no retrieval step",
                 ts(11, 20), ts(11, 20))],
             pinned=False, critique=_critique_all_pass()),
        dict(start=ts(11, 48), end=ts(11, 48),
             summary="Unknown speaker asks about the demo flow",
             quote="And the dashboard is just backup?",
             stype="conversation", confidence="review",
             people=[{"name": "Unknown", "confidence": "review"}],
             objects=["laptop"], actions=["talking"], visible_text=[],
             transcript=[_tline("Unknown", "And the dashboard is just backup?",
                                ts(11, 48), ts(11, 48))],
             pinned=False, critique=_critique_all_pass()),
        dict(start=ts(12, 10), end=ts(12, 10),
             summary="Maya confirms the Friday deadline",
             quote="Yes, Friday, end of day, I promise",
             stype="quote", confidence="verified",
             people=[{"name": "Maya", "confidence": "verified"}],
             objects=["phone"], actions=["talking"], visible_text=[],
             transcript=[_tline("Maya", "Yes, Friday, end of day, I promise",
                                ts(12, 10), ts(12, 10))],
             pinned=False, critique=_critique_all_pass()),
    ]

    added = []
    for spec in specs:
        scene = {
            "session_id": session_id,
            "start_ts": spec["start"],
            "end_ts": spec["end"],
            "summary": spec["summary"],
            "quote": spec["quote"],
            "type": spec["stype"],
            "confidence": spec["confidence"],
            "objects": spec["objects"],
            "people": spec["people"],
            "actions": spec["actions"],
            "visible_text": spec["visible_text"],
            "critique": spec["critique"],
            "transcript": spec["transcript"],
            "pinned": spec["pinned"],
            "embedding_refs": None,
            # thumb_url / keyframes are filled by add_scene from the
            # store-assigned id, matching the mock's cdn pattern.
        }
        added.append(store.add_scene(scene))

    # Chronological index: added[0] = 09:15 promise, [4] = 11:02,
    # [5] = 11:20, [1] = 09:42.
    store.add_fact({
        "text": "Maya promised Q3 numbers by Friday",
        "scene_id": added[0]["id"], "actors": ["Maya"],
        "extracted_at": ts(9, 15),
    })
    store.add_fact({
        "text": "Maya decided the demo leads with glasses, not the dashboard",
        "scene_id": added[5]["id"], "actors": ["Maya"],
        "extracted_at": ts(11, 20),
    })
    store.add_fact({
        "text": "Live demo is 50 percent of the judging score",
        "scene_id": added[4]["id"], "actors": ["Maya"],
        "extracted_at": ts(11, 2),
    })

    store._seed_person({
        "name": "Maya",
        "photo_thumb": "https://cdn.helloscene.xyz/p/maya.jpg",
        "last_seen": ts(12, 10), "scene_count": 5, "quote_count": 6,
        "verified": True,
    })
    store._seed_person({
        "name": "Unknown",
        "photo_thumb": "https://cdn.helloscene.xyz/p/unknown.jpg",
        "last_seen": ts(11, 48), "scene_count": 2, "quote_count": 0,
        "verified": False,
    })

    store.add_spend(1.84)
    # Live session stays None; current_session_id() falls back to this one.
    return session
