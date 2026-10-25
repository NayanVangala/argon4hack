FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt && useradd --uid 10001 --create-home scene && mkdir -p /data && chown scene:scene /data
COPY --chown=scene:scene . .
USER scene
ENV SCENE_DB_PATH=/data/scene.sqlite3
EXPOSE 8000
CMD ["sh", "-c", "exec uvicorn app:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1 --no-access-log"]
