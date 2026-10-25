# Scene Cloud SQL deploy: security checklist

Tick every box before the deploy goes live, and again before the demo.
If any box cannot be ticked, do not go live with that piece. Fix it or
leave that feature out of the demo and say so out loud.

Scope reminder: the repo is public (NayanVangala/argon4hack). Anything
committed there is public forever. The provisioned Google account is
AI Studio API only, so GCP work uses Nayan's own GCP account with billing.
This checklist uses placeholders only. No real key, token, password, or
credential belongs in this file, in chat, in docs, or in the repo.

How auth works in this codebase (verified against the workspace copy):
- `app/routes.py` `check_auth`: `AUTH_ENABLED` off (unset, or anything
  other than `1`/`true`/`yes`/`on`) means no auth. `AUTH_ENABLED` on
  requires an `Authorization: Bearer <token>` header exactly matching
  `SCENE_API_TOKEN`.
- Fail closed: if `AUTH_ENABLED` is on but `SCENE_API_TOKEN` is unset or
  empty, every request is refused (401) and a warning is printed.
- Known WS gap, see section 1. REST is gated. The WebSocket upgrade is not.

---

## 1. Auth on and fail closed in production

- [ ] Cloud Run sets `AUTH_ENABLED=1` (not `true` in one place and `1` in
      another; pick `1` and use it everywhere so there is one value to audit).
- [ ] `SCENE_API_TOKEN` is set in production ONLY via Secret Manager
      (Cloud Run `--set-secrets`, never `--set-env-vars`, never in the
      image, never in an env file). See section 2.
- [ ] The Cloud Run service account is the only identity with
      `secretmanager.versions.access` on the `SCENE_API_TOKEN` secret.
      No `allUsers`, no broad developer access.
- [ ] Fail-closed test 1, no token configured: with `AUTH_ENABLED=1` and
      no `SCENE_API_TOKEN`, every REST request returns 401. If anything
      returns 200, stop. The deploy is not fail closed.
- [ ] Fail-closed test 2, token configured: a REST request with no
      `Authorization` header returns 401.
- [ ] Fail-closed test 3: a REST request with a wrong Bearer token
      returns 401.
- [ ] Positive test: a REST request with the correct
      `Authorization: Bearer <token-from-Secret-Manager>` returns 200.
      Run this from a machine that is not the deploy machine, so the test
      proves the deployed service, not localhost.
- [ ] Do NOT confuse Cloud Run IAM invoker auth with app auth. The demo
      phone app cannot do GCP IAM auth, so Cloud Run ingress will be
      unauthenticated and the app Bearer token is the load-bearing gate.
      That is exactly why `AUTH_ENABLED=1` is non-negotiable in production.
- [ ] Local dev stays separate: `AUTH_ENABLED` stays off or uses a
      different, throwaway local token on the Mac. The production token
      is never copied to the Mac, to SQLite, or to a LAN test.

### Known WS token gap: state this honestly, do not paper over it

- [ ] Understood and accepted by the team: `?token=` on the WebSocket
      upgrade (`/api/v1/live`) is IGNORED. Only REST requests go through
      the `check_auth` gate. There is currently no authenticated
      WebSocket handshake in this code.
- [ ] Demo implication, stated plainly: anyone who learns the deployed
      Cloud Run URL can open the WebSocket and receive live status/scene
      events. Do NOT claim in the pitch, the README, or the demo that
      the live stream is authenticated. Do NOT demo a sensitive session
      over the WebSocket.
- [ ] Mitigation for today (no code change): keep the deployed URL
      unlisted, share it only with the demo devices, and do not put it
      in the public repo, slides, or a public post. The URL itself is
      not a secret and must not be treated as one, but there is no reason
      to broadcast it.
- [ ] If time allows before the demo, the real fix is a code change:
      gate the WebSocket handshake on the same Bearer token (or a
      short-lived token issued over an authenticated REST call) and
      re-run the fail-closed tests against `/api/v1/live`. Until that
      lands and is tested, the gap above stays in effect.
- [ ] Do NOT "fix" this by pasting the token into the WebSocket URL
      (`?token=<real-token>`). It is ignored by the server, and it would
      leak the token into logs, browser history, and any proxy in the path.

---

## 2. Secrets in Secret Manager only

Secrets in scope: `GEMINI_API_KEY`, `SCENE_API_TOKEN`, and the Cloud SQL
app-user password (if one is used at all; see section 4).

