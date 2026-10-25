#!/usr/bin/env python3
"""Scene backend routes: thin REST + WS live layer (module 1).

Builds to ~/workspace/scene-backend/INTERFACES.md (Routes section) exactly.
Where plan 01 disagreed with INTERFACES.md, INTERFACES.md wins, notably:
- store method names: status_snapshot() (not get_status()), create_pin()
  (not add_pin()), enroll_person(name, photo_thumb=None)
- ingest method: process_chunk(session_id, start_ts, end_ts,
  video_path, audio_path) (not ingest_chunk())
- ask/followthrough methods: ask.ask(), ask.list_facts(),
  followthrough.generate_run() / list_followups() / approve_followup() /
  dismiss_followup()
- unknown session end -> 404 (old mock returned 200 unconditionally)
- unparsable limit -> 400 (old mock crashed on int())
- no synthetic 30s WS push (old mock only)
- malformed/non-dict JSON -> 400 (old mock silently returned {} for
  non-dict bodies)

Thin layer only: parse, validate, call one store/service method,
serialize to the contract shape. No Argon, embedding, or verification
logic here. Constructor injection only; no globals, no model imports.

Projection helpers scene_summary()/scene_detail() live in store.py per
INTERFACES.md; this module tries to import them and falls back to local
copies with the exact old-mock field lists, so this module stays
importable and testable before store.py lands.
"""

import base64
import hashlib
import json
import os
import re
import struct
import tempfile
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

_SUMMARY_FIELDS = ("id", "start_ts", "end_ts", "summary", "quote",
                   "thumb_url", "type", "verified", "confidence")
_DETAIL_FIELDS = ("id", "session_id", "start_ts", "end_ts", "summary",
                  "objects", "people", "actions", "visible_text", "type",
                  "confidence", "critique", "transcript", "keyframes",
                  "pinned")
# REST detail omits quote/verified (contract shape); the stored record
# keeps them. The mock's detail list also omits thumb_url; kept here.


def _fallback_summary(scene):
    return {k: scene.get(k) for k in _SUMMARY_FIELDS}


def _fallback_detail(scene):
    return {k: scene.get(k) for k in _DETAIL_FIELDS}


try:  # store.py owns these once it lands; prefer its copies.
    from .store import scene_summary as _store_summary, scene_detail as _store_detail
    scene_summary, scene_detail = _store_summary, _store_detail
except Exception:  # pragma: no cover - store.py not built yet
    try:
        from app.store import scene_summary as _store_summary, scene_detail as _store_detail
        scene_summary, scene_detail = _store_summary, _store_detail
    except Exception:
        scene_summary, scene_detail = _fallback_summary, _fallback_detail


def check_auth(handler=None):
    """Real Bearer auth, behind the AUTH_ENABLED env flag (default OFF).

    AUTH_ENABLED off (unset, or anything other than 1/true/yes/on,
    case-insensitive) -> True, preserving the old unenforced behavior
    and keeping all existing tests passing.

    AUTH_ENABLED on -> require an Authorization header "Bearer <token>"
    exactly matching the SCENE_API_TOKEN env var. Header parsing: the
    "Bearer " prefix is matched case-insensitively and surrounding
    whitespace is stripped; the token itself is compared exactly.
    Missing/wrong header -> False (dispatch already turns False into
    a 401 "unauthorized"). If AUTH_ENABLED is on but SCENE_API_TOKEN
    is unset/empty -> False, fail CLOSED, with a warning printed.
    If handler is None: off -> True, on -> False (no credentials
    presented). WS ?token= is deliberately NOT checked here (out of
    scope); the WS path relies on the same dispatch gate for HTTP and
    otherwise ignores the query token, as before.
    """
    enabled = os.environ.get("AUTH_ENABLED", "").strip().lower() in (
        "1", "true", "yes", "on")
    if not enabled:
        return True
    expected = os.environ.get("SCENE_API_TOKEN", "")
    if not expected:
        print("WARNING: AUTH_ENABLED is on but SCENE_API_TOKEN is unset; "
              "refusing all requests (fail closed).", flush=True)
        return False
    if handler is None:
        return False
    try:
        headers = getattr(handler, "headers", None)
        presented = headers.get("Authorization") if headers is not None else None
    except Exception:
        presented = None
    if not isinstance(presented, str):
        return False
    value = presented.strip()
    if value[:7].lower() != "bearer ":
        return False
    token = value[7:].strip()
    return token == expected and token != ""


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# WebSocket framing (RFC 6455 helpers, ported from the old mock).
# Separable and unit-testable without a socket.
# ---------------------------------------------------------------------------

