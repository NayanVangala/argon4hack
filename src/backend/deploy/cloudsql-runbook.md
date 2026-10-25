# Scene backend: Cloud SQL for PostgreSQL runbook

**Who does what.** All GCP console work in this runbook is Nayan's job, in
his own GCP account (the one with billing). The provisioned Google account
used for the hackathon is AI Studio API only and cannot do GCP console
work. Nothing here provisions anything by itself; every step below is a
console click or a command Nayan runs.

**What this moves.** Today the backend runs on Nayan's Mac with SQLite and
a LAN IP. This runbook moves only the database to Cloud SQL. The backend
code already supports Postgres: `server.py` selects it with
`SCENE_STORE=postgres` plus `DATABASE_URL`, and fails fast with exit code 2
if `DATABASE_URL` is missing. No code changes are needed for this move.

**Placeholders used throughout.** Replace these, never paste a real value
into a shared doc or chat:
- `PROJECT_ID` — Nayan's GCP project
- `INSTANCE_NAME` — the Cloud SQL instance name
- `REGION` — the GCP region (see step 2)
- `DB_NAME` — the application database
- `DB_USER` / `DB_PASSWORD` — the application database user and password
- `POSTGRES_PASSWORD` — the built-in `postgres` superuser password

**Recommended path, in one paragraph.** Create one small Postgres 16
instance in `us-west2` (Los Angeles, closest GCP region to Fremont / San
Francisco), database `scene`, app user `scene_app` with least-privilege
grants. Load `schema.sql` once via the Cloud SQL Auth Proxy from the Mac,
then run the API on Cloud Run attached to the instance and connect over
the native Unix socket (`/cloudsql/PROJECT_ID:REGION:INSTANCE_NAME`).
First boot on the fresh instance seeds the demo data automatically.
Verify reachability from the Mac (via proxy + `psql`) before deploying
the API, and verify the API with `GET /api/v1/status` after deploying.

---

## 0. Before you start

- [ ] You are signed into the GCP console with Nayan's own GCP account
      (billing enabled), not the AI Studio-only account.
- [ ] You have the backend copy with `server.py`,
      `app/postgres_store.py`, and `schema.sql` (workspace copy at
      `~/workspace/scene-backend/`).
- [ ] You know where the API will run: Cloud Run is the assumed target
      for the primary connection path below. If the API stays on the Mac
      for now, use the Auth Proxy path in step 5 instead and skip the
      Cloud Run socket step.

## 1. Project selection and APIs

1. Console: https://console.cloud.google.com/ — pick `PROJECT_ID` from
   the project picker at the top. If no suitable project exists, create
   one (any name; billing must be attached or instance creation fails).
2. Enable these APIs (Console > APIs & Services > Library, or Cloud Shell):
   - **Cloud SQL Admin API** (`sqladmin.googleapis.com`) — required.
     This is the one that manages the instance.
   - **Compute Engine API** (`compute.googleapis.com`) — required by
     Cloud SQL for its networking under the hood; enable it even though
     you are not creating VMs.
   - **Cloud Run Admin API** (`run.googleapis.com`) — required only if
     the API runs on Cloud Run (the recommended path).
   - **Secret Manager API** (`secretmanager.googleapis.com`) —
     recommended: store `DATABASE_URL` as a secret instead of a plain
     Cloud Run env var (see step 5).
3. Confirm billing is attached to `PROJECT_ID` (Billing page). Cloud SQL
   will not create an instance on a project without billing.

## 2. Create the instance

Console > SQL > Create instance > Choose PostgreSQL.

