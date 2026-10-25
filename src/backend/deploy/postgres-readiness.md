# Scene backend: Postgres readiness for Google Cloud SQL

- Workflow: `scene-cloudsql-deploy`, worker 1 (Postgres readiness verifier)
- Date: 2026-10-25
- Code reviewed (read only, no backend files edited):
  `~/workspace/scene-backend/server.py`,
  `~/workspace/scene-backend/app/postgres_store.py`,
  `~/workspace/scene-backend/app/routes.py` (auth),
  `~/workspace/scene-backend/app/seed.py`,
  `~/workspace/scene-backend/schema.sql`,
  `~/workspace/scene-backend/requirements.txt`
- Also spot-checked: `app/sqlite_store.py` (parity reference),
  `app/vector_store.py` (ChromaDB import path only).

## Verdict: NOT READY as-is, but one line away from demo-ready

**Blocking change: exactly 1.** Add `psycopg[binary]` to `requirements.txt`
(change 1 below). Without it, a Cloud Run build from `requirements.txt`
will crash on `import psycopg` in `app/postgres_store.py`, even though
`server.py` deliberately checks `DATABASE_URL` before that import.

Everything else in the Postgres path is already Cloud SQL compatible:
the URL is passed through verbatim, the schema uses no extensions or
superuser-only statements, and the store self-creates its tables and
seeds on an empty database. The remaining items are hardening and
deploy configuration, not redesigns. For a hackathon demo, changes 1
plus the deploy settings in changes 7-9 are sufficient. Changes 2-4
should land before anything is treated as production, and change 5
should land if the team does not want canned demo data in Cloud SQL.

No credentials appear in this file. All URLs below use placeholders:
`PROJECT`, `REGION`, `INSTANCE`, `DBUSER`, `DBPASSWORD`, `DBNAME`.

---

## 1. DATABASE_URL handling: pass-through, both schemes, params preserved

### What the code does

`server.py`:

```python
store_env = os.environ.get("SCENE_STORE", "sqlite").lower()
# ...
elif store_env == "postgres":
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("SCENE_STORE=postgres requires DATABASE_URL to be set",
              file=sys.stderr)
        raise SystemExit(2)
    from app.postgres_store import PostgresStore
    store = PostgresStore(database_url)
```

`app/postgres_store.py`:

```python
def __init__(self, database_url=None):
    if not database_url:
        raise ValueError("PostgresStore requires a database_url")
    self._lock = threading.RLock()
    self._conn = psycopg.connect(database_url)
```

The URL is passed **verbatim** to `psycopg.connect()`. There is no
scheme rewriting, no parameter stripping, no logging of the URL
(verified by inspection: the URL is never printed or included in an
error message, which is correct for Secret Manager values).

### Schemes: `postgresql://` and `postgres://` both work, no code change needed

psycopg 3 accepts a libpq-style connection string. libpq documents
`postgresql://` with `postgres://` as the backward-compatible alias,
and psycopg 3 documents the conninfo as "a `postgresql://` url or a
list of `key=value` pairs". Both schemes therefore reach the same
parser. No `postgres://` -> `postgresql://` rewrite is required.
An optional defensive rewrite is given in change 6, but it is not
needed for correctness.

A keyword/value DSN also works verbatim, because that is the other
form `psycopg.connect()` accepts:

```
host=/cloudsql/PROJECT:REGION:INSTANCE dbname=DBNAME user=DBUSER password=DBPASSWORD
```

That DSN form is a useful fallback if URL-encoding of the Unix socket
path ever proves troublesome (see below).

### `sslmode` and `host` params: passed through, with two caveats

Query parameters on the URL are parsed by psycopg/libpq into
connection parameters, so they survive untouched. That covers both
Cloud SQL access patterns:

**A. Auth Proxy Unix socket (recommended for Cloud Run).**
Cloud Run attaches the proxy as `--add-cloudsql-instances` (deploy
worker wiring, not code), and the proxy listens on
`/cloudsql/PROJECT:REGION:INSTANCE`. The URL form is:

```
postgresql://DBUSER:DBPASSWORD@/DBNAME?host=/cloudsql/PROJECT:REGION:INSTANCE
```

Notes:

- The empty host before `/DBNAME` is intentional and standard for
  Unix-socket URLs: the real host comes from the `?host=` query
  parameter.