def ws_accept_key(key):
    return base64.b64encode(
        hashlib.sha1((key + WS_GUID).encode()).digest()).decode()


def ws_frame_opcode(opcode, payload):
    """Build one unmasked server->client frame for the given opcode."""
    if isinstance(payload, str):
        payload = payload.encode("utf-8")
    header = bytearray([0x80 | (opcode & 0x0F)])
    n = len(payload)
    if n < 126:
        header.append(n)
    elif n < 65536:
        header.append(126)
        header += struct.pack("!H", n)
    else:
        header.append(127)
        header += struct.pack("!Q", n)
    return bytes(header) + payload


def ws_frame(payload):
    """Build one unmasked server->client text frame."""
    return ws_frame_opcode(0x1, payload)


def ws_send(conn, obj):
    conn.sendall(ws_frame(json.dumps(obj)))


def ws_read_frame(rfile):
    """Read one client->server frame. Returns (opcode, payload) or None."""
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


# ---------------------------------------------------------------------------
# Broadcaster: routes owns the WS client set. Ingest calls these after
# storing; routes call broadcast_status() after session start/end.
# ---------------------------------------------------------------------------

class Broadcaster:
    def __init__(self, store=None):
        self.store = store
        self._clients = set()
        self._lock = threading.Lock()

    def add(self, conn):
        with self._lock:
            self._clients.add(conn)

    def discard(self, conn):
        with self._lock:
            self._clients.discard(conn)

    def client_count(self):
        with self._lock:
            return len(self._clients)

    def broadcast(self, obj):
        with self._lock:
            clients = list(self._clients)
        dead = []
        for conn in clients:
            try:
                ws_send(conn, obj)
            except Exception:
                dead.append(conn)
        if dead:
            with self._lock:
                self._clients.difference_update(dead)

    def broadcast_scene(self, summary):
        self.broadcast({"event": "scene", "scene": summary})

    def broadcast_status(self, snapshot=None):
        if snapshot is None and self.store is not None:
            try:
                snapshot = self.store.status_snapshot()
            except Exception:
                snapshot = None
        if snapshot is None:
            snapshot = {"recording": False, "scene_count": 0}
        event = {"event": "status"}
        event.update(snapshot)
        self.broadcast(event)

    def broadcast_error(self, code, message):
        self.broadcast({"event": "error", "code": code, "message": message})


# ---------------------------------------------------------------------------
# Multipart parsing (stdlib only; cgi is gone). Raw bytes split on the
# boundary manually. Returns (fields, files) or None on malformed input.
# fields: name -> str (UTF-8 text parts); files: name -> bytes.
# ---------------------------------------------------------------------------

