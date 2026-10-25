"""Scene backend store (module 3).

Locked interface per ~/workspace/scene-backend/INTERFACES.md (Store section).
Python stdlib only. All records are plain dicts. All timestamps ISO 8601
with offset, all ids UUID v4 strings.

Rules (locked):
- One ``threading.Lock`` guards all mutation (getters copy under it too,
  so a caller can never observe a half-written record).
- Getters return ``None`` on a missing id; mutations targeting a missing
  id raise ``KeyError`` (routes map to 404).
- ``approve_followup`` on a ``needs_review`` draft raises ``ValueError``
  (routes map to 400 ``not_approvable``).
- ``add_scene`` assigns the scene id; scenes are stored newest-first.
- Projections ``scene_summary`` / ``scene_detail`` are pure functions
  with the old mock's field lists. REST detail omits ``quote`` /
  ``verified``; the stored record keeps them.

Creation methods that reference another record (``create_chunk``,
``add_scene``, ``add_fact``, ``create_followup_run``) do NOT validate
the referenced session/scene id: the locked routes resolve those ids
before calling, and Follow-Through may pass a client-supplied session id.
The methods that target an existing id directly (``end_session``,
``update_chunk_status``, ``update_scene``, ``create_pin``,
``update_followup_run_status``, ``approve_followup``,
``dismiss_followup``) raise ``KeyError`` on a missing target.

Seed-only helpers (``_seed_session``, ``_seed_person``) exist so
``seed.py`` can insert the canned session/people rows verbatim (a seed
session is not a live session, and canned people counters cannot be
reached through ``enroll_person`` + ``record_appearance`` alone).
They are not part of the locked interface and no other module calls them.
"""

import copy
import threading
import uuid
from datetime import datetime

__all__ = [
    "InMemoryStore",
    "scene_summary",
    "scene_detail",
    "SUMMARY_FIELDS",
    "DETAIL_FIELDS",
]

SUMMARY_FIELDS = (
    "id", "start_ts", "end_ts", "summary", "quote", "thumb_url",
    "type", "verified", "confidence",
)

DETAIL_FIELDS = (
    "id", "session_id", "start_ts", "end_ts", "summary", "objects",
    "people", "actions", "visible_text", "type", "confidence",
    "critique", "transcript", "keyframes", "pinned",
)

FOLLOWUP_STEPS = ["find_promises", "verify_quotes", "draft_followups"]


def _new_id():
    return str(uuid.uuid4())


def _now():
    """ISO 8601 timestamp with offset, local timezone."""
    return datetime.now().astimezone().isoformat(timespec="seconds")


def scene_summary(scene):
    """SceneSummary projection: the old mock's field list, verbatim."""
    return {k: scene.get(k) for k in SUMMARY_FIELDS}


def scene_detail(scene):
    """Full scene detail projection: the old mock's field list.

    REST detail omits ``quote`` / ``verified`` (contract shape); the
    stored record keeps them.
    """
    return {k: scene.get(k) for k in DETAIL_FIELDS}


