# Scene backend on Cloud Run + Cloud SQL for PostgreSQL

Worker 3 (API hosting). Placeholders only: nothing in this doc is a real
project ID, password, token, or key. Replace every `<...>` before running.

## Who provisions what

- Provisioning is Nayan's console/`gcloud` job, not an agent job. The
  provisioned Google account from the hackathon is AI Studio API only,
  so all GCP work below uses Nayan's own GCP account with billing
  enabled. Agents never see or store GCP credentials.
- What already exists: the backend in `~/workspace/scene-backend/`
  (`server.py`, `app/`, `schema.sql`, `requirements.txt`). It is
  stdlib plus optional real services, runs `ThreadingHTTPServer` on
  `0.0.0.0:$PORT` (default 8000), and picks the store from
  `SCENE_STORE`. `SCENE_STORE=postgres` needs `DATABASE_URL` and
  fail-fasts with exit 2 without it, before even importing psycopg.
- This doc does not edit the backend. The `Dockerfile` lives next to
  this doc in `scene-cloudsql-deploy/`; the backend directory itself
  is untouched.

## 0. Prereqs (Nayan, one time)

```sh
gcloud auth login
gcloud config set project <PROJECT_ID>
gcloud services enable run.googleapis.com sqladmin.googleapis.com \
  secretmanager.googleapis.com
```

## 1. Cloud SQL instance (Nayan, console or gcloud)

Create one PostgreSQL instance in the same region as the Cloud Run
service, plus a database and a user. Example shape only:

```sh
gcloud sql instances create <INSTANCE_NAME> \
  --database-version=POSTGRES_16 \
  --region=<REGION> \
  --tier=db-f1-micro \
  --root-password='<DB_ROOT_PASSWORD>'

gcloud sql databases create <DB_NAME> --instance=<INSTANCE_NAME>
gcloud sql users create <DB_USER> \
  --instance=<INSTANCE_NAME> \
  --password='<DB_USER_PASSWORD>'
```

The tier above is a starting point for a demo, not a production
sizing. No schema migration step is needed: `PostgresStore` creates
its tables (`CREATE TABLE IF NOT EXISTS`, DDL identical to
`schema.sql`) on first connect, and `server.py` seeds only when the
store is empty, so redeploys never duplicate seed data.

## 2. Secrets in Secret Manager (never env-var plaintext)

`DATABASE_URL` carries the database password, so it is a secret too,
not a `--set-env-vars` value. Create three secrets:

```sh
printf '%s' '<SCENE_API_TOKEN>' | gcloud secrets create scene-api-token \
  --data-file=-
printf '%s' '<GEMINI_API_KEY>' | gcloud secrets create scene-gemini-key \
  --data-file=-
printf '%s' '<DATABASE_URL>' | gcloud secrets create scene-database-url \
  --data-file=-
```

`DATABASE_URL` for the Cloud Run native Unix socket (see step 3) is:

```
postgresql://<DB_USER>:<DB_PASSWORD>@/<DB_NAME>?host=/cloudsql/<PROJECT_ID>:<REGION>:<INSTANCE_NAME>
```

Notes: the password must be URL-encoded if it contains special
characters (`@`, `/`, `?`, `#`, etc.); psycopg receives this string
verbatim and never logs it. The `/cloudsql/...` path only exists
inside a Cloud Run revision that has `--add-cloudsql-instances` set,
so this exact URL does not work from a laptop; local testing keeps
using SQLite or a TCP `DATABASE_URL`.

## 3. Build and deploy

### Image layout

`Dockerfile` (next to this doc) assumes the build context is the
backend directory, so `COPY server.py`, `COPY app/`, `COPY schema.sql`
and `COPY requirements.txt` resolve. Base is `python:3.12-slim`,
single stage. It installs `requirements.txt` plus `psycopg[binary]`
(psycopg v3, the one dependency `PostgresStore` needs; it is not in
`requirements.txt`, and the binary wheel avoids needing system
libpq). It also installs `ffmpeg` for real keyframe extraction.
No secrets are baked into the image; everything sensitive arrives
via env/Secret Manager at runtime.

