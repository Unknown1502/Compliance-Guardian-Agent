# Ingestion Agent — Cloud Run container.
# Build context is the monorepo root so shared/ and rulesets/ are available:
#   docker build -f services/ingestion-agent/Dockerfile -t ingestion-agent .
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install shared packages first (better layer caching).
COPY shared/ /app/shared/
RUN pip install /app/shared

# Service dependencies.
COPY services/ingestion-agent/requirements.txt /app/requirements.txt
RUN pip install -r /app/requirements.txt

# Service code + rulesets (read at runtime for the dynamic field list).
COPY services/ingestion-agent/ingestion_agent/ /app/ingestion_agent/
COPY rulesets/ /app/rulesets/

ENV RULESETS_ROOT=/app/rulesets

# Cloud Run provides $PORT (default 8080). uvicorn binds to it.
ENV PORT=8080
CMD ["sh", "-c", "uvicorn ingestion_agent.main:app --host 0.0.0.0 --port ${PORT}"]