- [ ] `GEMINI_API_KEY` lives in backend env only, via Secret Manager.
      Never in the phone app, never in the Lens code, never in the
      public repo, never in chat, never in a doc, never in a screenshot.
- [ ] `SCENE_API_TOKEN` lives in Secret Manager only. Same bans as above.
- [ ] No secret is baked into the container image. Check the Dockerfile
      and build context for `ENV GEMINI_API_KEY`, `ENV SCENE_API_TOKEN`,
      `COPY .env`, or any copied credential file before building.
- [ ] No secret is passed with `--set-env-vars` on Cloud Run. Secrets go
      with `--set-secrets` only, so they do not show up in plain-text
      service configuration.
- [ ] No `.env`, `backend.env`, or other env file is committed anywhere,
      and no env file is copied into the image build context. Env files
      stay local, untracked, and out of the repo (see section 3).
- [ ] No secret is pasted in chat, email, a shared doc, a slide, or a
      Devpost description, even redacted-looking fragments. If a secret
      is ever pasted anywhere shared, treat it as leaked and rotate it
      (section 7) instead of deleting the message and hoping.
- [ ] Secret Manager secret names are not secrets, but secret VALUES
      never appear in Cloud Run logs, deploy logs, or error output.
      Check one deploy log by eye before the demo.
- [ ] The phone app and Lens code contain no API key and no token
      literal. Grep them too, not just the backend (section 6).

---

## 3. .gitignore coverage

Current gap: the repo root `.gitignore` covers ONLY `xcuserdata/`,
`.DS_Store`, `DerivedData/`, `*.xcuserstate`, and `build.log`. It does
NOT cover `.env`, `backend.env`, `scene.db`, or Python artifacts. The
workspace copy at `~/workspace/scene-backend/` already contains a real
`scene.db` plus `__pycache__/` files, which is proof these files exist
and will get committed by accident if the ignore rules are missing.

Add the exact lines below. Keep the existing Xcode lines. Do not remove
them.

### Repo root `.gitignore` (argon4hack): append these lines

```gitignore
# Secrets and local env (never commit)
.env
.env.*
backend.env
*.env
!.env.example

# Local databases (SQLite dev data, never commit)
scene.db
scene.db-shm
scene.db-wal
*.db
*.sqlite
*.sqlite3

# Python artifacts
__pycache__/
*.py[cod]
*.pyc
*.pyo
.venv/
venv/

# Cloud SQL / GCP credentials (never commit)
*.json
!package.json
service-account*.json
*-key.json
credentials*.json
cloudsql-credentials*.json
```

Notes on the lines above:
- [ ] `*.json` with `!package.json` is deliberate: it blocks service
      account JSON by default while keeping a real `package.json` (if
      the repo has one) committable. If any other JSON file legitimately
      belongs in the repo, allowlist it explicitly with `!name.json`
      instead of loosening the rule.
- [ ] If the team prefers a narrower rule over blanket `*.json`, the
      minimum non-negotiable lines are `service-account*.json`,
      `*-key.json`, and `credentials*.json`. Blanket is safer for a
      public repo on demo day.

### Backend directory `.gitignore` (in the repo, e.g. `src/backend/.gitignore`)

Apply the same lines in the backend directory itself, so the backend
is protected even if it is ever moved or copied on its own:

```gitignore
# Secrets and local env (never commit)
.env
.env.*
backend.env
*.env
!.env.example

# Local databases (SQLite dev data, never commit)
scene.db
scene.db-shm
scene.db-wal
*.db
*.sqlite
*.sqlite3

# Python artifacts
__pycache__/
*.py[cod]
*.pyc
*.pyo
.venv/
venv/

# Cloud SQL / GCP credentials (never commit)
service-account*.json
*-key.json
credentials*.json
cloudsql-credentials*.json
```

- [ ] Root `.gitignore` updated AND backend `.gitignore` created/updated.
- [ ] `.env.example` (if one is added) contains placeholder names only,
      e.g. `GEMINI_API_KEY=YOUR_KEY_HERE`, never a real value.
- [ ] Verified with `git status` after the change: `scene.db`,
      `__pycache__/`, `*.pyc`, `.env`, and `backend.env` do not appear
      as untracked or staged files. Note: `.gitignore` does not un-track
      a file that is already tracked. If any of these files is already
      tracked, remove it from tracking (`git rm --cached <file>`) and
      rotate any secret it contained; ignoring it after the fact does
      not un-publish it.
