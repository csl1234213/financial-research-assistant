# ============================================================
# Financial RAG Assistant — Production Dockerfile
# ============================================================
# Multi-stage build for FastAPI backend + Agent Worker
# Usage:
#   docker build -t financial-rag-api:latest .
#   docker build --target api -t financial-rag-api:latest .
#   docker build --target worker -t financial-rag-worker:latest .
# ============================================================

FROM python:3.12-slim AS builder

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libgl1 \
    libglib2.0-0 \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements ./requirements
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements/api.txt && \
    pip check


FROM python:3.12-slim AS runtime

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    curl \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd -r appuser && useradd -r -g appuser -m appuser

WORKDIR /app

COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

COPY --chown=appuser:appuser . .

RUN mkdir -p /app/chroma_db /app/storage/uploads /app/storage/memory /app/logs /app/backup && \
    chown -R appuser:appuser /app/chroma_db /app/storage /app/logs /app/backup

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8000/api/v1/ready || exit 1

FROM runtime AS api
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]

FROM runtime AS worker
CMD ["python", "-m", "workers.agent_worker"]
