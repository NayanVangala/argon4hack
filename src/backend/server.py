#!/usr/bin/env python3
"""Scene backend entrypoint (module 1 owns it).

Wiring per ~/workspace/scene-backend/INTERFACES.md, exactly:
  store = SQLiteStore() by default (SCENE_STORE=memory for InMemoryStore,
    SCENE_STORE=postgres for PostgresStore with DATABASE_URL);
  seed(store) once on an empty store
  broadcaster = routes' broadcast object
  transcriber, analyzer, attributor, embedder = real services
    (FasterWhisperTranscriber, ArgonSceneAnalyzer, FaceVoiceAttributor,
    MockEmbedder), each degrading to mock behavior without deps/key
  ingest = IngestPipeline(store, broadcaster, ...)
  ask = AskService(store, ArgonReasoning())
  followthrough = FollowThroughService(store)
  handler = create_handler(store, ingest, ask, followthrough)

ThreadingHTTPServer on 0.0.0.0:PORT (env PORT, default 8000).
Prints the REST and WS URLs, serves forever. Core is stdlib only;
real services add optional third-party deps (requirements.txt).

Other modules (store, seed, services, ingest, ask, followthrough) are
imported inside main() so that importing this file never fails before
they land; the wiring itself is unchanged.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from http.server import ThreadingHTTPServer

from app.routes import Broadcaster, create_handler


def main():
    from app.ask import AskService, MockReasoning
    from app.followthrough import FollowThroughService
    from app.ingest import IngestPipeline
    from app.seed import seed
    from app.services import make_mock_services
    from app.store import InMemoryStore

    # Store selection (Phase 1 persistence advance): SQLite is the
    # default; SCENE_STORE=memory opts back to the in-memory store.
    # Any other value also selects SQLite. SQLite seeds the canned demo
    # data only when the database tables are empty, so restarts never
    # duplicate seeds; the memory store is fresh per process, so it is
    # always seeded once.
    store_env = os.environ.get("SCENE_STORE", "sqlite").lower()
    if store_env == "memory":
        store = InMemoryStore()
        seed(store)
    elif store_env == "postgres":
        # URL check BEFORE the PostgresStore import, so the fail-fast
        # exit 2 holds even when psycopg is not installed (design sec 5
        # lists the import first; see builder report for the reason).
        database_url = os.environ.get("DATABASE_URL")
        if not database_url:
            print("SCENE_STORE=postgres requires DATABASE_URL to be set",
                  file=sys.stderr)
            raise SystemExit(2)
        from app.postgres_store import PostgresStore
        store = PostgresStore(database_url)
        if store.is_empty():
            seed(store)
    else:
        from app.sqlite_store import SQLiteStore
        db_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "scene.db")
        store = SQLiteStore(db_path)
        if store.is_empty():
            seed(store)
    broadcaster = Broadcaster(store)
    # Real services wired 2026-10-25. Graceful degradation is built
    # into each service: without faster-whisper installed, the
    # transcriber falls back to the mock transcript shape; without
    # GEMINI_API_KEY, Argon services fall back to mock drafts and
    # reasoning with a clear log line. So this wiring behaves exactly
    # like the mock until deps + key are present.
    from app.services import (ArgonReasoning, ArgonSceneAnalyzer,
                              FaceVoiceAttributor,
                              FasterWhisperTranscriber, MockEmbedder)
    transcriber = FasterWhisperTranscriber()
    analyzer = ArgonSceneAnalyzer()
    attributor = FaceVoiceAttributor()
    embedder = MockEmbedder()
    ingest = IngestPipeline(store, broadcaster, transcriber, analyzer,
                            attributor, embedder)
    ask = AskService(store, ArgonReasoning())
    followthrough = FollowThroughService(store)
    handler = create_handler(store, ingest, ask, followthrough,
                             broadcaster=broadcaster)

    port = int(os.environ.get("PORT", "8000"))
    server = ThreadingHTTPServer(("0.0.0.0", port), handler)
    print("Scene backend REST on http://localhost:%d/api/v1" % port, flush=True)
    print("Scene backend WS live on ws://localhost:%d/api/v1/live" % port,
          flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
