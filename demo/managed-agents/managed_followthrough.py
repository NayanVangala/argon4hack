#!/usr/bin/env python3
"""Managed Agents Follow-Through prototype (standalone, read-only client).

Implements the agent loop from DESIGN.md against the Scene contract API:

    find_promises -> verify_quotes -> draft_followups -> wait for human tap

    GET  /api/v1/facts?limit=...            find today's promise facts
    GET  /api/v1/scenes/{id}                transcript for verification
    POST /api/v1/followups/generate         trigger the server run (202)
    GET  /api/v1/followups?run_id=...       poll stored drafts + needs_review

Stdlib only. No live Argon calls. No server is started by this file.
No send, email, or Resend code exists here, on purpose: approve only
flips status server-side, and this prototype does not even call
approve or dismiss. Those are human taps in the phone app.

Verification rule (ported verbatim from scene-backend/app/followthrough.py
`verify_quote`, minus the store dependency):

    normalize: lowercase, replace runs of non-[a-z0-9] with one space
    score:     difflib.SequenceMatcher.ratio, per line and joined segment
    pass:      best ratio >= 0.80 AND best line overlaps the scene window
               (missing/unparseable timestamps cannot disprove overlap;
               the joined-segment match spans the scene window by definition)

NOTE ON THE TASK BRIEF: the brief said "exact string match". The verified
server rule is the fuzzy rule above, not exact match. An exact match is
a special case (normalized equality -> ratio 1.0 -> passes), but an
exact-only checker would be stricter than the server and would disagree
with it on real data. This file ports the server rule so the two verdicts
agree. Do not "tighten" this to exact match without changing the server
too (and telling Isabella first).

Modes:
    --dry-run    (default) run the whole loop against a fake transport
                 seeded with the contract's example data. Sends nothing,
                 touches no network, needs no token.
    --live       hit SCENE_API_BASE with SCENE_API_TOKEN. Still sends
                 nothing: it only triggers generate and polls. Requires
                 SCENE_API_TOKEN unless --allow-no-token is passed.
    --self-test  run assertions (verifier + gate + fake-transport loop)
                 and exit. No network, no token.

Auth: token comes ONLY from the SCENE_API_TOKEN environment variable.
It is never logged, never printed, never put in the agent prompt, and
never sent anywhere except as an Authorization header to SCENE_API_BASE.
Error messages redact it (only its presence is ever reported).

MANAGED AGENTS SEAM (unverified, see DESIGN.md section 2):
`launch_managed_agent()` contains the Interactions call shape reported
by secondary write-ups (client.interactions.create with
agent="antigravity-preview-09-2026", input=..., environment="remote").
That shape was NOT verified against official Google documentation in
this task, so the function refuses to run until the caller passes
confirm_sdk_shape=True AND the google-genai package is importable, and
even then it is the caller's responsibility to have confirmed the shape
against the official Antigravity agent guide. The dry-run and live
REST paths never call it. The prompt it would send, MANAGED_AGENT_PROMPT,
is final and does not depend on the SDK shape.
"""

import argparse
import difflib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

# ---------------------------------------------------------------------------
# Constants (verified against the contract doc / followthrough.py / routes.py)
# ---------------------------------------------------------------------------

STEPS = ["find_promises", "verify_quotes", "draft_followups"]
VERIFY_THRESHOLD = 0.80
DEFAULT_BASE_URL = "https://api.helloscene.xyz/api/v1"  # contract base URL
DEFAULT_LIMIT = 50
POLL_INTERVAL_SECONDS = 2.0
POLL_TIMEOUT_SECONDS = 30.0
WAIT_TIMEOUT_SECONDS = 300.0

_PROMISE_RE = re.compile(r"\b(promis|commit|decid)", re.IGNORECASE)
_NON_ALNUM = re.compile(r"[^a-z0-9]+")

MANAGED_AGENT_ID = "antigravity-preview-09-2026"  # [UNVERIFIED SDK SEAM]

