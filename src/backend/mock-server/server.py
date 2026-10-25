#!/usr/bin/env python3
"""Scene mock API server — Python stdlib only, no dependencies.

Serves SCENE-API-CONTRACT.md field-for-field with canned data so the phone
app, dashboard, and lens teams can build before the real pipeline is live.

Run:  python3 server.py            (listens on :8000)
      PORT=9000 python3 server.py  (override port)

REST base: http://localhost:PORT/api/v1
WS live:   ws://localhost:PORT/api/v1/live

Notes (mock leniency, all documented in README.md):
- Auth is not enforced: any or no Bearer token is accepted.
- CORS is wide open (*) so browser clients on any origin can call it.
- POST /chunks indexes one mock scene and broadcasts it over WS, so the
  live timeline moves when the bridge uploads.
- A background thread pushes one synthetic scene + status event over WS
  every 30s, but only while at least one WS client is connected.
- spend_usd starts at 1.84 and grows 0.07 per chunk, 0.12 per ask.
"""

import base64
import hashlib
import json
import os
import re
import struct
import threading
import uuid
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

PORT = int(os.environ.get("PORT", "8000"))
PDT = timezone(timedelta(hours=-7))  # hackathon day offset, matches contract
WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


def new_id():
    return str(uuid.uuid4())


def ts(hour, minute):
    """ISO 8601 timestamp on hackathon day (2026-10-25) in PDT."""
    return datetime(2026, 10, 25, hour, minute, tzinfo=PDT).isoformat(timespec="seconds")


# --------------------------------------------------------------------------
# Canned data: 8 scenes, 2 people (Maya, Unknown), 3 facts, 1 pinned scene.
# Scenes are stored newest-first, matching GET /scenes/today ordering.
# --------------------------------------------------------------------------

TODAY_SESSION_ID = new_id()


def _critique(passes=("transcript_alignment", "visual_grounding",
                      "people_consistency", "temporal_sanity"),
              notes=None, fails=None):
    notes = notes or {}
    fails = fails or {}
    out = []
    for check in passes:
        if check in fails:
            out.append({"check": check, "result": "fail", "note": fails[check]})
        else:
            out.append({"check": check, "result": "pass",
                        "note": notes.get(check, "Check passed")})
    return out


def make_scene(start, end, summary, quote, stype, confidence, people,
               objects, actions, visible_text, transcript, pinned=False,
               critique=None):
    sid = new_id()
    return {
        "id": sid,
        "session_id": TODAY_SESSION_ID,
        "start_ts": start,
        "end_ts": end,
        "summary": summary,
        "quote": quote,
        "thumb_url": "https://cdn.helloscene.xyz/t/%s.jpg" % sid,
        "type": stype,
        "verified": confidence == "verified",
        "confidence": confidence,
        "objects": objects,
        "people": people,
        "actions": actions,
        "visible_text": visible_text,
        "critique": critique if critique is not None else _critique(notes={
            "transcript_alignment": "Key claims appear in transcript",
            "visual_grounding": "Keyframe matches scene description",
            "people_consistency": "Speaker matches enrolled print",
            "temporal_sanity": "Timestamps in order",
        }),
        "transcript": transcript,
        "keyframes": ["https://cdn.helloscene.xyz/k/%s/0.jpg" % sid],
        "pinned": pinned,
    }


def scene_summary(s):
    return {k: s[k] for k in
            ("id", "start_ts", "end_ts", "summary", "quote", "thumb_url",
             "type", "verified", "confidence")}


def scene_detail(s):
    return {k: s[k] for k in
            ("id", "session_id", "start_ts", "end_ts", "summary", "objects",
             "people", "actions", "visible_text", "type", "confidence",
             "critique", "transcript", "keyframes", "pinned")}


def _tline(speaker, text, start, end):
    return {"speaker": speaker, "text": text, "start_ts": start, "end_ts": end}


