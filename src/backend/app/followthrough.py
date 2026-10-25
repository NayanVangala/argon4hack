"""Follow-Through approval gate (module 5).

Built to ~/workspace/scene-backend/INTERFACES.md (locked). Where plan 05
disagreed with INTERFACES.md, INTERFACES.md wins:
- approve from any status other than needs_review sets approved (mock
  parity); the plan's tightening (400 for non-pending) is rejected.
- dismiss from any status sets dismissed (mock parity); the plan's
  tightening (pending/needs_review only) is rejected.
- Constructor injection: FollowThroughService(store); the plan's
  module-level functions taking store are superseded.
- Store method names are the INTERFACES.md ones (create_followup_run,
  add_followup, ...), not the plan's save_*/update_* names.

Stdlib only. No I/O, no LLM calls. Nothing sends: approve only flips
status; Resend delivery is a stretch goal owned elsewhere. No auto-run
at session end in this phase (on-demand only).
"""

import difflib
import re
from datetime import datetime

from app import actions

STEPS = ["find_promises", "verify_quotes", "draft_followups"]

# Exact canned drafts from the old mock (server.py), field-for-field.
# Verification flags are NOT canned: they are computed live by
# verify_quote() against the resolved scene transcript, and reproduce
# the mock's flags on seeded data (True, True, False).
CANNED_DRAFTS = [
    {
        "promise": "Maya promised Q3 numbers by Friday",
        "person": "Maya",
        "quote": "I'll send the Q3 numbers by Friday",
        "draft": "Hi Maya, following up on the Q3 numbers you mentioned today. "
                 "Could you send them over when you get a chance?",
        "fact_key": "Q3",
    },
    {
        "promise": "Maya decided the demo leads with glasses, not the dashboard",
        "person": "Maya",
        "quote": "The whole day goes into one context, no retrieval step",
        "draft": "Hi Maya, confirming we agreed the demo leads with the glasses "
                 "and the dashboard stays backup only.",
        "fact_key": "demo leads with glasses",
    },
    {
        "promise": "Unknown speaker promised to share the demo link",
        "person": "Unknown",
        "quote": "I'll drop the link somewhere",
        "draft": "",
        "fact_key": None,
    },
]

_PROMISE_RE = re.compile(r"\b(promis|commit|decid)", re.IGNORECASE)
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def _now_iso():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _normalize(text):
    """Lowercase, strip punctuation/whitespace (verification rule)."""
    return _NON_ALNUM.sub(" ", (text or "").lower()).strip()


def _parse_ts(value):
    """Parse an ISO 8601 timestamp; None when missing/unparsable."""
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def transcript_lines(scene):
    """Transcript lines as [{text, start_ts, end_ts}] (tolerates strings)."""
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


def _windows_overlap(line, scene):
    """Best-matching line must overlap the scene window.

    Lines/scenes without parseable timestamps cannot disprove overlap,
    so they pass this check (the fuzzy check still has to pass).
    """
    line_start = _parse_ts(line.get("start_ts"))
    line_end = _parse_ts(line.get("end_ts"))
    scene_start = _parse_ts((scene or {}).get("start_ts"))
    scene_end = _parse_ts((scene or {}).get("end_ts"))
    if None in (line_start, line_end, scene_start, scene_end):
        return True
    return line_start <= scene_end and scene_start <= line_end


def verify_quote(quote, scene):
    """Deterministic quote verification (code disposes, LLM proposes).

    Fuzzy-matches the quote (normalized, difflib >= 0.80) against each
    transcript line and the joined segment; the best-matching line must
    overlap the scene window. Returns (verified, best_ratio).
    """
    lines = transcript_lines(scene)
    norm_quote = _normalize(quote)
    if not norm_quote or not lines:
        return False, 0.0
    best_ratio, best_line = 0.0, None
    for line in lines:
        ratio = difflib.SequenceMatcher(
            None, norm_quote, _normalize(line.get("text"))).ratio()
        if ratio > best_ratio:
            best_ratio, best_line = ratio, line
    joined = " ".join(line.get("text") or "" for line in lines)
    joined_ratio = difflib.SequenceMatcher(
        None, norm_quote, _normalize(joined)).ratio()
    if joined_ratio > best_ratio:
        # The joined segment spans the whole scene window by definition.
        return joined_ratio >= 0.80, joined_ratio
    if best_line is None:
        return False, best_ratio
    return best_ratio >= 0.80 and _windows_overlap(best_line, scene), best_ratio


