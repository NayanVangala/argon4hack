"""Postgres-backed store for the Scene backend.

Same method names and signatures as ``InMemoryStore`` in ``store.py``
and ``SQLiteStore`` in ``sqlite_store.py``, same record shapes, same
edge-case semantics. Only the storage changes: records live in Postgres
(via psycopg v3, the single added dependency for this module) instead
of in-process dicts or a SQLite file, so data survives a server restart
and can be shared.

Design notes (see /tmp/scene-data-design.md, sections 1-3):
- One table per record kind, mirroring SQLite. Each row carries the
  record's key in an ``id`` column (pins use their ``pin_id``,
  followup runs their ``run_id``), an insertion-order ``seq`` column
  (BIGSERIAL), and the full record as JSONB in ``data``. Storing the
  whole dict as JSONB means ``update_scene`` can carry arbitrary fields
  exactly like the in-memory version, with no column migration per
  field. There are NO foreign key constraints, exactly as in SQLite:
  creation methods do not validate referenced session/scene ids.
- List methods load the rows in insertion order and then run the exact
  same Python filtering/slicing logic as ``InMemoryStore``. No WHERE
  clause filters on JSONB fields.
- A ``meta`` table holds the state ``InMemoryStore`` kept as
  attributes: ``live_session_id``, ``today_session_id``, and the global
  ``spend_usd`` counter (stored as ``repr(float_total)``).
- One ``threading.RLock`` guards all access and a single connection is
  shared, mirroring SQLite's one-lock rule. Every mutation commits
  immediately, per statement (not per call).
- ``database_url`` is passed verbatim to psycopg and is never printed,
  logged, or included in error messages. ``database_url=None`` (or
  empty) fails fast with ``ValueError``; it never silently falls back
  to another store.

Quirks preserved on purpose (do not fix here; a fix must land in all
three stores together under a lock change):
- ``list_scenes_today(limit=0)`` on a non-empty store raises
  ``IndexError`` (``page[-1]`` on an empty page when more rows remain).
  This implementation runs the same code path, so it raises the same
  way.
- ``add_scene`` session_id setdefault order: the today id first, the
  live id only if the result is still falsy.
- ``create_pin`` commits each statement separately, so a crash between
  the scene save and the pin insert can leave a pinned scene with no
  pin row.
- Spend stays at 2dp: ``add_spend`` and ``get_spend`` round to 2dp.

Seed-only helpers ``_seed_session`` / ``_seed_person`` and the
``set_scene_pinned`` alias are mirrored so ``seed.py`` runs unchanged.
Extra method, not part of the locked interface: ``is_empty()`` reports
whether every record table is empty (seed-on-empty rule in server.py).
"""

import copy
import threading
import uuid
from datetime import datetime

import psycopg
from psycopg.types.json import Jsonb

try:
    from app.store import FOLLOWUP_STEPS
except ImportError:  # pragma: no cover - direct-file / relative fallback
    try:
        from .store import FOLLOWUP_STEPS
    except ImportError:
        from store import FOLLOWUP_STEPS

__all__ = ["PostgresStore"]

# table -> key field on the stored dict (pins/runs use a non-"id" key)
_TABLES = (
    "sessions",
    "chunks",
    "scenes",
    "facts",
    "people",
    "pins",
    "followup_runs",
    "followups",
)

_KEY_FIELD = {
    "sessions": "id",
    "chunks": "id",
    "scenes": "id",
    "facts": "id",
    "people": "id",
    "pins": "pin_id",
    "followup_runs": "run_id",
    "followups": "id",
}

