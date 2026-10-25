# Scene Cloud SQL Deploy: convergence index

Workflow: scene-cloudsql-deploy. 6 workers, all done. No GCP resources
provisioned, no keys or credentials in any file, no backend files edited.

## Recommended path (converged)

1. **Database:** Cloud SQL for PostgreSQL 16, region us-west2 (Los
   Angeles, closest to Fremont/SF), tier db-f1-micro, 10 GB SSD.
2. **Connection:** Cloud Run native Unix socket, primary path:
   `DATABASE_URL=postgresql://DB_USER:DB_PASSWORD@/DB_NAME?host=/cloudsql/PROJECT_ID:REGION:INSTANCE_NAME`,
   stored in Secret Manager, never as plaintext env.
3. **API host:** Cloud Run, publicly reachable (`--allow-unauthenticated`)
   with app-level Bearer auth (`AUTH_ENABLED=1`, `SCENE_API_TOKEN` via
   Secret Manager), because the iOS app and Lens have no GCP credentials
   and IAM invoker would reject every client call.
4. **Secrets:** `GEMINI_API_KEY`, `SCENE_API_TOKEN`, and the DATABASE_URL
   all in Secret Manager. Nothing in the image, repo, or chat.
5. **Clients:** iOS apiBase = bare service URL, mock mode OFF. Lens =
   `?api=<SERVICE_URL>&token=<SCENE_API_TOKEN>`. Public HTTPS needs no
   ATS exception.
6. **Fallback:** if not working end to end by 6:30pm (one hour before the
   7:30pm feature freeze), abandon cloud and go LAN + SQLite. See
   fallback-plan.md. Nayan makes the call.

## The one blocker

`psycopg` is missing from `requirements.txt`. Add `psycopg[binary]>=3.1`
(then pin to the Mac-installed version). It must be v3 `[binary]`
(`psycopg.types.json` is v3-only; `psycopg2` will NOT work). The
Dockerfile already installs it, but the repo requirements file needs
the line too for local/Mac parity.

## Other findings worth knowing

- DATABASE_URL passes verbatim to `psycopg.connect()`: both
  `postgresql://` and `postgres://` work, socket `?host=/cloudsql/...`
  and `?sslmode=require` both survive. Password must be URL-encoded.
- One shared connection + RLock, no pooling, no reconnect/retry. Fine
  for demo traffic; do NOT retrofit a pool during the hackathon.
- Deploy with `--max-instances=1`: kills the double-seed race (two
  instances booting at once can both seed, duplicating demo data).
- Seed is not atomic and has no opt-out flag; on a fresh instance the
  server seeds 1 session, 8 scenes, 3 facts, 2 people, spend 1.84.
- WS token gap is real and confirmed twice: `?token=` on the
  `/api/v1/live` upgrade is ignored; only REST is gated. Do not claim
  the live stream is authenticated.
- Cloud Run request timeout bounds WS connections (max 60 min via
  `--timeout=3600`); fine for short demo sessions.
- Skipping faster-whisper/google-genai still boots with mock
  degradation; including faster-whisper re-downloads the model per new
  Cloud Run instance (ephemeral filesystem).
- Cost: demo weekend about $0.61 on db-f1-micro (48h, budget $1);
  monthly run-rate about $9.37 if left running. Delete (not just stop)
  after the demo: a stopped instance with a public IP kept costs about
  $9/mo.

## Cross-worker assumption conflicts (resolved here)

- **Region:** runbook says us-west2; cost figures used a us-central1
  baseline. Use us-west2; prices are similar, re-check at deploy time.
- **Backups:** runbook says daily backups ON; cost assumed backups OFF.
  Backups add roughly $0.80/mo for 10 GB, about $0.05 over the weekend.
  Keep them ON unless every cent matters; the $0.61 weekend figure
  becomes roughly $0.66.

## Files

- postgres-readiness.md: verdict NOT READY as-is, one line away, with
  the full numbered change list and snippets.
- cloudsql-runbook.md: console steps (instance, user, grants, socket vs
  proxy vs public IP, schema load, seed, verification, teardown).
- Dockerfile: python:3.12-slim, psycopg[binary], ffmpeg, no secrets.
  Build context is the backend directory.
- cloudrun-deploy.md: gcloud commands, env/secrets, client wiring,
  build-context handling, verify step (unauthenticated status = 401).
- security-checklist.md: tickable checklist (fail-closed auth tests,
  Secret Manager only, gitignore lines, socket over public IP,
  least-privilege user, pre-push greps, post-demo rotation).
- cost-estimate.md: weekend + monthly figures with assumptions.
- fallback-plan.md: LAN + SQLite steps, restart gotchas, IP-change
  handling, cloudflared second fallback, 6:30pm cutoff.