class InMemoryStore:
    """In-memory store: dicts keyed by id, one lock, plain dict records."""

    def __init__(self):
        self._lock = threading.Lock()
        self._sessions = {}          # id -> session dict
        self._session_order = []     # ids in creation order
        self._live_session_id = None
        self._today_session_id = None  # seed session id (fallback)
        self._chunks = {}            # id -> chunk dict
        self._scenes = []            # newest-first
        self._scenes_by_id = {}      # id -> scene dict
        self._facts = []             # insertion order
        self._facts_by_id = {}
        self._people = []            # insertion order
        self._people_by_id = {}
        self._pins = []              # insertion order
        self._followup_runs = {}     # run_id -> run dict
        self._followups = []         # insertion order
        self._followups_by_id = {}
        self._spend_usd = 0.0

    # -- internal helpers -------------------------------------------------

    def _get_scene_internal(self, scene_id):
        return self._scenes_by_id.get(scene_id)

    def _session_id_for_fact(self, fact):
        """Resolve a fact's session: explicit field, else its scene."""
        if fact.get("session_id"):
            return fact["session_id"]
        scene = self._scenes_by_id.get(fact.get("scene_id"))
        return scene["session_id"] if scene else None

    # -- seed-only helpers (used by seed.py, not part of locked API) -----

    def _seed_session(self, session):
        """Insert a canned session row without making it live.

        Sets the today-session fallback if none is set yet.
        """
        with self._lock:
            session = copy.deepcopy(session)
            session.setdefault("id", _new_id())
            self._sessions[session["id"]] = session
            self._session_order.append(session["id"])
            if self._today_session_id is None:
                self._today_session_id = session["id"]
            return copy.deepcopy(session)

    def _seed_person(self, person):
        """Insert a canned person row verbatim (counts included)."""
        with self._lock:
            person = copy.deepcopy(person)
            person.setdefault("id", _new_id())
            self._people.append(person)
            self._people_by_id[person["id"]] = person
            return copy.deepcopy(person)

    # -- sessions ---------------------------------------------------------

    def create_session(self):
        with self._lock:
            session = {
                "id": _new_id(),
                "started_at": _now(),
                "ended_at": None,
                "status": "live",
            }
            self._sessions[session["id"]] = session
            self._session_order.append(session["id"])
            self._live_session_id = session["id"]
            if self._today_session_id is None:
                self._today_session_id = session["id"]
            return copy.deepcopy(session)

    def get_session(self, session_id):
        with self._lock:
            session = self._sessions.get(session_id)
            return copy.deepcopy(session) if session is not None else None

    def get_live_session(self):
        with self._lock:
            if self._live_session_id is None:
                return None
            session = self._sessions.get(self._live_session_id)
            return copy.deepcopy(session) if session is not None else None

    def end_session(self, session_id, ended_at=None):
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                raise KeyError(session_id)
            session["ended_at"] = ended_at if ended_at is not None else _now()
            session["status"] = "ended"
            if self._live_session_id == session_id:
                self._live_session_id = None
            return copy.deepcopy(session)

    def current_session_id(self):
        """Live id, else today's seed session id, else None (empty store)."""
        with self._lock:
            if self._live_session_id is not None:
                return self._live_session_id
            return self._today_session_id

    # -- chunks -----------------------------------------------------------

    def create_chunk(self, session_id, start_ts, end_ts, storage_path=None):
        with self._lock:
            chunk = {
                "id": _new_id(),
                "session_id": session_id,
                "start_ts": start_ts,
                "end_ts": end_ts,
                "storage_path": storage_path,
                "status": "received",
            }
            self._chunks[chunk["id"]] = chunk
            return copy.deepcopy(chunk)

    def update_chunk_status(self, chunk_id, status):
        with self._lock:
            chunk = self._chunks.get(chunk_id)
            if chunk is None:
                raise KeyError(chunk_id)
            chunk["status"] = status
            return copy.deepcopy(chunk)

    # -- scenes -----------------------------------------------------------

    def add_scene(self, scene):
        """Store assigns the id; inserts newest-first. Returns the row."""
        with self._lock:
            scene = copy.deepcopy(scene) if scene else {}
            scene_id = _new_id()
            scene["id"] = scene_id
            scene.setdefault("session_id", self._today_session_id)
            if self._live_session_id is not None and not scene.get("session_id"):
                scene["session_id"] = self._live_session_id
            scene.setdefault("start_ts", _now())
            scene.setdefault("end_ts", scene["start_ts"])
            scene.setdefault("summary", "")
            scene.setdefault("quote", "")
            scene.setdefault(
                "thumb_url", "https://cdn.helloscene.xyz/t/%s.jpg" % scene_id)
            scene.setdefault("type", "conversation")
            scene.setdefault("confidence", "review")
            if "verified" not in scene:
                scene["verified"] = scene["confidence"] == "verified"
            scene.setdefault("objects", [])
            scene.setdefault("people", [])
            scene.setdefault("actions", [])
            scene.setdefault("visible_text", [])
            scene.setdefault("critique", [])
            scene.setdefault("transcript", [])
            if not scene.get("keyframes"):
                scene["keyframes"] = [
                    "https://cdn.helloscene.xyz/k/%s/0.jpg" % scene_id]
            scene.setdefault("pinned", False)
            scene.setdefault("embedding_refs", None)
            self._scenes.insert(0, scene)
            self._scenes_by_id[scene_id] = scene
            return copy.deepcopy(scene)

    def get_scene(self, scene_id):
        with self._lock:
            scene = self._scenes_by_id.get(scene_id)
            return copy.deepcopy(scene) if scene is not None else None

    def list_scenes_today(self, limit=50, before=None):
        """Newest-first page; ``next_before`` = last id iff more remain.

        Unknown ``before`` yields an empty page (old-mock semantics).
        """
        with self._lock:
            scenes = self._scenes
            if before is not None:
                idx = next(
                    (i for i, s in enumerate(scenes) if s["id"] == before),
                    None)
                if idx is None:
                    return [], None
                scenes = scenes[idx + 1:]
            if limit is None:
                limit = 50
            if limit < 0:
                limit = 0
            page = scenes[:limit]
            next_before = page[-1]["id"] if len(scenes) > limit else None
            return copy.deepcopy(page), next_before

    def list_scenes_for_session(self, session_id):
        """Oldest-first, for Ask context building."""
        with self._lock:
            scenes = [s for s in self._scenes
                      if s.get("session_id") == session_id]
            return copy.deepcopy(list(reversed(scenes)))

    def list_scenes_by_person(self, name, limit=10):
        """Newest-first scenes featuring ``name`` (case-insensitive)."""
        with self._lock:
            wanted = (name or "").lower()
            out = []
            for scene in self._scenes:
                if any((p.get("name") or "").lower() == wanted
                       for p in scene.get("people") or []):
                    out.append(scene)
                    if limit is not None and len(out) >= limit:
                        break
            return copy.deepcopy(out)

    def update_scene(self, scene_id, **fields):
        """Critique / confidence / pinned updates. Id is never changed."""
        with self._lock:
            scene = self._scenes_by_id.get(scene_id)
            if scene is None:
                raise KeyError(scene_id)
            fields.pop("id", None)
            scene.update(fields)
            return copy.deepcopy(scene)

    def set_scene_pinned(self, scene_id, pinned=True):
        """Plan-03 alias for ``update_scene(scene_id, pinned=pinned)``.

        Not part of the locked interface; kept so plan-03 callers still
        work. Locked callers use ``update_scene``.
        """
        return self.update_scene(scene_id, pinned=pinned)

    # -- facts ------------------------------------------------------------

    def add_fact(self, fact):
        with self._lock:
            fact = copy.deepcopy(fact) if fact else {}
            fact.setdefault("id", _new_id())
            fact.setdefault("text", "")
            fact.setdefault("scene_id", None)
            fact.setdefault("actors", [])
            fact.setdefault("extracted_at", _now())
            self._facts.append(fact)
            self._facts_by_id[fact["id"]] = fact
            return copy.deepcopy(fact)

    def list_facts(self, actor=None, query=None, limit=20, session_id=None):
        with self._lock:
            out = self._facts
            if actor:
                wanted = actor.lower()
                out = [f for f in out
                       if any(wanted in (a or "").lower()
                              for a in f.get("actors") or [])]
            if query:
                wanted = query.lower()
                out = [f for f in out if wanted in (f.get("text") or "").lower()]
            if session_id is not None:
                out = [f for f in out
                       if self._session_id_for_fact(f) == session_id]
            if limit is not None:
                out = out[:limit]
            return copy.deepcopy(out)

    # -- people -----------------------------------------------------------

    def enroll_person(self, name, photo_thumb=None):
        with self._lock:
            person = {
                "id": _new_id(),
                "name": name,
                "photo_thumb": photo_thumb
                if photo_thumb is not None
                else "https://cdn.helloscene.xyz/p/enrolled.jpg",
                "last_seen": _now(),
                "scene_count": 0,
                "quote_count": 0,
                "verified": True,
            }
            self._people.append(person)
            self._people_by_id[person["id"]] = person
            return copy.deepcopy(person)

    def list_people(self):
        with self._lock:
            return copy.deepcopy(self._people)

    def get_person_by_name(self, name):
        with self._lock:
            for person in self._people:
                if person.get("name") == name:
                    return copy.deepcopy(person)
            return None

    def record_appearance(self, name, last_seen, quote=False):
        """Bump counters; creates an unverified row if the name is unseen."""
        with self._lock:
            person = next(
                (p for p in self._people if p.get("name") == name), None)
            if person is None:
                person = {
                    "id": _new_id(),
                    "name": name,
                    "photo_thumb": None,
                    "last_seen": last_seen,
                    "scene_count": 0,
                    "quote_count": 0,
                    "verified": False,
                }
                self._people.append(person)
                self._people_by_id[person["id"]] = person
            person["last_seen"] = last_seen
            person["scene_count"] += 1
            if quote:
                person["quote_count"] += 1
            return None

    # -- pins -------------------------------------------------------------

    def create_pin(self, scene_id, note=None):
        with self._lock:
            scene = self._scenes_by_id.get(scene_id)
            if scene is None:
                raise KeyError(scene_id)
            scene["pinned"] = True
            pin = {"pin_id": _new_id(), "scene_id": scene_id, "note": note}
            self._pins.append(pin)
            return copy.deepcopy(pin)

    def list_pins(self):
        with self._lock:
            return copy.deepcopy(self._pins)

    # -- followups --------------------------------------------------------

    def create_followup_run(self, session_id=None):
        with self._lock:
            if session_id is None:
                session_id = self._live_session_id or self._today_session_id
            run = {
                "run_id": _new_id(),
                "status": "running",
                "steps": list(FOLLOWUP_STEPS),
                "session_id": session_id,
            }
            self._followup_runs[run["run_id"]] = run
            return copy.deepcopy(run)

    def get_followup_run(self, run_id):
        with self._lock:
            run = self._followup_runs.get(run_id)
            return copy.deepcopy(run) if run is not None else None

    def update_followup_run_status(self, run_id, status):
        with self._lock:
            run = self._followup_runs.get(run_id)
            if run is None:
                raise KeyError(run_id)
            run["status"] = status
            return copy.deepcopy(run)

    def add_followup(self, followup):
        with self._lock:
            followup = copy.deepcopy(followup) if followup else {}
            followup.setdefault("id", _new_id())
            followup.setdefault("run_id", None)
            followup.setdefault("promise", "")
            followup.setdefault("person", "")
            followup.setdefault("quote", "")
            followup.setdefault("quote_verified", False)
            followup.setdefault("verified_at", None)
            followup.setdefault("draft", "")
            followup.setdefault("status", "pending")
            followup.setdefault("scene_id", None)
            self._followups.append(followup)
            self._followups_by_id[followup["id"]] = followup
            return copy.deepcopy(followup)

    def get_followup(self, followup_id):
        with self._lock:
            followup = self._followups_by_id.get(followup_id)
            return copy.deepcopy(followup) if followup is not None else None

    def list_followups(self, run_id=None, status=None):
        with self._lock:
            out = self._followups
            if run_id is not None:
                out = [f for f in out if f.get("run_id") == run_id]
            if status is not None:
                out = [f for f in out if f.get("status") == status]
            return copy.deepcopy(out)

    def approve_followup(self, followup_id):
        with self._lock:
            followup = self._followups_by_id.get(followup_id)
            if followup is None:
                raise KeyError(followup_id)
            if followup.get("status") == "needs_review":
                raise ValueError(followup_id)
            followup["status"] = "approved"
            return copy.deepcopy(followup)

    def dismiss_followup(self, followup_id):
        """Any status -> dismissed (mock parity)."""
        with self._lock:
            followup = self._followups_by_id.get(followup_id)
            if followup is None:
                raise KeyError(followup_id)
            followup["status"] = "dismissed"
            return copy.deepcopy(followup)

    # -- spend + status ---------------------------------------------------

    def add_spend(self, amount_usd):
        with self._lock:
            # Money: keep the counter at 2dp so 1.84 + 0.07 == 1.91 exactly.
            self._spend_usd = round(self._spend_usd + amount_usd, 2)
            return self._spend_usd

    def get_spend(self):
        with self._lock:
            return round(self._spend_usd, 2)

    def status_snapshot(self):
        with self._lock:
            session_id = self._live_session_id or self._today_session_id
            return {
                "recording": self._live_session_id is not None,
                "session_id": session_id,
                "scene_count": len(self._scenes),
                "last_scene_ts": self._scenes[0]["start_ts"]
                if self._scenes else None,
                "spend_usd": round(self._spend_usd, 2),
            }