- The socket path contains slashes and colons. In a query value those
  characters are legal unencoded, but the value must survive shell and
  Secret Manager handling intact. If it ever gets mangled, switch to
  the keyword DSN form above instead of debugging URL encoding.
- With a Unix socket, libpq does not use TLS to the proxy socket
  itself (the proxy encrypts the hop to Cloud SQL). Do **not** add
  `sslmode=require` to the socket form unless testing shows it is
  needed; it is at best ignored and at worst confusing. Leave
  `sslmode` off for the socket form.

**B. Public IP with TLS (fallback, not recommended for Cloud Run).**

```
postgresql://DBUSER:DBPASSWORD@PUBLIC_IP:5432/DBNAME?sslmode=require
```

Notes:

- `sslmode=require` is passed through, but the code does **not** set
  any SSL default. If `DATABASE_URL` omits `sslmode`, a public-IP
  connection will negotiate whatever libpq's default (`prefer`)
  gives, which may be unencrypted, and will fail outright if the
  instance is configured to require SSL. So for public IP, `sslmode`
  must be supplied in the URL itself (change 7). There is no code
  fix for this; it is a URL-construction rule.
- `sslmode=require` encrypts but does **not** verify the server
  certificate. `verify-ca` / `verify-full` additionally need the
  Cloud SQL server CA certificate (`sslrootcert`), which the current
  code has no provision for. For the demo, `require` is acceptable;
  for production, use the proxy (pattern A) or add `sslrootcert`.

### Small gaps in URL handling (non-blocking)

- **No whitespace stripping.** `server.py` tests `if not database_url`
  but does not `.strip()`. A trailing newline copied into a Secret
  Manager value would be passed to psycopg and fail to connect.
  Secret Manager values served as Cloud Run env vars normally do not
  carry a trailing newline, but change 6 strips defensively.
- **No `connect_timeout`.** `psycopg.connect(database_url)` sets no
  timeout, so a black-holed endpoint can hang startup past Cloud
  Run's expectations. Prefer adding `?connect_timeout=10` to the URL
  (pass-through, no code change) rather than editing the call.
- **Special characters in the password must be URL-encoded** in the
  URL form (for example `@`, `:`, `/`, `?`, `#`, `%`). This is a
  URL-construction rule, not a code bug. The keyword DSN form avoids
  it for passwords containing those characters only if quoted per
  libpq rules.
- **IAM database authentication is not supported.** IAM auth uses a
  short-lived token as the password. The store holds one connection
  for the life of the process (section 2), so a token password would
  expire under it. Use a built-in Postgres user with a Secret
  Manager password, not IAM auth, with this code.

### Verdict on (1)

Pass. No scheme or parameter code change is required. The only
required action is constructing `DATABASE_URL` in one of the two
forms above and putting it in Secret Manager.

---

## 2. Connection handling: one shared connection, one lock, no pooling

### What the code does

`PostgresStore.__init__` opens exactly one connection:

```python
self._conn = psycopg.connect(database_url)
```

Every method runs under a single `threading.RLock`, and every
mutation commits immediately, per statement. This mirrors the SQLite
store's one-lock rule, and it is **correct** for psycopg: a psycopg
connection must not be used concurrently from multiple threads, and
the lock prevents that. `ThreadingHTTPServer` (one thread per
request in `server.py`) is therefore safe against concurrent-use
corruption.

### What that means under Cloud Run concurrency

- **Throughput is serialized at the database.** All requests in one
  container instance queue on the same `RLock`, so database work is
  effectively single-threaded per instance even though HTTP handling
  is threaded. For demo traffic (one phone, one lens, occasional Ask)
  this is fine. For sustained concurrent traffic it is a bottleneck:
  each `list_*` call loads whole tables into Python and filters there
  (see section 3), so a slow list blocks every other request behind
  the lock.
- **Connection count is minimal, which is good for Cloud SQL.** One
  container instance holds exactly one connection. Ten instances
  hold ten connections, far below Cloud SQL's default
  `max_connections` (100). There is no pool-exhaustion risk from
  this design; the risk runs the other way (under-utilization).
- **Scale-out does not share state safely beyond the database.**
  The `RLock` is per-process, so two Cloud Run instances do not
  serialize against each other. That is fine because Postgres itself
  serializes writes, but it interacts with seeding (section 5) and
  with the spend counter (`add_spend` is read-modify-write across
  two statements, so two instances can interleave and lose an
  increment; acceptable for a demo spend display, not for money).