def parse_multipart(body, content_type):
    if not body or not content_type:
        return None
    m = re.search(r"boundary=([^;]+)", content_type)
    if not m:
        return None
    boundary = m.group(1).strip().strip('"').encode("utf-8")
    delimiter = b"--" + boundary
    fields, files = {}, {}
    for segment in body.split(delimiter)[1:]:
        if segment.startswith(b"\r\n"):
            segment = segment[2:]
        elif segment.startswith(b"\n"):
            segment = segment[1:]
        if segment.endswith(b"\r\n"):
            segment = segment[:-2]
        elif segment.endswith(b"\n"):
            segment = segment[:-1]
        if segment in (b"", b"--"):
            continue
        if b"\r\n\r\n" in segment:
            raw_headers, data = segment.split(b"\r\n\r\n", 1)
        elif b"\n\n" in segment:
            raw_headers, data = segment.split(b"\n\n", 1)
        else:
            return None
        disp = None
        for line in raw_headers.decode("utf-8", "replace").splitlines():
            if line.lower().startswith("content-disposition:"):
                disp = line
        if disp is None:
            return None
        name_m = re.search(r'name="([^"]*)"', disp)
        if not name_m:
            return None
        name = name_m.group(1)
        file_m = re.search(r'filename="([^"]*)"', disp)
        if file_m is not None:
            files[name] = data
        else:
            fields[name] = data.decode("utf-8", "replace")
    return fields, files


def _write_temp(data, suffix):
    fd, path = tempfile.mkstemp(suffix=suffix)
    try:
        os.write(fd, data)
    finally:
        os.close(fd)
    return path


# ---------------------------------------------------------------------------
# Handler factory: constructor injection is the wiring seam.
# ---------------------------------------------------------------------------