SCENES = []
# Chronological seed; reversed below so the list is newest-first.
_seed = [
    make_scene(ts(9, 15), ts(9, 15), "Maya explaining Q3 numbers at the whiteboard",
               "I'll send the Q3 numbers by Friday", "conversation", "verified",
               [{"name": "Maya", "confidence": "verified"}],
               ["whiteboard", "laptop", "coffee cup"], ["pointing", "talking"],
               ["Q3 revenue $4.2M"],
               [_tline("Maya", "I'll send the Q3 numbers by Friday", ts(9, 15), ts(9, 15))],
               pinned=True),
    make_scene(ts(9, 42), ts(9, 42), "Unknown speaker asks about the demo flow",
               "So the demo starts with the glasses, right?", "conversation", "review",
               [{"name": "Unknown", "confidence": "review"}],
               ["laptop"], ["talking"], [],
               [_tline("Unknown", "So the demo starts with the glasses, right?", ts(9, 42), ts(9, 42))],
               critique=_critique(fails={"visual_grounding": "Face partially occluded in keyframe"})),
    make_scene(ts(10, 5), ts(10, 5), "Maya sketches the Ask flow on a napkin",
               "Ask loads the whole day, no retrieval step", "action", "verified",
               [{"name": "Maya", "confidence": "verified"}],
               ["napkin", "pen"], ["sketching", "talking"], ["Ask -> whole day"],
               [_tline("Maya", "Ask loads the whole day, no retrieval step", ts(10, 5), ts(10, 5))]),
    make_scene(ts(10, 31), ts(10, 31), "Hallway, no conversation",
               "", "location", "silence", [], [], [], [], []),
    make_scene(ts(11, 2), ts(11, 2), "Maya reviews the pitch rubric",
               "Live demo is half the score", "conversation", "verified",
               [{"name": "Maya", "confidence": "verified"}],
               ["laptop"], ["talking"], ["Demo 50%"],
               [_tline("Maya", "Live demo is half the score", ts(11, 2), ts(11, 2))]),
    make_scene(ts(11, 20), ts(11, 20), "Maya whiteboards the Scene pipeline",
               "The whole day goes into one context, no retrieval step", "conversation",
               "verified",
               [{"name": "Maya", "confidence": "verified"}],
               ["whiteboard", "marker"], ["pointing", "talking"],
               ["chunk -> scene -> Ask"],
               [_tline("Maya", "The whole day goes into one context, no retrieval step",
                       ts(11, 20), ts(11, 20))]),
    make_scene(ts(11, 48), ts(11, 48), "Unknown speaker asks about the demo flow",
               "And the dashboard is just backup?", "conversation", "review",
               [{"name": "Unknown", "confidence": "review"}],
               ["laptop"], ["talking"], [],
               [_tline("Unknown", "And the dashboard is just backup?", ts(11, 48), ts(11, 48))]),
    make_scene(ts(12, 10), ts(12, 10), "Maya confirms the Friday deadline",
               "Yes, Friday, end of day, I promise", "quote", "verified",
               [{"name": "Maya", "confidence": "verified"}],
               ["phone"], ["talking"], [],
               [_tline("Maya", "Yes, Friday, end of day, I promise", ts(12, 10), ts(12, 10))]),
]
SCENES = list(reversed(_seed))

PROMISE_SCENE = _seed[0]  # the Q3 numbers promise scene

PEOPLE = [
    {"id": new_id(), "name": "Maya",
     "photo_thumb": "https://cdn.helloscene.xyz/p/maya.jpg",
     "last_seen": ts(12, 10), "scene_count": 5, "quote_count": 6, "verified": True},
    {"id": new_id(), "name": "Unknown",
     "photo_thumb": "https://cdn.helloscene.xyz/p/unknown.jpg",
     "last_seen": ts(11, 48), "scene_count": 2, "quote_count": 0, "verified": False},
]