- **No reconnect, no retry, no rollback-on-error. This is the real
  fragility.** Three failure modes all leave the single connection
  unusable until the process restarts:
  1. **Idle / dropped connection.** Cloud SQL, the Auth Proxy, and
     Cloud Run networking can all close an idle TCP connection
     (maintenance, failover, proxy restart, idle timeout). The next
     store call then raises an operational error, and because the
     code never re-connects, every later call fails the same way.
     There is no `conn.check()`, no keepalive parameter, and no
     `close()` / re-open path anywhere in the store.
  2. **Poisoned transaction.** psycopg 3 defaults to
     `autocommit=False`. Reads (`_get`, `_all`, `_count`) open a
     transaction that is only closed by the next committing write.
     If any statement fails (duplicate key, transient Cloud SQL
     error), the transaction enters the aborted state and every
     subsequent statement on that connection fails until a rollback,
     and the code has no `try/except: rollback` anywhere. One failed
     insert can therefore wedge the whole backend until restart.
  3. **Startup failure is fail-fast, which is good and bad.**
     `PostgresStore.__init__` runs the schema DDL before the HTTP
     server starts, so if Cloud SQL is unreachable at boot, the
     container crashes and Cloud Run restarts it (crash loop until
     the database is reachable). That is the correct fail-fast
     behavior for a demo, but it means a transient Cloud SQL outage
     at deploy time looks like a bad container image.
- **No connection close on shutdown.** The store has no `close()`
  method and `server.py` has no shutdown hook. Cloud Run SIGTERM
  handling will just kill the process; Postgres cleans up the
  orphaned connection itself. Not a blocker.
- **Long-lived read transactions.** Because reads do not commit, a
  read-heavy idle period leaves the connection "idle in transaction",
  holding a snapshot that can delay `VACUUM` on Cloud SQL. Minor at
  demo volume, worth fixing with the autocommit/rollback change.

### Recommendation

For the hackathon demo, keep the single-connection design and
mitigate it with deploy settings (change 8: keep the instance count
low, ideally `--max-instances=1` for the demo, so there is exactly
one connection and no multi-instance seed race). Do **not** retrofit
a pool during the hackathon: pooling requires restructuring the lock
(a pool plus a single global lock defeats the pool; a pool without
the lock requires auditing every method for connection checkout
discipline), and the current design is proven by the 61/61 local
tests.

After the demo, the correct fix is change 2 (reconnect + rollback
wrapper) first, and only then, if throughput demands it, a
`psycopg_pool.ConnectionPool` with per-operation checkout
(`psycopg[binary,pool]`). Change 2 alone fixes the wedge-on-error
and dropped-connection failure modes without changing the threading
model.

### Verdict on (2)

Works for a demo, fragile for production. Single connection plus
`RLock` is safe but serializing, and the missing reconnect/rollback
path is the largest post-demo reliability gap after the missing
dependency.

---

## 3. `schema.sql` compatibility with managed Postgres: clean

`schema.sql` contains exactly nine `CREATE TABLE IF NOT EXISTS`
statements, and the inline `_SCHEMA_SQL` in `postgres_store.py` is
**byte-identical to `schema.sql`** (verified by diff, ignoring
trailing whitespace). The two cannot drift silently unless someone
edits one and not the other; see the drift note below.

| Construct | Cloud SQL verdict |
|---|---|
| `BIGSERIAL PRIMARY KEY` (`seq`) | Fine. Standard sequence-backed identity on every managed Postgres version (14/15/16/17). No superuser needed. |
| `TEXT NOT NULL UNIQUE` (`id`) | Fine. Unique index created automatically. |
| `JSONB NOT NULL` (`data`) | Fine. Native since Postgres 9.4; no extension. |
| `TEXT PRIMARY KEY` (`meta.key`), nullable `TEXT` value | Fine. |
| Extensions (`CREATE EXTENSION`) | None. No `pgcrypto`, `pgvector`, `PostGIS`, or anything else. Nothing to enable on Cloud SQL. |
| Superuser-only statements | None. No roles, grants, `ALTER SYSTEM`, `VACUUM`, tablespaces, or replication settings. A least-privilege user with `CREATE` on the schema works for first boot. |
| Foreign keys | None, by design (same as SQLite). No constraint migration risk. |
| Indexes beyond PK/unique | None. `ORDER BY seq` uses the PK index; `id` lookups use the unique index. All list/filter logic runs in Python over full-table reads, so there is no missing-index failure, only a scaling ceiling (fine for hundreds of scenes, not for tens of thousands). |