MANAGED_AGENT_PROMPT = """\
You are Scene's Follow-Through Agent, running in a Managed Agents remote
sandbox. You close the loop from memory to action. You NEVER send anything.

TOOLS (read-only): get_facts, get_scene. There is no approve, dismiss,
edit, or send tool. Do not invent one. If a tool you want does not exist,
stop and say so in your run report.

LOOP, IN ORDER:
1. find_promises: call get_facts and keep facts whose text matches a
   promise, commitment, or decision (promise/commit/decid).
2. verify_quotes: for each promise, call get_scene for its scene_id and
   get the transcript. The LLM proposes the quote; CODE disposes. Run
   the verifier code in this sandbox: normalize (lowercase, strip every
   non-alphanumeric run to one space), score with difflib SequenceMatcher
   ratio against each transcript line and against the joined segment,
   and require best ratio >= 0.80 plus timestamp-window overlap of the
   best line with the scene window. Report (verified, best_ratio) per item.
3. draft_followups: for each VERIFIED promise, write one follow-up draft
   addressed to the person, referencing the promise and its verified quote.
   For each UNVERIFIED promise, write NO draft text and mark it
   needs_review. A verification failure NEVER becomes a draft.
4. STOP. Output a JSON list in the stored follow-up shape
   (promise, person, quote, quote_verified, verified_at, draft, status,
   scene_id) plus a run report with per-item verdicts and ratios.
   The human approves, edits, or dismisses each draft in the phone app.
   Nothing sends without a tap, and approve only flips status.
"""


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class ApiError(Exception):
    """An HTTP error from the Scene API, with code but never a token."""

    def __init__(self, status, code, message):
        super().__init__("%s %s: %s" % (status, code, message))
        self.status = status
        self.code = code
        self.message = message


class NotApprovable(Exception):
    """Local mirror of the server's 400 not_approvable gate."""


class UnverifiedSeamError(Exception):
    """The Managed Agents SDK seam has not been confirmed; refuse to run."""


# ---------------------------------------------------------------------------
# Verification: verbatim port of followthrough.verify_quote
# ---------------------------------------------------------------------------

def _normalize(text):
    """Lowercase, strip punctuation/whitespace (verification rule)."""
    return _NON_ALNUM.sub(" ", (text or "").lower()).strip()


def _parse_ts(value):
    """Parse an ISO 8601 timestamp; None when missing/unparsable."""
    if not value or not isinstance(value, str):
        return None
    try:
        from datetime import datetime
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
    from datetime import datetime  # noqa: F401  (kept local, mirrors source)
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
    An exact normalized match scores 1.0 and passes; exact-only matching
    would be stricter than this rule and is NOT what the server does.
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
        return joined_ratio >= VERIFY_THRESHOLD, joined_ratio
    if best_line is None:
        return False, best_ratio
    return (best_ratio >= VERIFY_THRESHOLD
            and _windows_overlap(best_line, scene)), best_ratio


def is_promise_fact(fact):
    """Server's promise filter: promis|commit|decid in the fact text."""
    return bool(_PROMISE_RE.search((fact or {}).get("text") or ""))


def build_draft(promise, person, quote, verified, ratio, scene_id):
    """One follow-up in the exact stored shape (see DESIGN.md section 6).

    Unverified items get an empty draft and status needs_review, never
    a pending draft. verified_at is set only when verified.
    """
    from datetime import datetime
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    if verified:
        draft = ("Hi %s, following up: %s. You mentioned: \"%s\". "
                 "Could you send it over when you get a chance?"
                 % (person, promise, quote))
        return {"promise": promise, "person": person, "quote": quote,
                "quote_verified": True, "verified_at": now, "draft": draft,
                "status": "pending", "scene_id": scene_id,
                "verify_ratio": round(ratio, 3)}
    return {"promise": promise, "person": person, "quote": quote,
            "quote_verified": False, "verified_at": None, "draft": "",
            "status": "needs_review", "scene_id": scene_id,
            "verify_ratio": round(ratio, 3)}


# ---------------------------------------------------------------------------
# HTTP client: only the four prototype endpoints. No approve/dismiss/send.
# ---------------------------------------------------------------------------