If `faster-whisper` and/or `google-genai` are skipped at build time
(e.g. to shrink the image or speed the build), the server still
starts and serves: the transcriber falls back to the mock transcript
shape without faster-whisper, and the Argon services fall back to
mock drafts/reasoning without `GEMINI_API_KEY`, each with a clear log
line. Skipping them costs real transcription and real Argon analysis,
not uptime. Note the reverse trade-off of including faster-whisper:
the model downloads on first transcribe (`WHISPER_MODEL`, default
`base`, CPU/`int8` by default), and Cloud Run's filesystem is
ephemeral, so each new instance re-downloads it on its first real
transcription; allow for that cold-start cost in the demo.

### Option A: `gcloud run deploy --source` (simplest)

`--source` expects the `Dockerfile` at the source root, and this
repo's `Dockerfile` does not live in the backend directory. So copy
it into a deploy copy of the backend (never into
`~/workspace/scene-backend/` itself, which stays untouched), with a
`.dockerignore` so the local SQLite file and caches are not uploaded:

```sh
cp -r ~/workspace/scene-backend/ /tmp/scene-deploy-src/
cp ~/workspace/scene-cloudsql-deploy/Dockerfile /tmp/scene-deploy-src/Dockerfile
printf '%s\n' 'scene.db*' '__pycache__/' '.venv/' '*.pyc' \
  > /tmp/scene-deploy-src/.dockerignore
```

Then deploy from that directory (full command in "Deploy command"
below, with `--source /tmp/scene-deploy-src/`).

### Option B: `docker build -f` from elsewhere, then `--image`

When the `Dockerfile` stays in `scene-cloudsql-deploy/` and the
context is the backend directory:

```sh
docker build -f ~/workspace/scene-cloudsql-deploy/Dockerfile \
  -t <REGION>-docker.pkg.dev/<PROJECT_ID>/<REPO>/scene-backend:latest \
  ~/workspace/scene-backend/
docker push <REGION>-docker.pkg.dev/<PROJECT_ID>/<REPO>/scene-backend:latest
```