Two operational notes:

- **The app does not need `schema.sql` at all.** `PostgresStore`
  runs the identical DDL itself on every startup, statement by
  statement (the code notes psycopg's extended query protocol does
  not reliably accept multi-statement strings, so the split-on-`;`
  loop is intentional). Pre-running `schema.sql` manually is
  harmless and idempotent (`IF NOT EXISTS`), but it is optional.
  Do not treat `schema.sql` as a migration: if the schema ever
  changes, `IF NOT EXISTS` will **not** alter an existing table,
  so a changed column would require a manual `ALTER TABLE` or a
  fresh database.
- **The database itself is not created by the code.** The app
  creates tables inside the database named in `DATABASE_URL`; it
  cannot create that database. The deploy worker must run
  `CREATE DATABASE DBNAME;` (or pick the existing `postgres`
  database) before first boot, or startup will fail with
  "database does not exist". The connecting user also needs
  `CREATE` privilege on that database for the first-boot DDL.
- **Concurrent first boot is safe for DDL.** Two instances running
  `CREATE TABLE IF NOT EXISTS` at the same time do not error; the
  second gets a notice, not a failure. (Seeding is a different story;
  see section 5.)

### Verdict on (3)

Pass. No schema change needed for Cloud SQL.

---

## 4. `requirements.txt` gaps: `psycopg` is missing (the blocker)

Current `requirements.txt` (complete):

```text
google-genai>=2.3.0
faster-whisper          # deliberately unpinned, per its own comment
```

It even says "Postgres / ChromaDB / vector-store dependencies belong
to the data orchestrator's scope, not this file." That scoping note
is now stale for the Cloud SQL deploy: the Postgres dependency must
live in the file the Cloud Run build installs from, or the build
will not include it.

Only `app/postgres_store.py` imports psycopg:

```python
import psycopg
from psycopg.types.json import Jsonb
```

That import is **psycopg v3 only**. `psycopg2` / `psycopg2-binary`
will not satisfy it (`psycopg.types.json` does not exist in v2), so
the v2 package is not a substitute.

### Exact addition (change 1, blocking)

Add to `requirements.txt`:

```text
# Postgres (Cloud SQL + local). psycopg v3 only: postgres_store.py
# imports psycopg.types.json, which does not exist in psycopg2.
# [binary] bundles libpq in the wheel, so the Cloud Run build needs
# no libpq-dev / gcc. Pin the exact version that `pip show psycopg`
# reports on the Mac after installing, and record it here.
psycopg[binary]>=3.1
```

Version notes:

- `>=3.1` is the floor, not a guess at the Mac's version: the code
  uses only stable v3 APIs (`psycopg.connect`, `Jsonb`, cursors,
  `commit`), all present since 3.0, and 3.1 is a safe floor that
  still allows the current 3.2.x line. Before freezing the deploy,
  run `pip show psycopg` on the Mac (where it was installed
  separately) and tighten this to `==<that version>` so the Cloud
  Run image matches the tested Mac install exactly.
- `psycopg[binary]` (not plain `psycopg`) is the point for Cloud
  Run: plain `psycopg` is a source distribution that needs libpq
  headers and a compiler at build time, which a slim Cloud Run
  image does not have. The `[binary]` wheel works on Linux x86_64
  and arm64, matching Cloud Run.
- Do **not** add `psycopg_pool` now. It is only needed if the
  pooling redesign in section 2 is adopted later; adding it without
  the code change buys nothing. If pooling is adopted, the line
  becomes `psycopg[binary,pool]>=3.1` instead.
- Nothing else is missing for the Postgres path. `google-genai`
  and `faster-whisper` are already present for the real services,
  auth (`routes.py` `check_auth`) and the MCP stdio transport are
  stdlib-only per the file's own comments, and ChromaDB is not in
  the server path: `server.py` wires `MockEmbedder()`, not
  `VectorStore`, and `app/vector_store.py` imports `chromadb`
  lazily inside a try/except that degrades silently. Do not add
  `chromadb` to `requirements.txt` for the Cloud SQL move; it would
  also be pointless on Cloud Run, where `PersistentClient` would
  write to an ephemeral filesystem that vanishes per instance.