| Setting | Recommended value | Why / note |
| --- | --- | --- |
| Version | **PostgreSQL 16** | Any recent version works: `schema.sql` uses no extensions, no superuser statements, just 9 plain JSONB tables. 16 is stable and widely available. Do not pick anything older than 14. |
| Instance ID | `INSTANCE_NAME` (e.g. `scene-db`) | This becomes part of the connection name `PROJECT_ID:REGION:INSTANCE_NAME`. |
| Password | `POSTGRES_PASSWORD` | The built-in `postgres` user. Used once for schema load and grants, then kept out of the app. Generate it in a password manager; never reuse it as the app password. |
| Region | **`us-west2` (Los Angeles)** | Closest GCP region to Fremont and to the San Francisco demo venue, so lowest latency. Exception: if the Cloud Run service already lives in a different region, put the instance in that same region instead — same-region keeps the socket path fast. |
| Zonal availability | Single zone | A demo does not need high availability. Multi-zone doubles cost for no demo benefit. |
| Machine / tier | **`db-f1-micro` (shared-core)** | Smallest sensible tier for a demo weekend. Shared-core means the vCPU is shared with other tenants and can throttle under sustained load, and RAM is ~0.6 GB. That is fine for one demo session and the JSONB workload here. If queries feel laggy, step up to `db-g1-small` (dedicated-ish small tier, 1.7 GB) — one console edit, no data move. Watch the connection count too: micro tiers allow few concurrent connections, so do not point many API instances at it (see step 5). |
| Storage | **10 GB SSD, automatic storage increases ON** | 10 GB is the minimum and far more than the demo data needs. Auto-increase prevents a demo-day "disk full" failure. HDD is cheaper but slower; SSD is the default and worth it. |
| Automated backups | **ON (daily)** | Cheap insurance for the demo data. Keep the default backup window. |
| Point-in-time recovery (PITR) | **OFF** | Not needed for a short-lived demo instance; it adds storage cost. Daily backups are enough. |
| Deletion protection | **OFF for this instance** | This is a deliberate short-lived-demo choice: deletion protection blocks `gcloud sql instances delete` and console deletes, which would block teardown after the hackathon. If you would rather be protected during demo hours, turn it ON now and remember to turn it OFF before teardown (step 8). |
| Public IP | Leave enabled only if you need the public-IP path (step 5). For the recommended Cloud Run + proxy setup, public IP is not used by the app; you may still leave the default on and simply never authorize any IP, or disable it. Do not add `0.0.0.0/0` to authorized networks. | |
| Private IP / VPC | Not needed | Skip VPC setup for a demo weekend. The socket and proxy paths do not need it. |

Click Create and wait for the instance status to show **Running** (green
check). Creation takes a few minutes.

## 3. Database and user setup

Do this in Console > SQL > `INSTANCE_NAME` > Databases / Users, or in
`psql` via the proxy (step 4 gives the proxy command). The app must
**not** run as the `postgres` superuser.

1. **Database:** create database `DB_NAME` (recommended name: `scene`).
2. **App user:** create user `DB_USER` (recommended name: `scene_app`)
   with password `DB_PASSWORD`. This password is different from
   `POSTGRES_PASSWORD`.
3. **Load the schema as the admin user first** (step 4), then grant the
   app user least privilege. Grants are per-table because the schema has
   no ownership trickery; run these as `postgres` after `schema.sql`
   has created the tables:

```sql
-- Connect to the app database as postgres first.
GRANT CONNECT ON DATABASE "DB_NAME" TO "DB_USER";
\c DB_NAME
GRANT USAGE ON SCHEMA public TO "DB_USER";
GRANT SELECT, INSERT, UPDATE, DELETE ON
  sessions, chunks, scenes, facts, people, pins,
  followup_runs, followups, meta
  TO "DB_USER";
-- BIGSERIAL seq columns live on sequences; the app needs these to insert.
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO "DB_USER";
```

Notes on the grants:
- No `CREATE`, `DROP`, `ALTER`, `TRUNCATE`, or superuser rights for the
  app user. The app only reads/writes rows; it never creates tables.
  If a table is ever recreated from `schema.sql`, re-run the grants
  above for that table.
- `meta` is included: the backend stores `live_session_id`,
  `today_session_id`, and the spend counter there.
- The 9 tables are: `sessions`, `chunks`, `scenes`, `facts`, `people`,
  `pins`, `followup_runs`, `followups`, `meta`. If `\dt` shows fewer
  than 9, the schema load did not finish; re-run step 4 before going on.

## 4. Load schema.sql

`schema.sql` is idempotent (`CREATE TABLE IF NOT EXISTS`), so running it
twice is safe. Run it as the `postgres` admin user, not as the app user
(the app user has no DDL rights by design).

**Option A — Cloud SQL Auth Proxy from the Mac (recommended for loading).**

```bash
# 1. Install the proxy (once): https://cloud.google.com/sql/docs/mysql/sql-proxy
#    and authenticate once: gcloud auth login
#    (the account needs the Cloud SQL Client IAM role on PROJECT_ID)

# 2. Start the proxy (leave this terminal running):
cloud-sql-proxy PROJECT_ID:REGION:INSTANCE_NAME --port 5432

# 3. In a second terminal, load the schema:
psql "postgresql://postgres:POSTGRES_PASSWORD@127.0.0.1:5432/DB_NAME" \
  -f /path/to/schema.sql

# 4. Confirm all 9 tables exist:
psql "postgresql://postgres:POSTGRES_PASSWORD@127.0.0.1:5432/DB_NAME" \
  -c "\dt"
```