# DDL identical to ~/workspace/scene-backend/schema.sql. Executed
# statement by statement on init (psycopg uses the extended query
# protocol, which does not reliably accept multi-statement strings).
_SCHEMA_SQL = """CREATE TABLE IF NOT EXISTS sessions (
  seq BIGSERIAL PRIMARY KEY,
  id TEXT NOT NULL UNIQUE,
  data JSONB NOT NULL
);
CREATE TABLE IF NOT EXISTS chunks (
  seq BIGSERIAL PRIMARY KEY,
  id TEXT NOT NULL UNIQUE,
  data JSONB NOT NULL
);
CREATE TABLE IF NOT EXISTS scenes (
  seq BIGSERIAL PRIMARY KEY,
  id TEXT NOT NULL UNIQUE,
  data JSONB NOT NULL
);
CREATE TABLE IF NOT EXISTS facts (
  seq BIGSERIAL PRIMARY KEY,
  id TEXT NOT NULL UNIQUE,
  data JSONB NOT NULL
);
CREATE TABLE IF NOT EXISTS people (
  seq BIGSERIAL PRIMARY KEY,
  id TEXT NOT NULL UNIQUE,
  data JSONB NOT NULL
);
CREATE TABLE IF NOT EXISTS pins (
  seq BIGSERIAL PRIMARY KEY,
  id TEXT NOT NULL UNIQUE,  -- stores the pin dict's pin_id
  data JSONB NOT NULL
);
CREATE TABLE IF NOT EXISTS followup_runs (
  seq BIGSERIAL PRIMARY KEY,
  id TEXT NOT NULL UNIQUE,  -- stores the run dict's run_id
  data JSONB NOT NULL
);
CREATE TABLE IF NOT EXISTS followups (
  seq BIGSERIAL PRIMARY KEY,
  id TEXT NOT NULL UNIQUE,
  data JSONB NOT NULL
);
CREATE TABLE IF NOT EXISTS meta (
  key TEXT PRIMARY KEY,
  value TEXT  -- nullable: a cleared live_session_id is stored as NULL
);
"""


def _new_id():
    return str(uuid.uuid4())


def _now():
    """ISO 8601 timestamp with offset, local timezone."""
    return datetime.now().astimezone().isoformat(timespec="seconds")