class SceneClient:
    """Minimal client for the prototype's four endpoints.

    Deliberately exposes no approve/dismiss/send method: this prototype
    cannot approve anything, even by accident.
    """

    def __init__(self, base_url, token=None, opener=None):
        self.base_url = base_url.rstrip("/")
        self._token = token  # never logged, never printed
        self._opener = opener or urllib.request.build_opener()

    def _request(self, method, path, body=None):
        url = self.base_url + path
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        if data is not None:
            req.add_header("Content-Type", "application/json")
        if self._token:
            req.add_header("Authorization", "Bearer " + self._token)
        try:
            with self._opener.open(req, timeout=30) as resp:
                return json.loads(resp.read().decode() or "{}")
        except urllib.error.HTTPError as exc:
            try:
                payload = json.loads(exc.read().decode() or "{}")
            except ValueError:
                payload = {}
            err = payload.get("error") or {}
            raise ApiError(exc.code, err.get("code", "http_error"),
                           err.get("message", "HTTP %s" % exc.code))

    def list_facts(self, actor=None, limit=DEFAULT_LIMIT):
        qs = {"limit": limit}
        if actor:
            qs["actor"] = actor
        return self._request("GET", "/facts?" + urllib.parse.urlencode(qs))

    def get_scene(self, scene_id):
        return self._request("GET", "/scenes/" + urllib.parse.quote(scene_id))

    def generate_followups(self, session_id=None):
        body = {"session_id": session_id} if session_id else {}
        return self._request("POST", "/followups/generate", body)

    def list_followups(self, run_id=None, status=None):
        qs = {}
        if run_id:
            qs["run_id"] = run_id
        if status:
            qs["status"] = status
        path = "/followups"
        if qs:
            path += "?" + urllib.parse.urlencode(qs)
        return self._request("GET", path)


# ---------------------------------------------------------------------------
# Fake transport for --dry-run and --self-test (no network, no token)
# ---------------------------------------------------------------------------

FAKE_SCENES = {
    "scene-q3": {
        "id": "scene-q3",
        "start_ts": "2026-10-25T10:00:00-07:00",
        "end_ts": "2026-10-25T10:00:30-07:00",
        "transcript": [
            {"speaker": "Maya", "text": "I'll send the Q3 numbers by Friday",
             "start_ts": "2026-10-25T10:00:05-07:00",
             "end_ts": "2026-10-25T10:00:10-07:00"},
        ],
    },
    "scene-demo": {
        "id": "scene-demo",
        "start_ts": "2026-10-25T11:00:00-07:00",
        "end_ts": "2026-10-25T11:00:30-07:00",
        "transcript": [
            {"speaker": "Maya",
             "text": "The whole day goes into one context, no retrieval step",
             "start_ts": "2026-10-25T11:00:05-07:00",
             "end_ts": "2026-10-25T11:00:10-07:00"},
        ],
    },
    "scene-link": {
        "id": "scene-link",
        "start_ts": "2026-10-25T12:00:00-07:00",
        "end_ts": "2026-10-25T12:00:30-07:00",
        "transcript": [
            {"speaker": "Unknown", "text": "Good luck with the demo today",
             "start_ts": "2026-10-25T12:00:05-07:00",
             "end_ts": "2026-10-25T12:00:10-07:00"},
        ],
    },
}

FAKE_FACTS = [
    {"id": "fact-1", "text": "Maya promised Q3 numbers by Friday",
     "scene_id": "scene-q3", "actors": ["Maya"]},
    {"id": "fact-2", "text": "Maya decided the demo leads with glasses",
     "scene_id": "scene-demo", "actors": ["Maya"]},
    {"id": "fact-3", "text": "Unknown speaker promised to share the demo link",
     "scene_id": "scene-link", "actors": ["Unknown"]},
]

# Quotes the agent proposes for each fact (mirrors the server's canned set).
FAKE_PROPOSED_QUOTES = {
    "fact-1": "I'll send the Q3 numbers by Friday",
    "fact-2": "The whole day goes into one context, no retrieval step",
    "fact-3": "I'll drop the link somewhere",
}