Then deploy with `--image <REGION>-docker.pkg.dev/<PROJECT_ID>/<REPO>/scene-backend:latest`
in place of `--source` below. (Artifact Registry repo creation is
Nayan's one-time console/`gcloud` job.)

### Deploy command

```sh
gcloud run deploy <SERVICE_NAME> \
  --project=<PROJECT_ID> \
  --region=<REGION> \
  --source /tmp/scene-deploy-src/ \
  --add-cloudsql-instances=<PROJECT_ID>:<REGION>:<INSTANCE_NAME> \
  --set-env-vars=SCENE_STORE=postgres,AUTH_ENABLED=1 \
  --set-secrets=DATABASE_URL=scene-database-url:latest,SCENE_API_TOKEN=scene-api-token:latest,GEMINI_API_KEY=scene-gemini-key:latest \
  --allow-unauthenticated \
  --timeout=3600 \
  --memory=2Gi --cpu=2
```

What each flag does:

- `--add-cloudsql-instances` mounts the native Cloud SQL Unix socket
  at `/cloudsql/<PROJECT_ID>:<REGION>:<INSTANCE_NAME>`, which is what
  the `DATABASE_URL` in step 2 points at. The Cloud Run runtime
  service account needs the Cloud SQL Client role
  (`roles/cloudsql.client`); grant it in IAM if deploys fail on the
  socket.
- `--set-env-vars SCENE_STORE=postgres` selects `PostgresStore`;
  `AUTH_ENABLED=1` turns on app-level Bearer auth (see below).
- `--set-secrets` mounts the three Secret Manager secrets as env vars
  (`SECRET_NAME=secret-name:latest` form). Rotate by creating a new
  secret version and redeploying; no image rebuild is needed for a
  secret rotation.
- `--timeout=3600` raises the request timeout to its 60-minute max;
  see the WebSocket caveat below for why this matters.
- `--memory=2Gi --cpu=2` is a starting point for CPU Whisper
  transcription; tune if transcription is slow, and consider
  `--min-instances=1` on demo day to dodge cold starts (it costs
  while idle, so turn it off after).

On success `gcloud` prints the service URL, shaped like
`https://<SERVICE_NAME>-<HASH>-<REGION>.a.run.app`. That URL is the
public API base the clients point at. Redeploys reuse the same URL
and the same Cloud SQL data; only the code revision changes.

## 4. Public vs IAM: use `--allow-unauthenticated` + app Bearer auth

Recommendation, stated plainly: deploy with
`--allow-unauthenticated` and protect the API with the app's own
Bearer auth (`AUTH_ENABLED=1`, token `SCENE_API_TOKEN`), not with
Cloud Run IAM invoker. The reason is the clients: the iOS phone app
and the Lens web app have no GCP credentials and no Google identity
token flow, so an IAM-invoker-only service would reject every call
they make, and adding Google auth to both clients during the
hackathon is out of scope. With `--allow-unauthenticated`, anyone
can reach the URL, but every API route still requires
`Authorization: Bearer <SCENE_API_TOKEN>` and returns 401 without
it, which is the same auth model the LAN deployment already uses.
IAM invoker (`--no-allow-unauthenticated` plus `roles/run.invoker`
grants) is the right choice only if the clients later gain a way to
present a Google identity token; until then it breaks the demo.

## 5. Verify

```sh
SERVICE_URL='https://<SERVICE_NAME>-<HASH>-<REGION>.a.run.app'

# No token -> 401 (auth is on)
curl -s -o /dev/null -w '%{http_code}\n' "$SERVICE_URL/api/v1/status"

# With token -> 200
curl -s -H "Authorization: Bearer <SCENE_API_TOKEN>" \
  "$SERVICE_URL/api/v1/status"
```

Also confirm the socket path works end to end: a successful status
call after a fresh deploy proves `PostgresStore` connected, because
a bad `DATABASE_URL` fail-fasts the container (exit 2) or fails the
revision health check instead of silently serving mock data.

## 6. Point the clients at the public URL

### iOS phone app

Set the app's API base to the bare service URL
(`https://<SERVICE_NAME>-<HASH>-<REGION>.a.run.app`, no path). Its
`apiBase` normalizer strips surrounding whitespace and trailing
slashes and ensures exactly one trailing `/api/v1`, so pasting the
URL with or without `/api/v1` lands on the same endpoint, but paste
the bare URL to keep it obvious. Then turn the app's mock-mode
toggle OFF: with mock mode on, the app talks to its local mock
instead of this server no matter what the base URL says. The app
sends the token as `Authorization: Bearer <SCENE_API_TOKEN>`; that
token value lives in the phone's settings/keychain entry, never in
this doc.

iOS App Transport Security: a public HTTPS Cloud Run URL needs no
ATS exception. The local-networking ATS exception added for the LAN
deployment was only for the plain-HTTP LAN URL; leave it scoped to
local networking and do not add `NSAllowsArbitraryLoads` for the
Cloud Run URL.

### Scene Lens web app

Open the Lens page with the service URL and token as query params:

```
https://<LENS_HOST>/?api=<SERVICE_URL>&token=<SCENE_API_TOKEN>
```

`?api=` is the API base URL (same bare service URL as iOS) and
`?token=` is the same `SCENE_API_TOKEN` Bearer token. Do not share
a Lens link with a real token in it beyond the demo team, since the
token is visible in the URL.

### Rollback to LAN

If Cloud Run misbehaves during the demo, point both clients back at
the Mac's LAN URL and flip nothing else: the API contract is the
same, and the LAN server keeps serving SQLite. Cloud SQL data and
LAN SQLite data are separate stores and do not sync.

## 7. WebSocket / request-timeout caveat

Cloud Run supports WebSockets, but a WebSocket connection is still
bounded by the revision's request timeout (default 5 minutes, max
60 minutes with `--timeout=3600` as set above), so the `/live`
socket at `/api/v1/live` will be cut if a single session outlives
that timeout; demo sessions are short, so this is fine for the
hackathon, but a multi-hour always-on session would need client
reconnect logic or a different host.

## 8. What this doc deliberately does not cover

Cloud SQL backups, private IP/VPC, custom domains, and CI/CD
deploys are out of scope for the hackathon deploy. The data-layer
worker owns schema/connection details beyond the `DATABASE_URL`
shape above, and the frontend worker owns the exact iOS/Lens
settings UI; this doc only states the contract between them (public
URL + Bearer token + `SCENE_STORE=postgres`).