**Option B — Cloud Shell (no local install).**

```bash
# In console Cloud Shell, with schema.sql uploaded to the shell:
gcloud sql connect INSTANCE_NAME --user=postgres --database=DB_NAME
# then inside psql:
\i schema.sql
\dt
\q
```

After loading, run the grants from step 3 (or run grants before loading
is pointless: there is nothing to grant on until the tables exist).

## 5. Connection method (pick one primary path)

### Primary: Cloud Run native Unix socket (use this for the deployed API)

In the Cloud Run service settings, add a Cloud SQL connection for
`PROJECT_ID:REGION:INSTANCE_NAME`. Cloud Run then mounts the socket at
`/cloudsql/PROJECT_ID:REGION:INSTANCE_NAME`, and no proxy process or
public IP is needed. Set the env var (preferably from Secret Manager):

```
SCENE_STORE=postgres
DATABASE_URL=postgresql://DB_USER:DB_PASSWORD@/DB_NAME?host=/cloudsql/PROJECT_ID:REGION:INSTANCE_NAME
```

Notes:
- The empty host between `@` and `/` is intentional: psycopg v3 (the
  driver `postgres_store.py` uses) takes the socket directory from the
  `host` query parameter.
- No `sslmode` is needed on the socket path: the socket is local to the
  Cloud Run instance and authenticated by the Cloud SQL connection.
- Keep Cloud Run at **1 instance / low concurrency** for the demo. The
  store holds a single shared connection guarded by one lock, so extra
  instances do not speed it up and a micro-tier instance allows few
  concurrent connections.
- The API host also needs the Postgres driver, which is **not** in
  `requirements.txt` (that file deliberately excludes Postgres deps).
  Install it on the API host:

```bash
pip install "psycopg[binary]"
```

  Without it, `server.py` fails on import in the `postgres` branch
  (after the `DATABASE_URL` check, so a missing `DATABASE_URL` still
  exits 2 first).

### Alternative A: Cloud SQL Auth Proxy (use this for local testing)

Best for running the backend from the Mac against Cloud SQL before
deploying, and for the schema load in step 4. Start the proxy as above,
then:

```
SCENE_STORE=postgres
DATABASE_URL=postgresql://DB_USER:DB_PASSWORD@127.0.0.1:5432/DB_NAME
```

The proxy needs the Cloud SQL Client IAM role; it authenticates with
Nayan's GCP account, not with a database password, and it encrypts the
connection. Prefer this over public IP whenever the app is not on
Cloud Run.

### Alternative B: Public IP (last resort only)

Only if neither the socket nor the proxy is available. Authorize only
the specific IP that connects (Console > SQL > Connections > Authorized
networks; never `0.0.0.0/0`), and require TLS:

```
SCENE_STORE=postgres
DATABASE_URL=postgresql://DB_USER:DB_PASSWORD@PUBLIC_IP:5432/DB_NAME?sslmode=require
```

`sslmode=require` forces an encrypted connection; without it the
password and data cross the internet unencrypted. Do not use this path
for the deployed API if Cloud Run is available.

### DATABASE_URL format summary

| Path | `DATABASE_URL` |
| --- | --- |
| Cloud Run socket (primary) | `postgresql://DB_USER:DB_PASSWORD@/DB_NAME?host=/cloudsql/PROJECT_ID:REGION:INSTANCE_NAME` |
| Auth Proxy (local / schema load) | `postgresql://DB_USER:DB_PASSWORD@127.0.0.1:5432/DB_NAME` |
| Public IP (last resort) | `postgresql://DB_USER:DB_PASSWORD@PUBLIC_IP:5432/DB_NAME?sslmode=require` |

`DATABASE_URL` is passed verbatim to psycopg and is never logged by the
backend. Keep it in Secret Manager / a local `.env` file, never in code,
never in a repo, never pasted into a shared doc.

## 6. Seed behavior

- `server.py` calls `seed(store)` **only when `store.is_empty()` is
  true**, i.e. every record table is empty. So: load `schema.sql` into a
  fresh instance, boot the server once with `SCENE_STORE=postgres`,
  and the canned demo data seeds itself on first boot. Restarts never
  duplicate the seed, because the store is no longer empty.
- **To skip the seed** (e.g. you want a truly empty database for a live
  capture): make the store non-empty before first boot, or simply do
  not rely on it — the seed only fires on a fully empty store, so any
  real ingested row before the first seeded boot is impossible in
  practice. The realistic "skip" is: boot once, let it seed, then clear
  it (below) if you decide you want empty.