class FakeClient:
    """In-memory stand-in for SceneClient with the same method shapes.

    Its generate_followups() mirrors the server's stored outcomes:
    verified -> pending with draft, unverified -> needs_review, empty draft.
    It records every call so tests can assert nothing was ever sent.
    `sent` stays empty forever: there is no send operation to record.
    """

    def __init__(self):
        self.calls = []
        self.sent = []  # no code path ever appends to this, by design
        self._run_counter = 0

    def list_facts(self, actor=None, limit=DEFAULT_LIMIT):
        self.calls.append("list_facts")
        facts = FAKE_FACTS
        if actor:
            facts = [f for f in facts if actor in (f.get("actors") or [])]
        return {"facts": facts[:limit]}

    def get_scene(self, scene_id):
        self.calls.append("get_scene:" + scene_id)
        scene = FAKE_SCENES.get(scene_id)
        if scene is None:
            raise ApiError(404, "scene_not_found", "No scene with that id.")
        return scene

    def generate_followups(self, session_id=None):
        self.calls.append("generate_followups")
        self._run_counter += 1
        run_id = "run-fake-%d" % self._run_counter
        followups = []
        for fact in FAKE_FACTS:
            quote = FAKE_PROPOSED_QUOTES[fact["id"]]
            scene = FAKE_SCENES[fact["scene_id"]]
            verified, ratio = verify_quote(quote, scene)
            item = build_draft(fact["text"],
                               (fact.get("actors") or ["Unknown"])[0],
                               quote, verified, ratio, fact["scene_id"])
            item["id"] = "followup-" + fact["id"]
            item["run_id"] = run_id
            followups.append(item)
        self._last_followups = followups
        return {"run_id": run_id, "status": "running", "steps": list(STEPS)}

    def list_followups(self, run_id=None, status=None):
        self.calls.append("list_followups")
        items = getattr(self, "_last_followups", [])
        if run_id:
            items = [i for i in items if i.get("run_id") == run_id]
        if status:
            items = [i for i in items if i.get("status") == status]
        return {"followups": items}


# ---------------------------------------------------------------------------
# The loop
# ---------------------------------------------------------------------------

def find_promises(client, actor=None, limit=DEFAULT_LIMIT):
    """Step 1: facts filtered to promises/commitments/decisions, deduped."""
    payload = client.list_facts(actor=actor, limit=limit)
    facts = payload.get("facts", []) if isinstance(payload, dict) else payload
    seen, found = set(), []
    for fact in facts or []:
        key = fact.get("id") or (fact.get("text"), fact.get("scene_id"))
        if key in seen:
            continue
        seen.add(key)
        if is_promise_fact(fact):
            found.append(fact)
    return found


def verify_and_draft(client, facts, propose_quote):
    """Steps 2-3: verify each proposed quote with code, build drafts.

    `propose_quote` is the LLM-proposes seam: in the live Managed Agents
    run the agent supplies the quote; here the caller supplies it (fake
    transport: FAKE_PROPOSED_QUOTES; live REST path: the fact text's
    known quote is NOT assumed -- see run_loop note below).
    """
    results = []
    for fact in facts:
        scene_id = fact.get("scene_id")
        quote = propose_quote(fact)
        person = (fact.get("actors") or ["Unknown"])[0]
        if not scene_id:
            results.append(build_draft(fact.get("text", ""), person, quote,
                                       False, 0.0, None))
            continue
        try:
            scene = client.get_scene(scene_id)
        except ApiError:
            results.append(build_draft(fact.get("text", ""), person, quote,
                                       False, 0.0, scene_id))
            continue
        verified, ratio = verify_quote(quote, scene)
        results.append(build_draft(fact.get("text", ""), person, quote,
                                   verified, ratio, scene_id))
    return results