- [ ] This checklist file itself contains no real secret, and the
      workspace scratch copy (`~/workspace/scene-backend/`) is never
      committed or pushed directly. It is a scratch copy, not the repo.

---

## 4. Network: no public database if it can be avoided

Preferred order. Use the first option that works; do not skip to a
public IP for convenience.

- [ ] Preferred: Cloud Run connects via the Cloud SQL Auth Proxy /
      Cloud Run native Unix socket (`/cloudsql/<INSTANCE_CONNECTION_NAME>`).
      The database has NO public IP. The app never sees a database
      password in a URL, and no database port is reachable from the
      internet.
- [ ] Acceptable alternative: private IP (VPC) with the Cloud Run
      service attached to the same VPC. Still no public IP.
- [ ] Public IP is a last resort, not the default. If it is ever enabled:
  - [ ] `sslmode=require` (or stronger) on every connection. No
        unencrypted connection, ever.
  - [ ] Authorized networks contain ONLY the IPs that need it
        (deploy/demo machines), never `0.0.0.0/0`.
  - [ ] Authorized networks are removed again immediately after the
        demo or debugging session that needed them.
  - [ ] The database password is supplied via Secret Manager, never
        embedded in a committed `DATABASE_URL`.
- [ ] The Cloud Run service URL is the only public surface. The database
      is not reachable by scanning that URL, and no database host, port,
      or password appears in the app, the repo, or the demo materials.
- [ ] Cloud SQL instance is in the GCP project with billing under
      Nayan's own account (not the AI Studio-only provisioned account),
      so the instance, its IAM, and its billing are all visible to the
      person who can shut it down (section 7).

---

## 5. Least-privilege DB user

The 9 tables in `schema.sql` are: `sessions`, `chunks`, `scenes`,
`facts`, `people`, `pins`, `followup_runs`, `followups`, `meta`.
The app user gets access to exactly these, and nothing else.

- [ ] A dedicated app user exists (e.g. `scene_app`), separate from the
      Cloud SQL superuser/`postgres` user and separate from any
      migration/owner user. The app never connects as a superuser.
- [ ] Grants on ONLY the 9 tables above: at most `SELECT, INSERT,
      UPDATE, DELETE` as the app actually needs. No grant on any other
      table, schema, or database object.
- [ ] No DDL for the app user: no `CREATE`, `ALTER`, `DROP`, or
      `TRUNCATE` beyond what the app code actually requires. If schema
      setup is done by a separate migration/owner step, the app user
      gets no DDL at all.
- [ ] No superuser, no `CREATEDB`, no `CREATEROLE`, no login as
      `postgres` from the app. Verify with the database's role listing,
      not just by trusting the creation command.
- [ ] If the app creates tables at startup (`CREATE TABLE IF NOT EXISTS`
      in `schema.sql`), decide explicitly who runs that step: either the
      migration/owner user runs it once before deploy, or the app user
      gets a one-time, documented exception. Do not silently grant DDL
      forever because startup table creation was convenient.
- [ ] `PUBLIC` schema default access is revoked where it would otherwise
      let the app user reach objects outside the 9 tables.
- [ ] The app-user password (if password auth is used) is stored in
      Secret Manager only, is long and random, and is never in the repo,
      in chat, or in a `DATABASE_URL` string that gets logged.
- [ ] Prefer IAM database auth or the Auth Proxy's automatic auth where
      available, so there is one fewer long-lived password to rotate.

---

## 6. Pre-push safety: grep before ANY commit

Run these from the repo root, on the exact files about to be committed,
before every commit and every push. A clean grep is a precondition, not
a nice-to-have. This applies to backend, phone app, and Lens code alike.

- [ ] `git status` reviewed by eye: no `.env`, `backend.env`,
      `scene.db`, `__pycache__/`, `*.pyc`, or credential JSON in the
      staged or untracked list.
- [ ] `git diff --cached` reviewed by eye: no secret value, no token,
      no password, no private key block in the diff itself.
- [ ] Grep for API keys and tokens (case-insensitive, whole repo,
      excluding `.git/`):

```bash
grep -RniE "GEMINI_API_KEY\s*=\s*[^Y\"' ]|AIza[0-9A-Za-z_-]{20,}|SCENE_API_TOKEN\s*=\s*[^Y\"' ]|Bearer [A-Za-z0-9._-]{10,}" --exclude-dir=.git --exclude-dir=__pycache__ . || true
```

