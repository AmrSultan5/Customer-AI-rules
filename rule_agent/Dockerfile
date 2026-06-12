# Rule Agent — Backend
# Build: docker build -t rule-agent-backend .
# Run:   docker run -p 8000:8000 --env-file backend/.env rule-agent-backend

# Pin base image for reproducible builds. Update deliberately.
FROM python:3.11.9-slim

WORKDIR /app

# Install dependencies first (layer cache)
COPY backend/requirements.txt ./requirements.txt
COPY backend/requirements-lock.txt ./requirements-lock.txt
RUN pip install --no-cache-dir -r requirements-lock.txt

# Copy application source (exclude data files — mount via volume in production)
COPY backend/*.py ./

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