def run_loop(client, session_id=None, actor=None,
             propose_quote=None, poll_timeout=POLL_TIMEOUT_SECONDS,
             wait_timeout=WAIT_TIMEOUT_SECONDS, wait_for_human=False):
    """Run the full prototype loop and return a JSON-serializable report.

    NOTE on the live REST path: the REST API has no endpoint that accepts
    agent-produced drafts (see DESIGN.md section 6), so the live path's
    "drafts" are the prototype's own verification report, and the stored
    drafts come from POST /followups/generate + polling. The prototype
    does NOT claim its drafts are stored. `propose_quote` defaults to a
    conservative rule for the REST path: it proposes nothing verifiable
    on its own -- callers that want agent-proposed quotes must pass one
    in (the Managed Agents run does). With the default, live-path items
    are reported as needs_review unless the caller supplies quotes.
    """
    if propose_quote is None:
        # Conservative default: without an agent proposing quotes, the
        # prototype must not invent them. Report needs_review and let
        # the server's generate step produce the stored drafts.
        def propose_quote(fact):  # noqa: F811
            return ""
    facts = find_promises(client, actor=actor)
    local = verify_and_draft(client, facts, propose_quote)
    generated = client.generate_followups(session_id)
    run_id = generated.get("run_id")
    steps = generated.get("steps", STEPS)

    # Poll for stored drafts. The server runs synchronously, so this
    # normally returns on the first poll; the loop exists for safety.
    stored, deadline = [], time.time() + poll_timeout
    while time.time() < deadline:
        payload = client.list_followups(run_id=run_id)
        stored = payload.get("followups", []) if isinstance(payload, dict) else []
        if stored:
            break
        time.sleep(min(POLL_INTERVAL_SECONDS,
                       max(0.0, deadline - time.time())))
    if not stored and poll_timeout > 0:
        payload = client.list_followups(run_id=run_id)
        stored = payload.get("followups", []) if isinstance(payload, dict) else []

    # Compare local verdicts with stored verdicts (audit, never override).
    stored_by_scene = {i.get("scene_id"): i for i in stored}
    agreement = []
    for item in local:
        match = stored_by_scene.get(item.get("scene_id"))
        agreement.append({
            "scene_id": item.get("scene_id"),
            "local_status": item["status"],
            "stored_status": match.get("status") if match else None,
            "agree": bool(match)
            and match.get("status") == item["status"]
            and match.get("quote_verified") == item["quote_verified"],
        })

    report = {
        "run_id": run_id,
        "generate_status": generated.get("status"),
        "steps": steps,
        "promise_count": len(facts),
        "local_verdicts": local,
        "stored_followups": stored,
        "verdict_agreement": agreement,
        "pending": [i for i in stored if i.get("status") == "pending"],
        "needs_review": [i for i in stored
                         if i.get("status") == "needs_review"],
        "human_decision": None,
        "sent": [],  # always empty: nothing sends, ever, in this prototype
    }

    if wait_for_human:
        # Wait for the human's taps in the phone app. Never approve here.
        deadline = time.time() + wait_timeout
        while time.time() < deadline:
            payload = client.list_followups(run_id=run_id)
            current = payload.get("followups", [])
            undecided = [i for i in current
                         if i.get("status") in ("pending",)]
            if not undecided:
                report["human_decision"] = {
                    i.get("id"): i.get("status") for i in current}
                break
            time.sleep(min(POLL_INTERVAL_SECONDS,
                           max(0.0, deadline - time.time())))
        else:
            report["human_decision"] = "timeout: still awaiting human tap"
        report["stored_followups"] = client.list_followups(
            run_id=run_id).get("followups", [])
    return report


# ---------------------------------------------------------------------------
# Managed Agents SDK seam -- UNVERIFIED, guarded, never used by default
# ---------------------------------------------------------------------------

def launch_managed_agent(confirm_sdk_shape=False):
    """[UNVERIFIED SEAM] Launch the Managed Agents run.

    Reported shape (secondary write-ups only, NOT official docs):
        from google import genai
        client = genai.Client()
        interaction = client.interactions.create(
            agent="antigravity-preview-09-2026",
            input=MANAGED_AGENT_PROMPT,
            environment="remote",
        )

    This function REFUSES to run unless confirm_sdk_shape=True (meaning
    the caller has confirmed the shape against the official Antigravity
    agent guide) and the google-genai package imports. It is pseudocode
    with the exact behavior it must implement until that confirmation
    exists: send the prompt above, run it in the remote sandbox, return
    the agent's output text. It performs no Scene API call itself and
    receives no token: auth stays in SceneClient, outside the sandbox.
    """
    if not confirm_sdk_shape:
        raise UnverifiedSeamError(
            "Managed Agents SDK shape is UNVERIFIED: confirm "
            "client.interactions.create(agent=%r, input=..., "
            "environment='remote') against the official Antigravity agent "
            "guide, then call with confirm_sdk_shape=True."
            % MANAGED_AGENT_ID)
    try:
        from google import genai  # type: ignore
    except ImportError as exc:
        raise UnverifiedSeamError(
            "google-genai package not installed; cannot launch the "
            "Managed Agents run. Install it and confirm the SDK shape "
            "first.") from exc
    client = genai.Client()
    interaction = client.interactions.create(
        agent=MANAGED_AGENT_ID,
        input=MANAGED_AGENT_PROMPT,
        environment="remote",
    )
    return getattr(interaction, "output_text", interaction)


# ---------------------------------------------------------------------------
# Self-test (no network, no token)
# ---------------------------------------------------------------------------