- **To re-run the seed from scratch** (demo-only, destructive): as the
  `postgres` user, wipe all tables and restart the server, which will
  see an empty store and seed again:

```sql
TRUNCATE sessions, chunks, scenes, facts, people, pins,
  followup_runs, followups, meta
  RESTART IDENTITY CASCADE;
```

  Then restart the API. Warning: this deletes live captured data too.
  Never run it on an instance holding anything you want to keep. For a
  partial reset (keep sessions, clear a bad seed), truncate only the
  tables you mean to, and remember `meta` holds the spend counter and
  live/today session ids.

## 7. Verify reachability BEFORE deploying the API

Do all of these from the Mac via the proxy (Option A, step 4). If any
step fails, fix it here; do not deploy the API hoping it will work.

1. **Instance is Running.** Console > SQL: status green, no errors.
2. **psql connects and tables exist:**

```bash
psql "postgresql://DB_USER:DB_PASSWORD@127.0.0.1:5432/DB_NAME" -c "\dt"
# Expect 9 tables. Then:
psql "postgresql://DB_USER:DB_PASSWORD@127.0.0.1:5432/DB_NAME" \
  -c "SELECT count(*) FROM sessions;"
```

   Connecting as `DB_USER` (not `postgres`) proves the app credentials
   and grants work. If `\dt` shows nothing as `DB_USER` but shows 9
   tables as `postgres`, the grants from step 3 were missed.
3. **Backend boots against Cloud SQL and seeds:**

```bash
SCENE_STORE=postgres \
DATABASE_URL="postgresql://DB_USER:DB_PASSWORD@127.0.0.1:5432/DB_NAME" \
python3 server.py
# Expect: "Scene backend REST on http://localhost:8000/api/v1"
# and no traceback. First boot on a fresh instance seeds the demo data.
```

4. **Smoke-test the API:**

```bash
curl http://localhost:8000/api/v1/status
curl http://localhost:8000/api/v1/scenes/today
```

   A JSON response (not a connection error) means the app-to-Cloud SQL
   path works end to end. Stop the local server (`Ctrl+C`).
5. **Only now deploy to Cloud Run** with the socket `DATABASE_URL`
   from step 5, then repeat the smoke test against the deployed URL:

```bash
curl https://CLOUD_RUN_URL/api/v1/status
```

   If the deployed API fails but the local proxy run worked, the fault
   is in the Cloud Run side (missing Cloud SQL connection, wrong
   socket `DATABASE_URL`, or `psycopg` not installed), not in the
   database.

## 8. Teardown after the hackathon

1. Export anything worth keeping first (`pg_dump` via the proxy).
2. If deletion protection was turned ON, turn it OFF (Console > SQL >
   instance > Edit).
3. Delete the instance (Console > SQL > instance > Delete). This stops
   billing. Deleting the instance does not delete the GCP project.
4. Revoke or rotate `DB_PASSWORD` / `POSTGRES_PASSWORD` if they were
   ever pasted anywhere shared.

## Troubleshooting

| Symptom | Likely cause / fix |
| --- | --- |
| Server exits with code 2 | `SCENE_STORE=postgres` but `DATABASE_URL` unset. Set it; the check runs before any import. |
| `ImportError: psycopg` | Driver not installed on the API host. `pip install "psycopg[binary]"`. |
| `psql` connects as `postgres` but `\dt` empty as `DB_USER` | Grants from step 3 not run, or run before the tables existed. Re-run grants as `postgres`. |
| `password authentication failed` for `DB_USER` | Wrong password, or the user was created in a different database context. Recreate/reset the user in Console > SQL > Users. |
| Proxy: `permission denied` / IAM error | The `gcloud auth login` account lacks Cloud SQL Client on `PROJECT_ID`. Grant the role, re-auth. |
| Cloud Run: `connection refused` on the socket path | Cloud SQL connection not added to the service, or `DATABASE_URL` host is not exactly `/cloudsql/PROJECT_ID:REGION:INSTANCE_NAME`. Check both, redeploy. |
| Seed appears twice / demo data duplicated | Should not happen: seed only fires on an empty store. If you see duplicates, the store was wiped between boots (see step 6) or two different databases are in play — check which `DATABASE_URL` each boot used. |
| App slow / connections exhausted on `db-f1-micro` | Shared-core throttling or too many API instances. Reduce Cloud Run instances to 1, or step up to `db-g1-small`. |
