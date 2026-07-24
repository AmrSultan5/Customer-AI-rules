# Rule Agent — Backend
# Build: docker build -t rule-agent-backend .
# Run:   docker run -p 8000:8000 --env-file backend/.env rule-agent-backend

# Pin base image for reproducible builds. Update deliberately.
FROM python:3.11.9-slim

WORKDIR /app

# System deps: git is required at runtime by the "add a Git repo" RAG ingestion
# feature, which shells out to `git clone` (see backend/ingestion.py::_clone_git_repo).
# python:3.11-slim has no git by default.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies first (layer cache)
COPY backend/requirements.txt ./requirements.txt
COPY backend/requirements-lock.txt ./requirements-lock.txt
RUN pip install --no-cache-dir -r requirements-lock.txt

# Copy the full backend package tree (main.py imports kb/, providers/, and
# migrations/ as packages, plus kb/*.yaml descriptors and kb/sample_docs/).
# backend/data, caches, tests, and .env are excluded via .dockerignore —
# data is mounted read-only via volume in production.
COPY backend/ ./

# Data files are expected at /app/data at runtime.
# Mount your data volume: -v ./backend/data:/app/data:ro
RUN mkdir -p /app/data

# Non-root user for least privilege
RUN useradd -m -u 1001 appuser && chown -R appuser /app
USER appuser

EXPOSE 8000

# Production command: no --reload, explicit workers.
# For more workers use gunicorn: gunicorn -w 4 -k uvicorn.workers.UvicornWorker main:app
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