class PostgresStore:
    """Postgres store: same interface as InMemoryStore, durable in Postgres."""

    def __init__(self, database_url=None):
        if not database_url:
            raise ValueError("PostgresStore requires a database_url")
        self._lock = threading.RLock()
        self._conn = psycopg.connect(database_url)
        with self._lock:
            with self._conn.cursor() as cur:
                for statement in _SCHEMA_SQL.split(";"):
                    statement = statement.strip()
                    if statement:
                        cur.execute(statement)
            self._conn.commit()

    # -- internal helpers (called with the lock held) --------------------

    def _insert(self, table, record):
        key = record[_KEY_FIELD[table]]
        with self._conn.cursor() as cur:
            cur.execute(
                "INSERT INTO %s (id, data) VALUES (%%s, %%s)" % table,
                (key, Jsonb(record)))
        self._conn.commit()

    def _save(self, table, record):
        key = record[_KEY_FIELD[table]]
        with self._conn.cursor() as cur:
            cur.execute(
                "UPDATE %s SET data = %%s WHERE id = %%s" % table,
                (Jsonb(record), key))
        self._conn.commit()

    def _get(self, table, key):
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT data FROM %s WHERE id = %%s" % table, (key,))
            row = cur.fetchone()
        return row[0] if row is not None else None

    def _all(self, table, newest_first=False):
        order = "seq DESC" if newest_first else "seq ASC"
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT data FROM %s ORDER BY %s" % (table, order))
            rows = cur.fetchall()
        return [r[0] for r in rows]

    def _count(self, table):
        with self._conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM %s" % table)
            row = cur.fetchone()
        return row[0]

    def _meta_get(self, key):
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT value FROM meta WHERE key = %s", (key,))
            row = cur.fetchone()
        return row[0] if row is not None else None

    def _meta_set(self, key, value):
        with self._conn.cursor() as cur:
            cur.execute(
                "INSERT INTO meta (key, value) VALUES (%s, %s) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value))
        self._conn.commit()

    def _session_id_for_fact(self, fact):
        """Resolve a fact's session: explicit field, else its scene."""
        if fact.get("session_id"):
            return fact["session_id"]
        scene = self._get("scenes", fact.get("scene_id"))
        return scene["session_id"] if scene else None

    def is_empty(self):
        """True iff every record table is empty (seed-on-empty rule)."""
        with self._lock:
            return all(self._count(t) == 0 for t in _TABLES)

    # -- seed-only helpers (used by seed.py, not part of locked API) -----

    def _seed_session(self, session):
        """Insert a canned session row without making it live.

        Sets the today-session fallback if none is set yet.
        """
        with self._lock:
            session = copy.deepcopy(session)
            session.setdefault("id", _new_id())
            self._insert("sessions", session)
            if self._meta_get("today_session_id") is None:
                self._meta_set("today_session_id", session["id"])
            return copy.deepcopy(session)

    def _seed_person(self, person):
        """Insert a canned person row verbatim (counts included)."""
        with self._lock:
            person = copy.deepcopy(person)
            person.setdefault("id", _new_id())
            self._insert("people", person)
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
            self._insert("sessions", session)
            self._meta_set("live_session_id", session["id"])
            if self._meta_get("today_session_id") is None:
                self._meta_set("today_session_id", session["id"])
            return copy.deepcopy(session)

    def get_session(self, session_id):
        with self._lock:
            session = self._get("sessions", session_id)
            return copy.deepcopy(session) if session is not None else None

    def get_live_session(self):
        with self._lock:
            live_id = self._meta_get("live_session_id")
            if live_id is None:
                return None
            session = self._get("sessions", live_id)
            return copy.deepcopy(session) if session is not None else None

    def end_session(self, session_id, ended_at=None):
        with self._lock:
            session = self._get("sessions", session_id)
            if session is None:
                raise KeyError(session_id)
            session["ended_at"] = ended_at if ended_at is not None else _now()
            session["status"] = "ended"
            self._save("sessions", session)
            if self._meta_get("live_session_id") == session_id:
                self._meta_set("live_session_id", None)
            return copy.deepcopy(session)

    def current_session_id(self):
        """Live id, else today's seed session id, else None (empty store)."""
        with self._lock:
            live_id = self._meta_get("live_session_id")
            if live_id is not None:
                return live_id
            return self._meta_get("today_session_id")

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
            self._insert("chunks", chunk)
            return copy.deepcopy(chunk)

    def update_chunk_status(self, chunk_id, status):
        with self._lock:
            chunk = self._get("chunks", chunk_id)
            if chunk is None:
                raise KeyError(chunk_id)
            chunk["status"] = status
            self._save("chunks", chunk)
            return copy.deepcopy(chunk)

    # -- scenes -----------------------------------------------------------

    def add_scene(self, scene):
        """Store assigns the id; inserts newest-first. Returns the row."""
        with self._lock:
            scene = copy.deepcopy(scene) if scene else {}
            scene_id = _new_id()
            scene["id"] = scene_id
            today_id = self._meta_get("today_session_id")
            live_id = self._meta_get("live_session_id")
            scene.setdefault("session_id", today_id)
            if live_id is not None and not scene.get("session_id"):
                scene["session_id"] = live_id
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
            self._insert("scenes", scene)
            return copy.deepcopy(scene)

    def get_scene(self, scene_id):
        with self._lock:
            scene = self._get("scenes", scene_id)
            return copy.deepcopy(scene) if scene is not None else None

    def list_scenes_today(self, limit=50, before=None):
        """Newest-first page; ``next_before`` = last id iff more remain.

        Unknown ``before`` yields an empty page (old-mock semantics).
        Same code path as InMemoryStore, including its limit=0
        IndexError on a non-empty store (see module docstring).
        """
        with self._lock:
            scenes = self._all("scenes", newest_first=True)
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
            scenes = [s for s in self._all("scenes", newest_first=True)
                      if s.get("session_id") == session_id]
            return copy.deepcopy(list(reversed(scenes)))

    def list_scenes_by_person(self, name, limit=10):
        """Newest-first scenes featuring ``name`` (case-insensitive)."""
        with self._lock:
            wanted = (name or "").lower()
            out = []
            for scene in self._all("scenes", newest_first=True):
                if any((p.get("name") or "").lower() == wanted
                       for p in scene.get("people") or []):
                    out.append(scene)
                    if limit is not None and len(out) >= limit:
                        break
            return copy.deepcopy(out)

    def update_scene(self, scene_id, **fields):
        """Critique / confidence / pinned updates. Id is never changed."""
        with self._lock:
            scene = self._get("scenes", scene_id)
            if scene is None:
                raise KeyError(scene_id)
            fields.pop("id", None)
            scene.update(fields)
            self._save("scenes", scene)
            return copy.deepcopy(scene)

    def set_scene_pinned(self, scene_id, pinned=True):
        """Plan-03 alias for ``update_scene(scene_id, pinned=pinned)``."""
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
            self._insert("facts", fact)
            return copy.deepcopy(fact)

    def list_facts(self, actor=None, query=None, limit=20, session_id=None):
        with self._lock:
            out = self._all("facts")
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
            self._insert("people", person)
            return copy.deepcopy(person)

    def list_people(self):
        with self._lock:
            return copy.deepcopy(self._all("people"))

    def get_person_by_name(self, name):
        with self._lock:
            for person in self._all("people"):
                if person.get("name") == name:
                    return copy.deepcopy(person)
            return None

    def record_appearance(self, name, last_seen, quote=False):
        """Bump counters; creates an unverified row if the name is unseen."""
        with self._lock:
            person = next(
                (p for p in self._all("people") if p.get("name") == name), None)
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
                self._insert("people", person)
            person["last_seen"] = last_seen
            person["scene_count"] += 1
            if quote:
                person["quote_count"] += 1
            self._save("people", person)
            return None

    # -- pins -------------------------------------------------------------

    def create_pin(self, scene_id, note=None):
        with self._lock:
            scene = self._get("scenes", scene_id)
            if scene is None:
                raise KeyError(scene_id)
            scene["pinned"] = True
            self._save("scenes", scene)
            pin = {"pin_id": _new_id(), "scene_id": scene_id, "note": note}
            self._insert("pins", pin)
            return copy.deepcopy(pin)

    def list_pins(self):
        with self._lock:
            return copy.deepcopy(self._all("pins"))

    # -- followups --------------------------------------------------------

    def create_followup_run(self, session_id=None):
        with self._lock:
            if session_id is None:
                session_id = (self._meta_get("live_session_id")
                              or self._meta_get("today_session_id"))
            run = {
                "run_id": _new_id(),
                "status": "running",
                "steps": list(FOLLOWUP_STEPS),
                "session_id": session_id,
            }
            self._insert("followup_runs", run)
            return copy.deepcopy(run)

    def get_followup_run(self, run_id):
        with self._lock:
            run = self._get("followup_runs", run_id)
            return copy.deepcopy(run) if run is not None else None

    def update_followup_run_status(self, run_id, status):
        with self._lock:
            run = self._get("followup_runs", run_id)
            if run is None:
                raise KeyError(run_id)
            run["status"] = status
            self._save("followup_runs", run)
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
            self._insert("followups", followup)
            return copy.deepcopy(followup)

    def get_followup(self, followup_id):
        with self._lock:
            followup = self._get("followups", followup_id)
            return copy.deepcopy(followup) if followup is not None else None

    def list_followups(self, run_id=None, status=None):
        with self._lock:
            out = self._all("followups")
            if run_id is not None:
                out = [f for f in out if f.get("run_id") == run_id]
            if status is not None:
                out = [f for f in out if f.get("status") == status]
            return copy.deepcopy(out)

    def approve_followup(self, followup_id):
        with self._lock:
            followup = self._get("followups", followup_id)
            if followup is None:
                raise KeyError(followup_id)
            if followup.get("status") == "needs_review":
                raise ValueError(followup_id)
            followup["status"] = "approved"
            self._save("followups", followup)
            return copy.deepcopy(followup)

    def dismiss_followup(self, followup_id):
        """Any status -> dismissed (mock parity)."""
        with self._lock:
            followup = self._get("followups", followup_id)
            if followup is None:
                raise KeyError(followup_id)
            followup["status"] = "dismissed"
            self._save("followups", followup)
            return copy.deepcopy(followup)

    # -- spend + status ---------------------------------------------------

    def add_spend(self, amount_usd):
        with self._lock:
            # Money: keep the counter at 2dp so 1.84 + 0.07 == 1.91 exactly.
            current = self._meta_get("spend_usd")
            total = round((float(current) if current is not None else 0.0)
                          + amount_usd, 2)
            self._meta_set("spend_usd", repr(total))
            return total

    def get_spend(self):
        with self._lock:
            current = self._meta_get("spend_usd")
            return round(float(current) if current is not None else 0.0, 2)

    def status_snapshot(self):
        with self._lock:
            session_id = (self._meta_get("live_session_id")
                          or self._meta_get("today_session_id"))
            scenes = self._all("scenes", newest_first=True)
            return {
                "recording": self._meta_get("live_session_id") is not None,
                "session_id": session_id,
                "scene_count": len(scenes),
                "last_scene_ts": scenes[0]["start_ts"] if scenes else None,
                "spend_usd": self.get_spend(),
            }