def create_handler(store, ingest, ask, followthrough, broadcaster=None):
    """Return the BaseHTTPRequestHandler subclass for ThreadingHTTPServer."""
    if broadcaster is None:
        broadcaster = Broadcaster(store)
    else:
        if broadcaster.store is None:
            broadcaster.store = store

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        # Injected dependencies (per-class, not globals).
        _store = store
        _ingest = ingest
        _ask = ask
        _followthrough = followthrough
        _broadcaster = broadcaster

        def log_message(self, fmt, *args):
            print("%s %s" % (self.command, self.path))

        # -- response plumbing ------------------------------------------

        def _send_json(self, code, obj):
            body = json.dumps(obj).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Headers",
                             "Authorization, Content-Type")
            self.send_header("Access-Control-Allow-Methods",
                             "GET, POST, OPTIONS")
            self.end_headers()
            self.wfile.write(body)

        def _send_empty(self, code):
            self.send_response(code)
            self.send_header("Content-Length", "0")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Headers",
                             "Authorization, Content-Type")
            self.send_header("Access-Control-Allow-Methods",
                             "GET, POST, OPTIONS")
            self.end_headers()

        def _error(self, code, err_code, message):
            self._send_json(code, {"error": {"code": err_code,
                                             "message": message}})

        def _read_body(self):
            try:
                n = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                n = 0
            return self.rfile.read(n) if n > 0 else b""

        def _read_json(self):
            """Returns (obj, ok). Empty body -> ({}, True). Malformed or
            non-dict -> (None, False), caller sends 400 bad_request."""
            raw = self._read_body()
            if not raw:
                return {}, True
            try:
                obj = json.loads(raw.decode("utf-8"))
            except Exception:
                return None, False
            if not isinstance(obj, dict):
                return None, False
            return obj, True

        def _parse_limit(self, query, key, default):
            raw = query.get(key, [None])[0]
            if raw is None or raw == "":
                return default, True
            try:
                value = int(raw)
            except (ValueError, TypeError):
                return None, False
            if value < 0:
                return None, False
            return value, True

        # -- tolerant store/service accessors (fakes in tests may omit
        #    helpers; the real store implements all of them) -----------

        def _status_snapshot(self):
            try:
                snap = self._store.status_snapshot()
                if isinstance(snap, dict):
                    if isinstance(snap.get("spend_usd"), (int, float)):
                        snap = dict(snap)
                        snap["spend_usd"] = round(snap["spend_usd"], 2)
                    return snap
            except Exception:
                pass
            recording = False
            try:
                recording = self._store.get_live_session() is not None
            except Exception:
                pass
            return {"recording": recording,
                    "session_id": self._current_session_id(),
                    "scene_count": self._scene_count(),
                    "last_scene_ts": self._last_scene_ts(),
                    "spend_usd": 0.0}

        def _current_session_id(self):
            try:
                return self._store.current_session_id()
            except Exception:
                return None

        def _scene_count(self):
            try:
                return self._status_snapshot_raw_count()
            except Exception:
                return 0

        def _status_snapshot_raw_count(self):
            snap = self._store.status_snapshot()
            return snap.get("scene_count", 0)

        def _last_scene_ts(self):
            scenes, _ = self._list_scenes_today(1, None)
            return scenes[0].get("start_ts") if scenes else None

        def _list_scenes_today(self, limit, before):
            result = self._store.list_scenes_today(limit, before)
            if isinstance(result, tuple) and len(result) == 2:
                return result[0], result[1]
            return result, None

        def _latest_scene_id(self):
            scenes, _ = self._list_scenes_today(1, None)
            return scenes[0].get("id") if scenes else None

        # -- HTTP verbs ---------------------------------------------------

        def do_OPTIONS(self):
            self._send_empty(204)

        def do_GET(self):
            self._dispatch()

        def do_POST(self):
            self._dispatch()

        def _dispatch(self):
            if not check_auth(self):
                return self._error(401, "unauthorized", "Token expired, re-pair.")
            try:
                self._route()
            except Exception:
                # Generic message, no traceback (locked error envelope).
                try:
                    self._error(500, "internal_error", "Internal error.")
                except Exception:
                    pass

        def _route(self):
            parsed = urlparse(self.path)
            path, query = parsed.path, parse_qs(parsed.query)
            method = self.command

            if method == "GET" and path in ("/api/v1/live", "/live"):
                return self._handle_ws()
            if method == "GET" and path in ("/", "/api/v1", "/api/v1/"):
                return self._send_json(200, {"service": "scene-backend",
                                             "rest": "/api/v1",
                                             "ws": "/api/v1/live"})
            if method == "GET" and path == "/api/v1/status":
                return self._send_json(200, self._status_snapshot())
            if method == "GET" and path == "/api/v1/scenes/today":
                limit, ok = self._parse_limit(query, "limit", 50)
                if not ok:
                    return self._error(400, "bad_request",
                                       "limit must be a non-negative integer.")
                before = query.get("before", [None])[0]
                scenes, next_before = self._list_scenes_today(limit, before)
                return self._send_json(200, {
                    "scenes": [scene_summary(s) for s in scenes],
                    "next_before": next_before})
            m = re.fullmatch(r"/api/v1/scenes/([^/]+)", path)
            if method == "GET" and m:
                scene = self._store.get_scene(m.group(1))
                if scene is None:
                    return self._error(404, "scene_not_found",
                                       "No scene with that id.")
                return self._send_json(200, scene_detail(scene))
            if method == "GET" and path == "/api/v1/people":
                return self._send_json(200,
                                       {"people": self._store.list_people()})
            if method == "GET" and path == "/api/v1/facts":
                limit, ok = self._parse_limit(query, "limit", 20)
                if not ok:
                    return self._error(400, "bad_request",
                                       "limit must be a non-negative integer.")
                actor = query.get("actor", [None])[0] or None
                result = self._ask.list_facts(actor=actor, limit=limit)
                if isinstance(result, dict) and "facts" in result:
                    return self._send_json(200, result)
                return self._send_json(200, {"facts": result})
            if method == "GET" and path == "/api/v1/followups":
                run_id = query.get("run_id", [None])[0] or None
                status = query.get("status", [None])[0] or None
                result = self._followthrough.list_followups(run_id=run_id,
                                                            status=status)
                if isinstance(result, dict) and "followups" in result:
                    return self._send_json(200, result)
                return self._send_json(200, {"followups": result})

            if method == "POST" and path == "/api/v1/sessions":
                self._read_body()
                session = self._store.create_session()
                host = self.headers.get("Host", "localhost:8000")
                resp = {"id": session.get("id"),
                        "started_at": session.get("started_at"),
                        "status": "live",
                        "ws_url": "ws://%s/api/v1/live" % host}
                self._send_json(201, resp)
                self._broadcaster.broadcast_status()
                return
            m = re.fullmatch(r"/api/v1/sessions/([^/]+)/end", path)
            if method == "POST" and m:
                self._read_body()
                sid = m.group(1)
                try:
                    ended = self._store.end_session(sid)
                except KeyError:
                    return self._error(404, "not_found",
                                       "No session with that id.")
                snap = self._status_snapshot()
                resp = {"id": sid,
                        "ended_at": (ended.get("ended_at")
                                     if isinstance(ended, dict) else None)
                        or now_iso(),
                        "status": "ended",
                        "scene_count": snap.get("scene_count", 0)}
                self._send_json(200, resp)
                self._broadcaster.broadcast_status()
                return
            if method == "POST" and path == "/api/v1/chunks":
                return self._handle_chunks()
            if method == "POST" and path == "/api/v1/ask":
                body, ok = self._read_json()
                if not ok:
                    return self._error(400, "bad_request",
                                       "Request body must be a JSON object.")
                session_id = body.get("session_id") or self._current_session_id()
                try:
                    top_k = int(body.get("top_k", 8))
                except (ValueError, TypeError):
                    top_k = 8
                result = self._ask.ask(query=body.get("query") or "",
                                       session_id=session_id, top_k=top_k)
                return self._send_json(200, result)
            if method == "POST" and path == "/api/v1/pin":
                body, ok = self._read_json()
                if not ok:
                    return self._error(400, "bad_request",
                                       "Request body must be a JSON object.")
                scene_id = body.get("scene_id") or self._latest_scene_id()
                if scene_id is None:
                    return self._error(404, "scene_not_found",
                                       "No scene with that id.")
                try:
                    pin = self._store.create_pin(scene_id, body.get("note"))
                except KeyError:
                    return self._error(404, "scene_not_found",
                                       "No scene with that id.")
                pin_id = pin.get("pin_id") if isinstance(pin, dict) else None
                return self._send_json(201, {"pinned": True,
                                             "pin_id": pin_id,
                                             "scene_id": scene_id})
            if method == "POST" and path == "/api/v1/people":
                return self._handle_enroll()
            if method == "POST" and path == "/api/v1/followups/generate":
                body, ok = self._read_json()
                if not ok:
                    return self._error(400, "bad_request",
                                       "Request body must be a JSON object.")
                run = self._followthrough.generate_run(
                    body.get("session_id") or None)
                resp = {"run_id": run.get("run_id"),
                        "status": run.get("status", "running"),
                        "steps": run.get("steps", ["find_promises",
                                                   "verify_quotes",
                                                   "draft_followups"])}
                return self._send_json(202, resp)
            m = re.fullmatch(r"/api/v1/followups/([^/]+)/(approve|dismiss)",
                             path)
            if method == "POST" and m:
                self._read_body()
                fid, action = m.group(1), m.group(2)
                try:
                    if action == "approve":
                        result = self._followthrough.approve_followup(fid)
                    else:
                        result = self._followthrough.dismiss_followup(fid)
                except ValueError:
                    return self._error(400, "not_approvable",
                                       "Unverified drafts are never approved; "
                                       "they stay under needs_review.")
                except KeyError:
                    return self._error(404, "followup_not_found",
                                       "No follow-up with that id.")
                status = (result.get("status") if isinstance(result, dict)
                          else None) or action + "d"
                # approve -> "approved", dismiss -> "dismissed"
                if action == "approve":
                    status = "approved"
                else:
                    status = "dismissed"
                return self._send_json(200, {"id": fid, "status": status})

            return self._error(404, "not_found", "Unknown route: %s" % path)

        def _handle_chunks(self):
            raw = self._read_body()
            parsed_mp = parse_multipart(raw, self.headers.get("Content-Type"))
            if parsed_mp is None:
                return self._error(400, "bad_request",
                                   "Expected multipart form data.")
            fields, files = parsed_mp
            if "video" not in files or "audio" not in files:
                return self._error(400, "bad_request",
                                   "Missing video or audio part.")
            session_id = fields.get("session_id") or None
            if session_id is None:
                live = None
                try:
                    live = self._store.get_live_session()
                except Exception:
                    live = None
                if isinstance(live, dict) and live.get("id"):
                    session_id = live["id"]
                else:
                    session_id = self._current_session_id()
            start_ts = fields.get("start_ts") or now_iso()
            end_ts = fields.get("end_ts") or start_ts
            video_path = _write_temp(files["video"], ".mp4")
            audio_path = _write_temp(files["audio"], ".wav")
            try:
                result = self._ingest.process_chunk(session_id, start_ts,
                                                    end_ts, video_path,
                                                    audio_path)
            finally:
                # Mock discards the files after the reply; real phase
                # moves them to durable storage instead.
                for p in (video_path, audio_path):
                    try:
                        os.unlink(p)
                    except OSError:
                        pass
            if not isinstance(result, dict):
                result = {}
            return self._send_json(202, {
                "chunk_id": result.get("chunk_id"),
                "session_id": result.get("session_id", session_id),
                "start_ts": result.get("start_ts", start_ts),
                "end_ts": result.get("end_ts", end_ts),
                "status": "received"})

        def _handle_enroll(self):
            raw = self._read_body()
            parsed_mp = parse_multipart(raw, self.headers.get("Content-Type"))
            if parsed_mp is None:
                return self._error(400, "bad_request",
                                   "Expected multipart form data.")
            fields, files = parsed_mp
            # voice_sample accepted, ignored in mock; photo bytes are not
            # stored, the store takes a placeholder thumb URL.
            name = fields.get("name") or "Enrolled Speaker"
            person = self._store.enroll_person(
                name, "https://cdn.helloscene.xyz/p/enrolled.jpg")
            resp = {"id": person.get("id") if isinstance(person, dict) else None,
                    "name": person.get("name") if isinstance(person, dict)
                    else name,
                    "verified": True}
            return self._send_json(201, resp)

        # -- WebSocket ------------------------------------------------------

        def _handle_ws(self):
            key = self.headers.get("Sec-WebSocket-Key")
            upgrade = (self.headers.get("Upgrade") or "").lower()
            if not key or "websocket" not in upgrade:
                return self._error(400, "websocket_upgrade_required",
                                   "Connect with a WebSocket client.")
            accept = ws_accept_key(key)
            self.send_response(101)
            self.send_header("Upgrade", "websocket")
            self.send_header("Connection", "Upgrade")
            self.send_header("Sec-WebSocket-Accept", accept)
            self.end_headers()
            conn = self.connection
            self.close_connection = True  # hijacked: no further HTTP here
            self._broadcaster.add(conn)
            try:
                ws_send(conn, {"event": "status", **self._status_snapshot()})
                scenes, _ = self._list_scenes_today(1, None)
                if scenes:
                    ws_send(conn, {"event": "scene",
                                   "scene": scene_summary(scenes[0])})
                while True:
                    frame = ws_read_frame(self.rfile)
                    if frame is None:
                        break
                    opcode, payload = frame
                    if opcode == 0x8:  # close -> echo close, drop
                        try:
                            conn.sendall(ws_frame_opcode(0x8, b""))
                        except Exception:
                            pass
                        break
                    if opcode == 0x9:  # ping frame -> pong, same payload
                        try:
                            conn.sendall(ws_frame_opcode(0xA, payload))
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
                    # Other opcodes/text ignored (lens never writes).
            except Exception:
                pass
            finally:
                self._broadcaster.discard(conn)
                try:
                    conn.close()
                except Exception:
                    pass

    return Handler
