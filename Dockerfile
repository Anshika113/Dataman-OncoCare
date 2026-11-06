# syntax=docker/dockerfile:1
# =============================================================================
# DataMan OncoCare — single production image
# Builds the React frontend, then packages the FastAPI backend that serves both
# the API and the built SPA from one process (required by the in-memory store).
#
# Run without any .env file:
#   docker compose up --build
#   -> opens http://localhost:8000
# =============================================================================

# ---- Stage 1: build the frontend --------------------------------------------
FROM node:22-alpine AS frontend-build
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
# VITE_DEMO gates the demo Ops Console + clock-advance controls. Keep false for
# production; build with --build-arg VITE_DEMO=true to expose them.
ARG VITE_DEMO=false
ENV VITE_DEMO=$VITE_DEMO
RUN npm run build

# ---- Stage 2: runtime (FastAPI) ---------------------------------------------
FROM python:3.11-slim AS runtime
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app/backend \
    CARE_DATA_PATH=/data/care.xlsx \
    CARE_AUTO_SALT_PATH=/data/.secret-salt

# Dependencies first (better layer caching)
COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend/ ./backend/
COPY --from=frontend-build /app/frontend/dist ./frontend/dist

# Non-root user; the datastore + auto-secret live in a writable /data volume.
RUN useradd -m oncocare && mkdir -p /data && chown -R oncocare /data /app
USER oncocare

EXPOSE 8000
VOLUME ["/data"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health',timeout=3).status==200 else 1)"

# Single process (the Excel store is shared in-memory; never run multiple).
# Seeds the datastore on first boot if the volume is empty.
CMD ["sh", "-c", "python -m backend.storage.seed >/dev/null 2>&1 || true; uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