def self_test():
    """Assertions over the verifier, the gate shape, and the fake loop."""
    # Exact match passes (ratio 1.0); near miss below threshold fails.
    scene = FAKE_SCENES["scene-q3"]
    ok, ratio = verify_quote("I'll send the Q3 numbers by Friday", scene)
    assert ok and ratio == 1.0, (ok, ratio)
    ok, ratio = verify_quote("completely unrelated sentence here", scene)
    assert not ok and ratio < VERIFY_THRESHOLD, (ok, ratio)
    # Empty transcript / missing scene cannot verify.
    ok, _ = verify_quote("anything", {"transcript": []})
    assert not ok
    # Normalization: case + punctuation must not matter.
    ok, _ = verify_quote("ill SEND the q3 numbers by friday!!!", scene)
    assert ok
    # Draft shape: verified -> pending with text; unverified -> needs_review.
    good = build_draft("p", "Maya", "q", True, 1.0, "scene-q3")
    assert good["status"] == "pending" and good["draft"] and good["verified_at"]
    bad = build_draft("p", "Unknown", "q", False, 0.1, "scene-link")
    assert bad["status"] == "needs_review" and bad["draft"] == ""
    assert bad["verified_at"] is None
    # Full fake loop: 2 pending, 1 needs_review, nothing sent, seam guarded.
    client = FakeClient()
    report = run_loop(client, propose_quote=lambda f: FAKE_PROPOSED_QUOTES[f["id"]],
                      poll_timeout=5)
    assert report["promise_count"] == 3, report["promise_count"]
    assert len(report["pending"]) == 2, report["pending"]
    assert len(report["needs_review"]) == 1, report["needs_review"]
    assert report["sent"] == [] and client.sent == []
    assert all(a["agree"] for a in report["verdict_agreement"]), report
    try:
        launch_managed_agent()
    except UnverifiedSeamError:
        pass
    else:
        raise AssertionError("unverified seam must refuse by default")
    print("self-test: all assertions passed "
          "(verifier, draft shape, fake loop 2 pending / 1 needs_review, "
          "nothing sent, SDK seam guarded)")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Scene Follow-Through Managed Agents prototype.")
    parser.add_argument("--base-url", default=os.environ.get(
        "SCENE_API_BASE", DEFAULT_BASE_URL),
        help="API base URL (default: SCENE_API_BASE or contract URL).")
    parser.add_argument("--session-id", default=None,
                        help="Session id for generate (omitted = today).")
    parser.add_argument("--actor", default=None,
                        help="Optional actor filter for GET /facts.")
    parser.add_argument("--dry-run", action="store_true", default=True,
                        help="Use the fake transport (default).")
    parser.add_argument("--live", action="store_true",
                        help="Hit the real API. Still sends nothing.")
    parser.add_argument("--allow-no-token", action="store_true",
                        help="Live mode without SCENE_API_TOKEN (only for "
                             "a server known to run with AUTH_ENABLED off).")
    parser.add_argument("--wait-for-human", action="store_true",
                        help="Poll until pending items are approved/ "
                             "dismissed in the phone app (or timeout).")
    parser.add_argument("--self-test", action="store_true",
                        help="Run assertions and exit.")
    args = parser.parse_args(argv)

    if args.self_test:
        return self_test()

    if args.live:
        token = os.environ.get("SCENE_API_TOKEN", "")
        if not token and not args.allow_no_token:
            print("Refusing live run: SCENE_API_TOKEN is not set. "
                  "Set it, or pass --allow-no-token only for a local "
                  "server known to run with AUTH_ENABLED off.",
                  file=sys.stderr)
            return 2
        # Token presence is logged; the value is never logged.
        print("live mode: base=%s token_present=%s"
              % (args.base_url, bool(token)))
        client = SceneClient(args.base_url, token or None)
        report = run_loop(client, session_id=args.session_id,
                          actor=args.actor,
                          wait_for_human=args.wait_for_human)
    else:
        client = FakeClient()
        report = run_loop(client, session_id=args.session_id,
                          actor=args.actor,
                          propose_quote=lambda f: FAKE_PROPOSED_QUOTES[f["id"]],
                          wait_for_human=False)
        report["mode"] = "dry-run (fake transport; no network, no token)"
    print(json.dumps(report, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