### Verdict on (4)

Fail, one line. This is the only code change that blocks the deploy.

---

## 5. Seed behavior on a fresh empty Cloud SQL instance: works, with two caveats

### The happy path works unchanged

`server.py` (Postgres branch):

```python
store = PostgresStore(database_url)
if store.is_empty():
    seed(store)
```

`is_empty()` returns true only when all eight record tables
(`sessions`, `chunks`, `scenes`, `facts`, `people`, `pins`,
`followup_runs`, `followups`) have zero rows. On a fresh Cloud SQL
instance the sequence is:

1. `PostgresStore.__init__` creates the nine tables (no manual
   `schema.sql` run needed).
2. `is_empty()` is true, so `seed(store)` runs.
3. Seed inserts, via the Postgres store's own methods (all of which
   `seed.py` needs are present: `_seed_session`, `_seed_person`,
   `add_scene`, `add_fact`, `add_spend`): 1 today session (status
   `ended`, 2026-10-25 00:00 PDT), 8 scenes in chronological order
   (09:15-12:10 PDT, newest-first on read), 3 facts, 2 people
   (Maya, Unknown), spend `1.84`, live session `None`, pins and
   followups empty. `current_session_id()` then falls back to the
   seeded today session, exactly as on SQLite.
4. On restart, `is_empty()` is false, so seed does not re-run and
   demo data is never duplicated by a restart. This matches the
   tested SQLite behavior.

No seed code change is needed for the fresh-instance case.

### Caveat A: there is no way to opt out of seeding

There is no `SCENE_SEED` flag. The only way to get a clean Cloud SQL
database (no canned Maya demo data) is to pre-insert a dummy row
before first boot, or to delete the seeded rows afterward. If the
team wants the Cloud SQL instance to start empty for real demo
recordings, add change 5. If the team wants the canned demo data
there as a fallback (the current SQLite behavior), do nothing.

### Caveat B: seed is not atomic and not race-safe

- Seed performs roughly 14 separate commits (each `_insert` /
  `_meta_set` commits per statement). A crash mid-seed (container
  killed during cold start, database failover) leaves a partially
  seeded database, and on the next boot `is_empty()` is false, so
  seeding never resumes or completes. Recovery is manual
  (`TRUNCATE` all tables and restart, or a fresh database).
- Two Cloud Run instances booting simultaneously on an empty
  database can both observe `is_empty() == True` and both seed.
  Nothing prevents this: seed rows carry fresh UUIDs, so the second
  seed's inserts succeed rather than conflicting, producing
  duplicated demo content (16 scenes, two Maya rows, spend `3.68`).
  The single-instance deploy mitigation in change 8 removes this
  race for the demo. The durable fix is a seed marker in `meta`
  claimed with `ON CONFLICT DO NOTHING` plus a re-check, which is
  sketched in change 5 but is not required for a single-instance
  demo.

### Verdict on (5)

Pass for a single-instance fresh boot. Add the opt-out flag only if
the team wants a clean (unseeded) Cloud SQL start.

---

## 6. Any other code changes needed for Cloud SQL

### Already Cloud Run compatible, no change needed

- **Port and bind.** `server.py` binds `ThreadingHTTPServer` to
  `0.0.0.0` on `PORT` (env, default 8000). Cloud Run sets `PORT`
  (8080) and requires listening on `0.0.0.0`, so this already
  matches. No change.
- **Secret handling.** The code reads `DATABASE_URL`,
  `SCENE_API_TOKEN`, and `GEMINI_API_KEY` from the environment and
  never logs any of them. That is exactly the shape Secret Manager
  as Cloud Run env vars needs. No code change; the deploy worker
  wires the secrets, the code just reads env.
- **Auth.** `routes.py` `check_auth()` is real Bearer auth behind
  `AUTH_ENABLED`, failing closed when enabled without a token.
  The default is **off**, which is correct for local LAN testing
  and wrong for a public Cloud Run URL (see change 9). Note the
  documented WS gap: the WebSocket path does not accept `?token=`;
  with auth enabled, a WS client must present the `Authorization`
  header on the upgrade request (the `_dispatch` gate runs before
  `_route`, so the handshake is gated). Verify the phone/lens WS
  client sends that header before enabling auth, or the live socket
  will 401 while REST works.
