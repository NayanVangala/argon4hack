# Scene backend image for Google Cloud Run (worker 3, API hosting).
#
# BUILD CONTEXT MUST BE THE BACKEND DIRECTORY, i.e. the directory that
# contains server.py, app/, schema.sql and requirements.txt
# (~/workspace/scene-backend/ in this workspace, or src/backend/ in the
# repo once the reorg lands). Every COPY below resolves against that
# context, not against this file's location. See cloudrun-deploy.md
# for the `docker build -f` form (Dockerfile elsewhere, context =
# backend dir) and the `gcloud run deploy --source` form (Dockerfile
# must sit at the source root).
#
# No secrets are baked into this image. All credentials arrive as
# environment variables / Secret Manager mounts at runtime:
# DATABASE_URL, SCENE_API_TOKEN, GEMINI_API_KEY. Nothing in this file
# contains a key, token, project ID, or password.

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# ffmpeg/ffprobe: used by app/ingest.py for keyframe extraction from
# video chunks. Optional in the strict sense (missing ffmpeg degrades
# to the mock keyframe path, never raises), but cheap to include and
# required for real frames, so it stays in the image.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Requirements first, so dependency layers cache across code changes.
COPY requirements.txt ./
# psycopg is in requirements.txt (psycopg[binary]>=3.1) and is also
# installed explicitly below. PostgresStore imports psycopg v3.
# psycopg[binary] ships its own libpq, so no system libpq-dev is
# needed on slim.
RUN pip install --no-cache-dir -r requirements.txt "psycopg[binary]"

COPY server.py schema.sql ./
COPY app/ ./app/

# Documentary only: Cloud Run sets $PORT itself (default 8080) and
# server.py already binds 0.0.0.0:$PORT (default 8000 locally).
# This EXPOSE does not control the Cloud Run port.
EXPOSE 8000

CMD ["python3", "server.py"]
