#!/usr/bin/env python3
"""Scene backend MCP stdio transport (module 6 transport).

Run from ~/workspace/scene-backend:

    python3 -m app.mcp_stdio

Stdlib only. Builds one store exactly the way server.py does:
SCENE_STORE=memory -> InMemoryStore + seed, otherwise SQLiteStore
(scene.db next to server.py) + seed-if-empty. Then serves the MCP
tools over stdin/stdout as one JSON object per line (JSON-RPC 2.0
shape):

    {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
    {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
    {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
     "params": {"name": "search_scenes", "arguments": {"query": "..."}}}

Method handling (per INTERFACES.md, MCP section: transport only lists
TOOL_SCHEMAS and dispatches TOOLS[name](store, **arguments), via
call_tool(store, name, arguments)):

    initialize  -> server info + capabilities
    tools/list  -> TOOL_SCHEMAS (all 5 tools)
    tools/call  -> call_tool(store, name, arguments); the tool's return
                   dict (including {"error": ...} dicts for unknown
                   tools / bad input) is the JSON-RPC result
    ping        -> {}
    anything else -> JSON-RPC error -32601 (method not found)

A malformed line gets a -32700 parse-error response and the loop keeps
serving; the loop NEVER crashes on bad input (unexpected per-request
errors become -32603 and serving continues). EOF ends the process
cleanly. Blank lines are skipped. Notifications (no "id", method
starting with "notifications/") get no response, per JSON-RPC.

Auth: none on this transport (local stdio process, same trust as the
server process itself). The REST Bearer check in routes.check_auth
does not apply here. WS ?token= handling is likewise out of scope.
"""

import json
import os
import sys

# Make `app.*` imports work regardless of how this module is invoked,
# as long as this file lives in <scene-backend>/app/. When run as
# `python3 -m app.mcp_stdio` from scene-backend this is a no-op
# (cwd is already on sys.path); it also covers direct-path invocation.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from app.mcp import TOOL_SCHEMAS, call_tool
from app.seed import seed
from app.store import InMemoryStore

__all__ = ["build_store", "handle_request", "serve", "main"]

_SERVER_INFO = {"name": "scene-backend", "version": "0.1.0"}


def build_store():
    """Build the store exactly the way server.py does.

    SCENE_STORE=memory -> fresh InMemoryStore, seeded once.
    Anything else (including unset) -> SQLiteStore at scene.db next
    to server.py, seeded only when empty (restarts never duplicate).
    """
    if os.environ.get("SCENE_STORE", "sqlite").lower() == "memory":
        store = InMemoryStore()
        seed(store)
        return store
    from app.sqlite_store import SQLiteStore
    db_path = os.path.join(_ROOT, "scene.db")
    store = SQLiteStore(db_path)
    if store.is_empty():
        seed(store)
    return store


def handle_request(store, request):
    """Handle one decoded JSON-RPC request dict.

    Returns the response dict, or None when no response is due
    (notifications). Never raises for bad request shapes: those
    become JSON-RPC error responses.
    """
    if not isinstance(request, dict):
        return {"jsonrpc": "2.0", "id": None,
                "error": {"code": -32600, "message": "Invalid Request: "
                          "request must be a JSON object"}}
    req_id = request.get("id")
    method = request.get("method")
    if not isinstance(method, str) or not method:
        return {"jsonrpc": "2.0", "id": req_id,
                "error": {"code": -32600, "message": "Invalid Request: "
                          "missing method"}}
    if req_id is None and method.startswith("notifications/"):
        return None
    if method == "initialize":
        return {"jsonrpc": "2.0", "id": req_id,
                "result": {"protocolVersion": "2024-11-05",
                           "capabilities": {"tools": {}},
                           "serverInfo": dict(_SERVER_INFO)}}
    if method == "ping":
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": req_id,
                "result": {"tools": list(TOOL_SCHEMAS.values())}}
    if method == "tools/call":
        params = request.get("params")
        if not isinstance(params, dict):
            return {"jsonrpc": "2.0", "id": req_id,
                    "error": {"code": -32602, "message": "Invalid params: "
                              "tools/call params must be an object"}}
        name = params.get("name")
        if not isinstance(name, str) or not name:
            return {"jsonrpc": "2.0", "id": req_id,
                    "error": {"code": -32602, "message": "Invalid params: "
                              "tools/call requires a tool name"}}
        arguments = params.get("arguments")
        if arguments is None:
            arguments = {}
        # call_tool never raises for bad input: unknown tools and bad
        # arguments come back as {"error": {...}} result dicts.
        result = call_tool(store, name, arguments)
        return {"jsonrpc": "2.0", "id": req_id, "result": result}
    return {"jsonrpc": "2.0", "id": req_id,
            "error": {"code": -32601,
                      "message": "Method not found: %s" % method}}


def serve(store, instream, outstream):
    """Serve one JSON object per line until EOF. Never crashes on a
    bad line: malformed input gets a parse-error response and the
    loop continues. Returns on EOF or a broken output pipe."""
    for line in instream:
        if not line.strip():
            continue
        try:
            request = json.loads(line)
        except Exception as exc:
            response = {"jsonrpc": "2.0", "id": None,
                        "error": {"code": -32700,
                                  "message": "Parse error: %s" % exc}}
            try:
                outstream.write(json.dumps(response) + "\n")
                outstream.flush()
            except BrokenPipeError:
                return
            continue
        try:
            response = handle_request(store, request)
        except Exception as exc:  # never crash the loop
            response = {"jsonrpc": "2.0", "id": None,
                        "error": {"code": -32603,
                                  "message": "Internal error: %s" % exc}}
            try:
                req_id = request.get("id") if isinstance(request, dict) else None
            except Exception:
                req_id = None
            response["id"] = req_id
        if response is None:
            continue
        try:
            outstream.write(json.dumps(response) + "\n")
            outstream.flush()
        except BrokenPipeError:
            return


def main():
    store = build_store()
    serve(store, sys.stdin, sys.stdout)


if __name__ == "__main__":
    main()