- **Table-name interpolation.** `_insert` / `_save` / `_get` /
  `_all` / `_count` interpolate the table name with `%` formatting,
  but the table names come only from the internal `_TABLES`
  constant, never from user input. Not an injection vector.

### Minor, non-blocking observations (no action for the demo)

- **Timestamps use local time.** `postgres_store._now()` uses
  `datetime.now().astimezone()`, so on Cloud Run (UTC) new scenes
  will be stamped in UTC while seed rows are fixed PDT. Display
  code that assumes PDT will show a shift for live rows. Cosmetic;
  do not change mid-hackathon.
- **Full-table list reads.** Every list method loads all rows and
  filters in Python. Fine for demo volume; it is the reason the
  lock-hold time grows with scene count (section 2).
- **Spend counter race across instances.** `add_spend` is
  read-modify-write without a single-statement atomic update, so
  concurrent instances can lose increments. Cosmetic for a spend
  display; the atomic form would be one `UPDATE ... SET value =
  ...` in SQL, but that changes the locked store semantics and is
  out of scope for the demo.

---

## Numbered change list

### Blocking

**1. Add `psycopg[binary]` to `requirements.txt`.** (Section 4.)
File: `~/workspace/scene-backend/requirements.txt` (report only;
not edited by this worker).

```text
# Postgres (Cloud SQL + local). psycopg v3 only: postgres_store.py
# imports psycopg.types.json, which does not exist in psycopg2.
# [binary] bundles libpq in the wheel, so the Cloud Run build needs
# no libpq-dev / gcc. Pin the exact version that `pip show psycopg`
# reports on the Mac after installing, and record it here.
psycopg[binary]>=3.1
```

Then tighten `>=3.1` to `==<Mac-installed version>` once that
version is known, and rebuild the Cloud Run image from
`requirements.txt` (not from a manually installed package).

### Recommended (post-demo reliability, or pre-demo if time allows)

