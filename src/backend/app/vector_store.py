"""Vector storage for embeddings, over ChromaDB (module: data layer).

Built to /tmp/scene-data-design.md section 4 and
~/workspace/scene-backend/INTERFACES.md (lock doc wins on conflict).

ChromaDB is OPTIONAL. This module degrades silently and never crashes
ingest: a missing install, or any client/collection creation failure,
leaves a live but inert VectorStore with available == False. When
unavailable, every add_* returns None, every query_*/match_* returns
[], counts() returns all zeros, close() is a no-op, and nothing
touches disk.

This module never imports the Postgres store, and the Postgres store
never imports it. Ingest/services call this module and pass resulting
vector ids into a scene's embedding_refs; when ChromaDB is
unavailable, embedding_refs stays None, exactly as in the mock phase.

Collections (ChromaDB metadata values must be scalars, so arrays and
nested objects are never stored as metadata; they go in document or
are omitted):

- text_memories: id convention ``text:<scene_id>:<index>``; document
  is summary plus transcript text; metadata {scene_id, start_ts,
  end_ts}. This is the collection Embedder feeds.
- visual_memories: id convention ``visual:<scene_id>:<index>``;
  document is the keyframe's visible text joined, or empty when none;
  metadata {scene_id, start_ts, end_ts, keyframe_url} where
  keyframe_url is omitted when unknown.
- face_prints: id convention ``face:<person_id or name>``; document
  is the person name; metadata {person, person_id} plus enrolled_at
  when known. One print per person id; re-enrollment upserts the
  same id.
- voice_prints: id convention ``voice:<person_id or name>``; same
  shape and upsert rule as face_prints.

Query return shape (uniform across query_*/match_*): a list of dicts
{id, scene_id or person, distance, document, metadata}, with scene_id
present for text/visual results and person present for face/voice
results; empty list when nothing matches or ChromaDB is unavailable.
Retrieval fusion across collections happens in the caller, not here.
"""

import os

try:
    import chromadb
except Exception:  # noqa: BLE001 - any import failure degrades, never raises
    chromadb = None

# Collection name constants.
TEXT_MEMORIES = "text_memories"
VISUAL_MEMORIES = "visual_memories"
FACE_PRINTS = "face_prints"
VOICE_PRINTS = "voice_prints"
COLLECTIONS = (TEXT_MEMORIES, VISUAL_MEMORIES, FACE_PRINTS, VOICE_PRINTS)


def _default_persist_directory():
    """CHROMA_DIR env when set, else a chroma/ directory next to
    server.py, resolved from the server file location, not CWD (same
    convention as scene.db). server.py lives next to the app/
    directory that holds this file."""
    env_dir = os.environ.get("CHROMA_DIR")
    if env_dir:
        return env_dir
    server_dir = os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))
    return os.path.join(server_dir, "chroma")


def _format_results(result, key_field):
    """Normalize one ChromaDB query result dict into the uniform
    return shape. key_field is "scene_id" (text/visual) or "person"
    (face/voice); the key value is read from the stored metadata."""
    if not isinstance(result, dict):
        return []
    ids = result.get("ids") or []
    distances = result.get("distances")
    documents = result.get("documents")
    metadatas = result.get("metadatas")
    # ChromaDB returns one list per query embedding; we query with a
    # single embedding, so take the first (only) inner list.
    ids = ids[0] if ids else []
    distances = distances[0] if distances else []
    documents = documents[0] if documents else []
    metadatas = metadatas[0] if metadatas else []
    out = []
    for i, result_id in enumerate(ids):
        metadata = metadatas[i] if i < len(metadatas) else None
        if not isinstance(metadata, dict):
            metadata = {}
        entry = {
            "id": result_id,
            "distance": distances[i] if i < len(distances) else None,
            "document": documents[i] if i < len(documents) else None,
            "metadata": metadata,
        }
        entry[key_field] = metadata.get(key_field)
        out.append(entry)
    return out