class FollowThroughService:
    """On-demand Follow-Through runs over a Store (INTERFACES.md)."""

    def __init__(self, store):
        self.store = store

    # -- discovery -----------------------------------------------------

    def _find_promise_facts(self, session_id):
        """Facts for promises/commitments/decisions, deduped by id.

        Queries the store per keyword and also pulls the session's facts
        unfiltered, filtering the broad pull locally, so the result does
        not depend on the store's exact query semantics.
        """
        found, seen = [], set()

        def _take(facts):
            for fact in facts or []:
                key = fact.get("id") or (fact.get("text"), fact.get("scene_id"))
                if key not in seen:
                    seen.add(key)
                    found.append(fact)

        for query in ("promise", "commitment", "decision"):
            try:
                _take(self.store.list_facts(query=query, session_id=session_id))
            except TypeError:
                _take(self.store.list_facts(query=query))
            except Exception:
                pass
        try:
            broad = self.store.list_facts(session_id=session_id)
        except TypeError:
            broad = self.store.list_facts()
        except Exception:
            broad = []
        _take([f for f in (broad or [])
               if _PROMISE_RE.search(f.get("text") or "")])
        return found

    def _session_scenes_oldest_first(self, session_id):
        """Session scenes oldest-first, via either store listing."""
        if session_id:
            try:
                scenes = self.store.list_scenes_for_session(session_id)
                if scenes:
                    return list(scenes)
            except Exception:
                pass
        try:
            result = self.store.list_scenes_today()
            scenes = result[0] if isinstance(result, tuple) else result
            return list(reversed(scenes or []))  # today listing is newest-first
        except Exception:
            return []

    def _resolve_scene_id(self, canned, facts, scenes):
        """Scene id for a canned draft: fact link, transcript match, or
        (Unknown draft only) the earliest Unknown-speaker scene."""
        if canned["fact_key"]:
            for fact in facts:
                if canned["fact_key"].lower() in (fact.get("text") or "").lower():
                    if fact.get("scene_id"):
                        return fact["scene_id"]
        for scene in scenes:
            verified, _ = verify_quote(canned["quote"], scene)
            if verified:
                return scene.get("id")
        if canned["person"] == "Unknown":
            for scene in scenes:
                speakers = {p.get("name") for p in scene.get("people") or []
                            if isinstance(p, dict)}
                speakers |= {line.get("speaker") for line in
                             transcript_lines(scene) if line.get("speaker")}
                if "Unknown" in speakers:
                    return scene.get("id")
        return None

    # -- runs ----------------------------------------------------------

    def generate_run(self, session_id=None):
        """Run the three steps synchronously; return 202 semantics.

        Returns {run_id, status: "running", steps} while the stored run
        is set to "done" after synchronous completion.
        """
        if session_id is None:
            try:
                session_id = self.store.current_session_id()
            except Exception:
                session_id = None
        run = self.store.create_followup_run(session_id)
        run_id = run.get("run_id") or run.get("id")
        # Real path (Oct 25): Argon reads the session's transcripts and
        # proposes emails / replies / calendar events / to-dos. Falls back
        # to the canned drafts below only when no key is configured or
        # the call fails, so the demo never hard-fails.
        if actions.api_key():
            try:
                self._generate_real(run_id, session_id)
                if hasattr(self.store, "update_followup_run_status"):
                    self.store.update_followup_run_status(run_id, "done")
                return {"run_id": run_id, "status": "running", "steps": list(STEPS)}
            except actions.ActionError as exc:
                print("FollowThrough: real extraction failed (%s); using canned drafts" % exc,
                      flush=True)
        facts = self._find_promise_facts(session_id)
        scenes = self._session_scenes_oldest_first(session_id)
        by_id = {s.get("id"): s for s in scenes if s.get("id")}

        for canned in CANNED_DRAFTS:
            scene_id = self._resolve_scene_id(canned, facts, scenes)
            scene = by_id.get(scene_id)
            if scene is None and scene_id:
                try:
                    scene = self.store.get_scene(scene_id)
                except Exception:
                    scene = None
            verified, _ = verify_quote(canned["quote"], scene) if scene else (False, 0.0)
            self.store.add_followup({
                "run_id": run_id,
                "promise": canned["promise"],
                "person": canned["person"],
                "quote": canned["quote"],
                "quote_verified": verified,
                "verified_at": _now_iso() if verified else None,
                "draft": canned["draft"] if verified else "",
                "status": "pending" if verified else "needs_review",
                "scene_id": scene_id,
            })
        if hasattr(self.store, "update_followup_run_status"):
            self.store.update_followup_run_status(run_id, "done")
        return {"run_id": run_id, "status": "running", "steps": list(STEPS)}

    def _generate_real(self, run_id, session_id):
        scenes = self._session_scenes_oldest_first(session_id)
        tasks = actions.extract_actions(scenes)
        by_id = {sc.get("id"): sc for sc in scenes if sc.get("id")}
        for task in tasks:
            scene = by_id.get(task.get("scene_id"))
            verified, _ = verify_quote(task["quote"], scene) if scene else (False, 0.0)
            if not verified:
                # The model may cite the wrong line: accept any scene in
                # this session whose transcript really contains the quote.
                for candidate in scenes:
                    ok, _ = verify_quote(task["quote"], candidate)
                    if ok:
                        verified, scene = True, candidate
                        break
            followup = dict(task)
            followup.update({
                "run_id": run_id,
                "promise": task["title"],
                "quote_verified": verified,
                "verified_at": _now_iso() if verified else None,
                "status": "pending" if verified else "needs_review",
                "scene_id": scene.get("id") if scene else task.get("scene_id"),
                "action_url": None,
                "execution_status": "waiting_for_approval",
            })
            self.store.add_followup(followup)

    def list_followups(self, run_id=None, status=None):
        return {"followups": self.store.list_followups(run_id=run_id, status=status)}

    # -- approval gate ---------------------------------------------------

    def _get_or_raise(self, followup_id):
        followup = None
        if hasattr(self.store, "get_followup"):
            followup = self.store.get_followup(followup_id)
        if followup is None:
            for item in self.store.list_followups() or []:
                if item.get("id") == followup_id:
                    followup = item
                    break
        if followup is None:
            raise KeyError(followup_id)
        return followup

    def approve_followup(self, followup_id, edits=None):
        """Approve only from pending with quote_verified True.

        needs_review raises ValueError (routes -> 400 not_approvable),
        as does pending with an unverified quote. Approve from any other
        status sets approved (mock parity, idempotent). Unknown id
        raises KeyError (routes -> 404 followup_not_found).
        """
        followup = self._get_or_raise(followup_id)
        status = followup.get("status")
        if status == "needs_review":
            raise ValueError("not_approvable: unverified drafts stay under needs_review")
        if status == "pending" and not followup.get("quote_verified"):
            raise ValueError("not_approvable: pending draft has an unverified quote")
        if status == "approved":
            return followup  # idempotent: second tap returns the same action
        # The user's edits from the approval screen win over the model's.
        changes = {}
        for key in ("draft", "recipient", "due_at"):
            value = (edits or {}).get(key)
            if isinstance(value, str) and value.strip():
                changes[key] = value.strip()[:4000]
        if changes.get("due_at") and actions._parse_ts(changes["due_at"]) is None:
            raise ValueError("not_approvable: due_at must be ISO 8601 with a time zone")
        merged = dict(followup, **changes)
        if merged.get("action_type"):
            changes.update(actions.build_action(merged))
        if hasattr(self.store, "approve_followup"):
            result = self.store.approve_followup(followup_id)
        else:
            followup["status"] = "approved"
            result = followup
        if changes and hasattr(self.store, "update_followup"):
            result = self.store.update_followup(followup_id, changes) or result
        result = dict(result, **changes)
        result["status"] = "approved"
        result.setdefault("id", followup_id)
        return result

    def list_todos(self):
        """Approved to-dos (and other approved actions) for the to-do list."""
        return [f for f in (self.store.list_followups() or [])
                if f.get("status") == "approved" and f.get("action_type") == "todo"]

    def dismiss_followup(self, followup_id):
        """Dismiss from any status (mock parity). Unknown id: KeyError."""
        self._get_or_raise(followup_id)
        if hasattr(self.store, "dismiss_followup"):
            result = self.store.dismiss_followup(followup_id)
        else:
            result = {"id": followup_id, "status": "dismissed"}
        return {"id": result.get("id", followup_id), "status": "dismissed"}