**2. Reconnect + rollback wrapper in `PostgresStore`.** (Section 2.)
Smallest fix that removes the wedge-on-error and dropped-connection
modes without changing the threading model. Sketch (adapt to the
file's style; keep the `RLock`):

```python
import psycopg

def _connect(self):
    # Called with the lock held. Fresh connection per (re)connect.
    self._conn = psycopg.connect(
        self._database_url, connect_timeout=10)

def _ensure_connection(self):
    # psycopg Connection.check() raises if the connection is broken;
    # .closed is nonzero when closed. Reconnect on either.
    try:
        if self._conn.closed or self._conn.check() is not None:
            self._connect()
    except Exception:
        self._connect()
```

And in each helper, roll back before re-raising so one failed
statement cannot poison the shared connection:

```python
def _insert(self, table, record):
    key = record[_KEY_FIELD[table]]
    try:
        with self._conn.cursor() as cur:
            cur.execute(
                "INSERT INTO %s (id, data) VALUES (%%s, %%s)" % table,
                (key, Jsonb(record)))
        self._conn.commit()
    except Exception:
        self._conn.rollback()
        raise
```

Apply the same `try/except: rollback; raise` shape to `_save` and
`_meta_set`, and call `_ensure_connection()` at the top of every
public method (or once per locked entry point). This requires
storing `self._database_url = database_url` in `__init__`. Do not
adopt a pool in the same change.

**3. (Later, only if throughput demands it) Pooling.** Replace the
single shared connection with `psycopg_pool.ConnectionPool`
(`psycopg[binary,pool]>=3.1`) and check a connection out per
operation instead of sharing one under a global lock. This is a
larger refactor (lock discipline changes) and is explicitly not
recommended during the hackathon.

**4. Keep `schema.sql` and `_SCHEMA_SQL` in sync, or delete one.**
They are identical today. If either is ever edited, edit both in
the same commit, or better, make `PostgresStore` read `schema.sql`
at startup instead of embedding a copy. No action needed today.

### Optional (only if the team wants it)

**5. Seed opt-out (and single-flight seed marker).**
In `server.py`, Postgres branch (and the SQLite branch for parity):

```python
store = PostgresStore(database_url)
if store.is_empty() and os.environ.get("SCENE_SEED", "1") != "0":
    seed(store)
```

With `SCENE_SEED=0`, a fresh Cloud SQL instance starts clean. For
the multi-instance race, additionally claim a marker row in `meta`
(`key='seeded'`) with `INSERT ... ON CONFLICT DO NOTHING` before
seeding and skip seeding if the claim loses; that requires a small
store helper and is only needed if `--max-instances` is raised
above 1.

**6. Defensive URL normalization (optional, not required).**
In `server.py`, before constructing the store:

```python
database_url = os.environ.get("DATABASE_URL", "").strip()
if database_url.startswith("postgres://"):
    database_url = "postgresql://" + database_url[len("postgres://"):]
```

This is cosmetic: psycopg accepts both schemes (section 1). The
`.strip()` half is the useful part (trailing-newline protection).
Do not add this if it risks a merge conflict with parallel work;
the URL forms in section 1 work without it.

### Deploy configuration (no code change, deploy worker owns these)

**7. Construct `DATABASE_URL` correctly and store it in Secret Manager.**
- Auth Proxy socket (recommended):
  `postgresql://DBUSER:DBPASSWORD@/DBNAME?host=/cloudsql/PROJECT:REGION:INSTANCE`
  plus `?connect_timeout=10` if desired (append with `&`).
- Public IP (fallback only):
  `postgresql://DBUSER:DBPASSWORD@PUBLIC_IP:5432/DBNAME?sslmode=require&connect_timeout=10`
- URL-encode special characters in `DBPASSWORD`; or use the
  keyword DSN form from section 1.
- The target database (`DBNAME`) must already exist
  (`CREATE DATABASE DBNAME;`); the app creates tables, not the
  database. The connecting user needs `CREATE` on that database
  for first boot.

**8. Constrain Cloud Run scaling for the demo.**
`--max-instances=1` (and consider `--min-instances=1` to avoid
cold-start connection churn) removes the double-seed race and
keeps the single-connection design at exactly one connection.
Raise the limit only after change 2 (and ideally change 5's seed
marker) lands.

**9. Turn auth on for the public URL, after verifying the WS client.**
Set `AUTH_ENABLED=1` and `SCENE_API_TOKEN` (Secret Manager) on the
Cloud Run service; otherwise the public API accepts unauthenticated
writes (sessions, pins, people). Before flipping it, verify the
phone/lens WebSocket client sends the `Authorization: Bearer`
header on the upgrade request, since `?token=` is not accepted
(`routes.py` docstring) and the `_dispatch` gate applies to WS too.

---

## Pre-flight checklist for the deploy worker (fresh Cloud SQL instance)

1. `CREATE DATABASE DBNAME;` on the instance; connecting user has
   `CREATE` on it.
2. `requirements.txt` includes change 1; Cloud Run image is built
   from it (verify with `pip show psycopg` inside the image if
   possible; a missing `psycopg` fails at first Postgres boot,
   not at build time, because the import is inside the Postgres
   branch).
3. `SCENE_STORE=postgres`, `DATABASE_URL` from Secret Manager in
   one of the section 1 forms (socket form preferred).
4. `PORT` left to Cloud Run's value; no code change needed.
5. `AUTH_ENABLED` / `SCENE_API_TOKEN` per change 9.
6. First-boot expectation: tables auto-created, seed runs once
   (1 session, 8 scenes, 3 facts, 2 people, spend `1.84`) unless
   `SCENE_SEED=0` (change 5) is set. Restart expectation: no
   re-seed, data persists.
7. Failure signature to watch: crash loop at startup with a
   connection error means the database is unreachable or `DBNAME`
   does not exist, not a code bug; a crash with
   `ModuleNotFoundError: psycopg` means change 1 did not make it
   into the image.

---

## What was NOT verified here

- Live connection parsing was not executed in this VM because
  `psycopg` is not installed here (the Mac install is separate).
  The scheme and parameter pass-through claims rest on the code
  path (verbatim `psycopg.connect(database_url)`) plus libpq /
  psycopg 3 documentation, not on a live Cloud SQL connection in
  this check. The deploy worker should run one live smoke test
  (boot with the real `DATABASE_URL`, confirm seed rows appear,
  restart, confirm no duplicate seed) before calling the deploy
  done.
- No GCP provisioning, no live Argon calls, no backend edits, no
  git operations, and no device calls were performed, per the task
  limits.