Any hit that is not an obvious placeholder (`YOUR_KEY_HERE`,
`PLACEHOLDER`, an empty value, or a variable name with no value) blocks
the commit. Fix it, then re-grep.

- [ ] Grep for database URLs with embedded passwords:

```bash
grep -RniE "DATABASE_URL\s*=.*://[^:]+:[^@]+@|postgres(ql)?://[^:]+:[^@]+@" --exclude-dir=.git . || true
```

A `DATABASE_URL` with a password in it blocks the commit, even if the
password looks like a local/dev one. Move it to Secret Manager.

- [ ] Grep for service account JSON and private keys:

```bash
grep -RniE "private_key|BEGIN (RSA |EC )?PRIVATE KEY|\"type\":\s*\"service_account\"" --exclude-dir=.git . || true
find . -path ./.git -prune -o -name "*service-account*.json" -print -o -name "*-key.json" -print -o -name "credentials*.json" -print
```

Any hit blocks the commit. Service account JSON is never committed,
even to a private branch of a public repo, even temporarily.

- [ ] Grep for the deployed Cloud Run URL and the database host in
      files that will be public: neither belongs in the repo unless the
      team has deliberately decided the Cloud Run URL is public.
- [ ] If ANY grep above hits a real secret: stop, rotate that secret
      immediately (section 7), and do not rely on deleting the commit.
      A pushed secret is a leaked secret even if the commit is later
      removed, because a public repo can be cloned in between.
- [ ] The pre-push check is run by the person pushing, not assumed from
      someone else's run. If Isabella pushed backend-adjacent changes in
      parallel (as happened during the hackathon rebase), re-run the
      greps on the merged result before pushing.

---

## 7. Post-demo hygiene: rotate, stop, verify

Do this the same day as the demo. "Later" is how demo credentials stay
live for months.

- [ ] Rotate `SCENE_API_TOKEN`: create a new Secret Manager version,
      point Cloud Run at it, verify the new token works and the old
      token returns 401, then disable/destroy the old secret version.
      Do not just change the value in one place and leave the old value
      valid somewhere else.
- [ ] Rotate `GEMINI_API_KEY` if it was ever in a shared place, a
      screenshot, a log, or a chat message during the demo. If it stayed
      in Secret Manager the whole time, rotation is still cheap insurance
      and is recommended.
- [ ] Rotate the Cloud SQL app-user password if password auth was used,
      and update only the Secret Manager copy.
- [ ] Delete or stop the Cloud SQL instance. Preferred: delete it if the
      demo data does not need to survive. Minimum: stop it so billing
      and the attack surface both go to zero. Verify the instance state
      in the GCP console, not just by assuming the stop command worked.
- [ ] Remove any public-IP authorized networks added during the demo
      or debugging, even if the instance is being kept. Verify the
      authorized-networks list is empty (or back to its pre-demo state).
- [ ] Disable or destroy demo-only Secret Manager versions that are no
      longer needed. Keep the secret itself only if the project continues
      past the demo; otherwise delete it.
- [ ] Remove any Cloud Run revisions or services created only for the
      demo, and confirm the deployed URL no longer serves the backend
      (or now serves the intended post-demo state).
- [ ] Check billing: confirm the GCP project shows no running Cloud SQL
      instance and no unexpected charges after shutdown.
- [ ] Final sweep: re-run the section 6 greps on the repo HEAD after
      the demo. Confirm no secret, token, password, or service account
      JSON landed in the repo during the rush. If one did, rotate it
      first, then clean the repo; rotation first, cleanup second.

---

## Quick pass/fail gate (read this before going live)

Live deploy is a GO only if all of these are true:

1. `AUTH_ENABLED=1` in production, token via Secret Manager, and the
   three fail-closed tests in section 1 pass.
2. No secret is in the image, in an env file, in the repo, or in chat.
3. `.gitignore` covers `.env`, `backend.env`, `scene.db`,
   `__pycache__/`, `*.pyc`, and credential JSON at both the repo root
   and the backend directory.
4. The database has no public IP, or, if it does, `sslmode=require`
   plus authorized networks only.
5. The app user touches only the 9 schema tables, with no superuser
   and no standing DDL.
6. Section 6 greps are clean on the exact commit being pushed.
7. The WS gap is disclosed to the team and the demo does not claim the
   live stream is authenticated.

Anything else is a NO-GO for that piece until it is fixed.