FACTS = [
    {"id": new_id(), "text": "Maya promised Q3 numbers by Friday",
     "scene_id": PROMISE_SCENE["id"], "actors": ["Maya"], "extracted_at": ts(9, 15)},
    {"id": new_id(), "text": "Maya decided the demo leads with glasses, not the dashboard",
     "scene_id": _seed[5]["id"], "actors": ["Maya"], "extracted_at": ts(11, 20)},
    {"id": new_id(), "text": "Live demo is 50 percent of the judging score",
     "scene_id": _seed[4]["id"], "actors": ["Maya"], "extracted_at": ts(11, 2)},
]

# Mutable mock state.
STATE = {
    "live_session": None,   # {"id", "started_at"} while a session is live
    "spend_usd": 1.84,
    "pins": [],             # {"pin_id", "scene_id", "note"}
    "followup_runs": {},   # run_id -> run dict
    "followups": [],       # draft dicts
}
STATE_LOCK = threading.Lock()

WS_CLIENTS = set()
WS_LOCK = threading.Lock()

# Rotating summaries for the 30s live-push thread.
LIVE_ROTATION = [
    ("Hallway chat (mock live scene)", "conversation"),
    ("Whiteboard sketch (mock live scene)", "action"),
    ("Demo rehearsal (mock live scene)", "conversation"),
]


# --------------------------------------------------------------------------
# WebSocket helpers (minimal RFC 6455: handshake, text frames, ping/pong).
# --------------------------------------------------------------------------

def ws_frame(payload):
    """Build one unmasked server->client text frame."""
    data = payload.encode("utf-8")
    header = bytearray([0x81])
    n = len(data)
    if n < 126:
        header.append(n)
    elif n < 65536:
        header.append(126)
        header += struct.pack("!H", n)
    else:
        header.append(127)
        header += struct.pack("!Q", n)
    return bytes(header) + data


def ws_send(conn, obj):
    conn.sendall(ws_frame(json.dumps(obj)))


def ws_broadcast(obj):
    dead = []
    with WS_LOCK:
        clients = list(WS_CLIENTS)
    for conn in clients:
        try:
            ws_send(conn, obj)
        except Exception:
            dead.append(conn)
    if dead:
        with WS_LOCK:
            WS_CLIENTS.difference_update(dead)


def ws_read_frame(rfile):
    """Read one client->client frame. Returns (opcode, payload bytes) or None."""
    head = rfile.read(2)
    if len(head) < 2:
        return None
    b1, b2 = head[0], head[1]
    opcode = b1 & 0x0F
    masked = bool(b2 & 0x80)
    length = b2 & 0x7F
    if length == 126:
        ext = rfile.read(2)
        if len(ext) < 2:
            return None
        length = struct.unpack("!H", ext)[0]
    elif length == 127:
        ext = rfile.read(8)
        if len(ext) < 8:
            return None
        length = struct.unpack("!Q", ext)[0]
    mask = rfile.read(4) if masked else b""
    payload = rfile.read(length) if length else b""
    if len(payload) < length:
        return None
    if masked:
        payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
    return opcode, payload


def status_event():
    return {"event": "status", "recording": STATE["live_session"] is not None,
            "scene_count": len(SCENES)}


def add_mock_scene(summary, stype, quote=""):
    """Prepend a review-confidence mock scene (chunk uploads, live pushes)."""
    now = datetime.now(PDT).isoformat(timespec="seconds")
    s = make_scene(now, now, summary, quote, stype, "review",
                   [{"name": "Unknown", "confidence": "review"}],
                   [], ["talking"], [],
                   [_tline("Unknown", quote or "Live segment (mock transcript).", now, now)])
    with STATE_LOCK:
        SCENES.insert(0, s)
    return s