class VectorStore:
    """Embeddings-only storage over four ChromaDB collections.

    Constructor injection: pass a ready client (e.g. an ephemeral
    client in tests) to use it instead of a persistent client. A
    supplied client is used as given, so collection creation through
    it is what decides availability in that case.
    """

    def __init__(self, persist_directory=None, client=None):
        if persist_directory is None:
            persist_directory = _default_persist_directory()
        self.persist_directory = persist_directory
        self._client = None
        self._collections = {}
        self._available = False
        # Missing install + no supplied client: inert, never raises.
        if client is None and chromadb is None:
            return
        try:
            if client is not None:
                self._client = client
            else:
                # Directory created on init only when ChromaDB is
                # available (we only reach here when it is).
                os.makedirs(self.persist_directory, exist_ok=True)
                self._client = chromadb.PersistentClient(
                    path=self.persist_directory)
            collections = {}
            for name in COLLECTIONS:
                collections[name] = \
                    self._client.get_or_create_collection(name)
            self._collections = collections
            self._available = True
        except Exception:  # noqa: BLE001 - any failure degrades
            self._client = None
            self._collections = {}
            self._available = False

    @property
    def available(self):
        """True only when a client and all four collections exist."""
        return self._available

    def add_text_memory(self, id, embedding, document, scene_id,
                        start_ts, end_ts):
        """Store a text memory. Returns the id, or None when no
        vector was stored (unavailable, or a storage failure)."""
        if not self._available:
            return None
        collection = self._collections.get(TEXT_MEMORIES)
        if collection is None:
            return None
        try:
            collection.add(
                ids=[id],
                embeddings=[list(embedding)] if embedding is not None
                else None,
                documents=[document if document is not None else ""],
                metadatas=[{"scene_id": scene_id,
                            "start_ts": start_ts,
                            "end_ts": end_ts}],
            )
        except Exception:  # noqa: BLE001 - degrade, ingest stays safe
            return None
        return id

    def add_visual_memory(self, id, embedding, document, scene_id,
                          start_ts, end_ts, keyframe_url=None):
        """Store a visual memory. keyframe_url is omitted from
        metadata when unknown. Returns the id, or None."""
        if not self._available:
            return None
        collection = self._collections.get(VISUAL_MEMORIES)
        if collection is None:
            return None
        metadata = {"scene_id": scene_id,
                    "start_ts": start_ts,
                    "end_ts": end_ts}
        if keyframe_url:
            metadata["keyframe_url"] = keyframe_url
        try:
            collection.add(
                ids=[id],
                embeddings=[list(embedding)] if embedding is not None
                else None,
                documents=[document if document is not None else ""],
                metadatas=[metadata],
            )
        except Exception:  # noqa: BLE001 - degrade, ingest stays safe
            return None
        return id

    def add_face_print(self, id, embedding, person, person_id=None,
                       enrolled_at=None):
        """Store (upsert) one face print per person. Returns the id,
        or None. person_id defaults to the person name when omitted."""
        if not self._available:
            return None
        collection = self._collections.get(FACE_PRINTS)
        if collection is None:
            return None
        metadata = {"person": person,
                    "person_id": person_id if person_id is not None
                    else person}
        if enrolled_at is not None:
            metadata["enrolled_at"] = enrolled_at
        try:
            if hasattr(collection, "upsert"):
                collection.upsert(
                    ids=[id],
                    embeddings=[list(embedding)]
                    if embedding is not None else None,
                    documents=[person],
                    metadatas=[metadata],
                )
            else:
                collection.add(
                    ids=[id],
                    embeddings=[list(embedding)]
                    if embedding is not None else None,
                    documents=[person],
                    metadatas=[metadata],
                )
        except Exception:  # noqa: BLE001 - degrade, ingest stays safe
            return None
        return id

    def add_voice_print(self, id, embedding, person, person_id=None,
                        enrolled_at=None):
        """Store (upsert) one voice print per person. Returns the id,
        or None. person_id defaults to the person name when omitted."""
        if not self._available:
            return None
        collection = self._collections.get(VOICE_PRINTS)
        if collection is None:
            return None
        metadata = {"person": person,
                    "person_id": person_id if person_id is not None
                    else person}
        if enrolled_at is not None:
            metadata["enrolled_at"] = enrolled_at
        try:
            if hasattr(collection, "upsert"):
                collection.upsert(
                    ids=[id],
                    embeddings=[list(embedding)]
                    if embedding is not None else None,
                    documents=[person],
                    metadatas=[metadata],
                )
            else:
                collection.add(
                    ids=[id],
                    embeddings=[list(embedding)]
                    if embedding is not None else None,
                    documents=[person],
                    metadatas=[metadata],
                )
        except Exception:  # noqa: BLE001 - degrade, ingest stays safe
            return None
        return id

    def query_text_memories(self, embedding, n_results=8):
        """Nearest text memories, uniform return shape; [] when
        unavailable or nothing matches."""
        if not self._available:
            return []
        collection = self._collections.get(TEXT_MEMORIES)
        if collection is None:
            return []
        try:
            result = collection.query(
                query_embeddings=[list(embedding)]
                if embedding is not None else None,
                n_results=n_results,
                include=["documents", "metadatas", "distances"],
            )
        except Exception:  # noqa: BLE001 - degrade, never raise
            return []
        return _format_results(result, "scene_id")

    def query_visual_memories(self, embedding, n_results=8):
        """Nearest visual memories, uniform return shape; [] when
        unavailable or nothing matches."""
        if not self._available:
            return []
        collection = self._collections.get(VISUAL_MEMORIES)
        if collection is None:
            return []
        try:
            result = collection.query(
                query_embeddings=[list(embedding)]
                if embedding is not None else None,
                n_results=n_results,
                include=["documents", "metadatas", "distances"],
            )
        except Exception:  # noqa: BLE001 - degrade, never raise
            return []
        return _format_results(result, "scene_id")

    def match_face_print(self, embedding, n_results=1):
        """Nearest face prints, uniform return shape with person; []
        when unavailable or nothing matches."""
        if not self._available:
            return []
        collection = self._collections.get(FACE_PRINTS)
        if collection is None:
            return []
        try:
            result = collection.query(
                query_embeddings=[list(embedding)]
                if embedding is not None else None,
                n_results=n_results,
                include=["documents", "metadatas", "distances"],
            )
        except Exception:  # noqa: BLE001 - degrade, never raise
            return []
        return _format_results(result, "person")

    def match_voice_print(self, embedding, n_results=1):
        """Nearest voice prints, uniform return shape with person; []
        when unavailable or nothing matches."""
        if not self._available:
            return []
        collection = self._collections.get(VOICE_PRINTS)
        if collection is None:
            return []
        try:
            result = collection.query(
                query_embeddings=[list(embedding)]
                if embedding is not None else None,
                n_results=n_results,
                include=["documents", "metadatas", "distances"],
            )
        except Exception:  # noqa: BLE001 - degrade, never raise
            return []
        return _format_results(result, "person")

    def counts(self):
        """{collection_name: int} for all four collections; all zeros
        when unavailable."""
        if not self._available:
            return {name: 0 for name in COLLECTIONS}
        out = {}
        for name in COLLECTIONS:
            collection = self._collections.get(name)
            try:
                out[name] = collection.count() if collection is not \
                    None else 0
            except Exception:  # noqa: BLE001 - degrade per collection
                out[name] = 0
        return out

    def close(self):
        """No-op: the persistent client persists on write and needs
        no teardown; kept so callers can close unconditionally."""
        return None