# --------------------------------------------------------------------------
# HTTP handler: all REST routes + WS upgrade on /api/v1/live.
# --------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        print("%s %s" % (self.command, self.path))

    # -- response plumbing -------------------------------------------------

    def _json(self, code, obj):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()
        self.wfile.write(body)

    def _error(self, code, err_code, message):
        self._json(code, {"error": {"code": err_code, "message": message}})

    def _read_body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""

    def _read_json(self):
        raw = self._read_body()
        if not raw:
            return {}
        try:
            obj = json.loads(raw.decode("utf-8"))
            return obj if isinstance(obj, dict) else {}
        except Exception:
            return None

    def do_OPTIONS(self):
        self._json(204, {})

    # -- routing -----------------------------------------------------------

    def do_GET(self):
        parsed = urlparse(self.path)
        path, query = parsed.path, parse_qs(parsed.query)
        if path == "/api/v1/live":
            return self._handle_ws()
        if path in ("/", "/api/v1", "/api/v1/"):
            return self._json(200, {"service": "scene-mock-server",
                                    "rest": "/api/v1", "ws": "/api/v1/live"})
        if path == "/api/v1/status":
            return self._json(200, {
                "recording": STATE["live_session"] is not None,
                "session_id": (STATE["live_session"] or {}).get("id") or TODAY_SESSION_ID,
                "scene_count": len(SCENES),
                "last_scene_ts": SCENES[0]["start_ts"] if SCENES else None,
                "spend_usd": round(STATE["spend_usd"], 2),
            })
        if path == "/api/v1/scenes/today":
            limit = int(query.get("limit", ["50"])[0])
            before = query.get("before", [None])[0]
            scenes = SCENES
            if before:
                idx = next((i for i, s in enumerate(scenes) if s["id"] == before), None)
                scenes = scenes[idx + 1:] if idx is not None else []
            page = scenes[:limit]
            nxt = page[-1]["id"] if len(scenes) > limit else None
            return self._json(200, {"scenes": [scene_summary(s) for s in page],
                                    "next_before": nxt})
        m = re.fullmatch(r"/api/v1/scenes/([^/]+)", path)
        if m:
            s = next((x for x in SCENES if x["id"] == m.group(1)), None)
            if not s:
                return self._error(404, "scene_not_found", "No scene with that id.")
            return self._json(200, scene_detail(s))
        if path == "/api/v1/people":
            return self._json(200, {"people": PEOPLE})
        if path == "/api/v1/facts":
            actor = (query.get("actor", [None])[0] or "").lower()
            limit = int(query.get("limit", ["20"])[0])
            facts = FACTS
            if actor:
                facts = [f for f in facts
                         if any(actor in a.lower() for a in f["actors"])]
            return self._json(200, {"facts": facts[:limit]})
        if path == "/api/v1/followups":
            run_id = query.get("run_id", [None])[0]
            status = query.get("status", [None])[0]
            items = STATE["followups"]
            if run_id:
                items = [f for f in items if f["run_id"] == run_id]
            if status:
                items = [f for f in items if f["status"] == status]
            return self._json(200, {"followups": items})
        return self._error(404, "not_found", "Unknown route: %s" % path)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/api/v1/sessions":
            self._read_body()
            sid = new_id()
            STATE["live_session"] = {"id": sid,
                                     "started_at": datetime.now(PDT).isoformat(timespec="seconds")}
            host = self.headers.get("Host", "localhost:%d" % PORT)
            return self._json(201, {
                "id": sid, "started_at": STATE["live_session"]["started_at"],
                "status": "live",
                "ws_url": "ws://%s/api/v1/live" % host,
            })
        m = re.fullmatch(r"/api/v1/sessions/([^/]+)/end", path)
        if m:
            self._read_body()
            sid = m.group(1)
            STATE["live_session"] = None
            return self._json(200, {
                "id": sid,
                "ended_at": datetime.now(PDT).isoformat(timespec="seconds"),
                "status": "ended", "scene_count": len(SCENES),
            })
        if path == "/api/v1/chunks":
            self._read_body()  # multipart video+audio accepted, contents ignored
            chunk_id = new_id()
            live = STATE["live_session"]
            session_id = live["id"] if live else TODAY_SESSION_ID
            now = datetime.now(PDT).isoformat(timespec="seconds")
            STATE["spend_usd"] += 0.07
            scene = add_mock_scene("Live chunk indexed (mock scene)", "conversation")
            ws_broadcast({"event": "scene", "scene": scene_summary(scene)})
            ws_broadcast(status_event())
            return self._json(202, {
                "chunk_id": chunk_id, "session_id": session_id,
                "start_ts": now, "end_ts": now, "status": "received",
            })
        if path == "/api/v1/ask":
            body = self._read_json()
            if body is None:
                return self._error(400, "bad_request", "Request body must be JSON.")
            q = (body.get("query") or "").lower()
            STATE["spend_usd"] += 0.12
            if "promise" in q:
                return self._json(200, {
                    "answer": "Maya promised to send the Q3 numbers by Friday.",
                    "receipts": [{
                        "scene_id": PROMISE_SCENE["id"],
                        "timestamp": PROMISE_SCENE["start_ts"],
                        "quote": "I'll send the Q3 numbers by Friday",
                        "thumb_url": PROMISE_SCENE["thumb_url"],
                    }],
                    "sources": ["fact:%s" % FACTS[0]["id"],
                                "scene:%s" % PROMISE_SCENE["id"]],
                })
            return self._json(200, {
                "answer": "I don't have a record of that.",
                "receipts": [], "sources": [],
            })
        if path == "/api/v1/pin":
            body = self._read_json()
            if body is None:
                return self._error(400, "bad_request", "Request body must be JSON.")
            scene_id = body.get("scene_id") or (SCENES[0]["id"] if SCENES else None)
            s = next((x for x in SCENES if x["id"] == scene_id), None)
            if not s:
                return self._error(404, "scene_not_found", "No scene with that id.")
            s["pinned"] = True
            pin_id = new_id()
            STATE["pins"].append({"pin_id": pin_id, "scene_id": scene_id,
                                  "note": body.get("note")})
            return self._json(201, {"pinned": True, "pin_id": pin_id,
                                    "scene_id": scene_id})
        if path == "/api/v1/people":
            self._read_body()  # multipart photo+voice_sample accepted, ignored
            name = "Enrolled Speaker"
            person = {"id": new_id(), "name": name,
                      "photo_thumb": "https://cdn.helloscene.xyz/p/enrolled.jpg",
                      "last_seen": datetime.now(PDT).isoformat(timespec="seconds"),
                      "scene_count": 0, "quote_count": 0, "verified": True}
            PEOPLE.append(person)
            return self._json(201, {"id": person["id"], "name": name, "verified": True})
        if path == "/api/v1/followups/generate":
            body = self._read_json()
            if body is None:
                return self._error(400, "bad_request", "Request body must be JSON.")
            run_id = new_id()
            STATE["followup_runs"][run_id] = {
                "run_id": run_id, "status": "running",
                "steps": ["find_promises", "verify_quotes", "draft_followups"],
                "session_id": body.get("session_id") or TODAY_SESSION_ID,
            }
            now = datetime.now(PDT).isoformat(timespec="seconds")
            STATE["followups"].extend([
                {"id": new_id(), "run_id": run_id,
                 "promise": "Maya promised Q3 numbers by Friday", "person": "Maya",
                 "quote": "I'll send the Q3 numbers by Friday", "quote_verified": True,
                 "verified_at": now,
                 "draft": "Hi Maya, following up on the Q3 numbers you mentioned today. "
                          "Could you send them over when you get a chance?",
                 "status": "pending", "scene_id": PROMISE_SCENE["id"]},
                {"id": new_id(), "run_id": run_id,
                 "promise": "Maya decided the demo leads with glasses, not the dashboard",
                 "person": "Maya",
                 "quote": "The whole day goes into one context, no retrieval step",
                 "quote_verified": True, "verified_at": now,
                 "draft": "Hi Maya, confirming we agreed the demo leads with the glasses "
                          "and the dashboard stays backup only.",
                 "status": "pending", "scene_id": _seed[5]["id"]},
                {"id": new_id(), "run_id": run_id,
                 "promise": "Unknown speaker promised to share the demo link",
                 "person": "Unknown",
                 "quote": "I'll drop the link somewhere", "quote_verified": False,
                 "verified_at": None, "draft": "",
                 "status": "needs_review", "scene_id": _seed[1]["id"]},
            ])
            return self._json(202, {
                "run_id": run_id, "status": "running",
                "steps": ["find_promises", "verify_quotes", "draft_followups"],
            })
        m = re.fullmatch(r"/api/v1/followups/([^/]+)/(approve|dismiss)", path)
        if m:
            self._read_body()
            fid, action = m.group(1), m.group(2)
            f = next((x for x in STATE["followups"] if x["id"] == fid), None)
            if not f:
                return self._error(404, "followup_not_found", "No follow-up with that id.")
            if action == "approve":
                if f["status"] == "needs_review":
                    return self._error(400, "not_approvable",
                                       "Unverified drafts are never approved; "
                                       "they stay under needs_review.")
                f["status"] = "approved"
                return self._json(200, {"id": fid, "status": "approved"})
            f["status"] = "dismissed"
            return self._json(200, {"id": fid, "status": "dismissed"})
        return self._error(404, "not_found", "Unknown route: %s" % path)


    # -- WebSocket ----------------------------------------------------------

    def _handle_ws(self):
        key = self.headers.get("Sec-WebSocket-Key")
        upgrade = (self.headers.get("Upgrade") or "").lower()
        if not key or "websocket" not in upgrade:
            return self._error(400, "websocket_upgrade_required",
                               "Connect with a WebSocket client.")
        accept = base64.b64encode(
            hashlib.sha1((key + WS_GUID).encode()).digest()).decode()
        self.send_response(101)
        self.send_header("Upgrade", "websocket")
        self.send_header("Connection", "Upgrade")
        self.send_header("Sec-WebSocket-Accept", accept)
        self.end_headers()
        conn = self.connection
        self.close_connection = True  # hijacked: no further HTTP on this socket
        with WS_LOCK:
            WS_CLIENTS.add(conn)
        try:
            ws_send(conn, status_event())
            if SCENES:
                ws_send(conn, {"event": "scene", "scene": scene_summary(SCENES[0])})
            while True:
                frame = ws_read_frame(self.rfile)
                if frame is None:
                    break
                opcode, payload = frame
                if opcode == 0x8:  # close
                    try:
                        conn.sendall(bytes([0x88, 0x00]))
                    except Exception:
                        pass
                    break
                if opcode == 0x9:  # ping frame -> pong frame
                    try:
                        conn.sendall(bytes([0x8A, len(payload)]) + payload)
                    except Exception:
                        break
                    continue
                if opcode == 0x1:  # text
                    try:
                        msg = json.loads(payload.decode("utf-8"))
                    except Exception:
                        continue
                    if isinstance(msg, dict) and msg.get("event") == "ping":
                        try:
                            ws_send(conn, {"event": "pong"})
                        except Exception:
                            break
        except Exception:
            pass
        finally:
            with WS_LOCK:
                WS_CLIENTS.discard(conn)
            try:
                conn.close()
            except Exception:
                pass


def live_push_loop():
    """Every 30s, while WS clients are connected, push a synthetic scene."""
    import time
    i = 0
    while True:
        time.sleep(30)
        with WS_LOCK:
            connected = bool(WS_CLIENTS)
        if not connected:
            continue
        summary, stype = LIVE_ROTATION[i % len(LIVE_ROTATION)]
        i += 1
        scene = add_mock_scene(summary, stype)
        ws_broadcast({"event": "scene", "scene": scene_summary(scene)})
        ws_broadcast(status_event())


def main():
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    threading.Thread(target=live_push_loop, daemon=True).start()
    print("Scene mock server on http://localhost:%d/api/v1" % PORT)
    print("WS live on ws://localhost:%d/api/v1/live" % PORT)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
