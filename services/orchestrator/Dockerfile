# Orchestrator — Cloud Run container.
#   docker build -f services/orchestrator/Dockerfile -t orchestrator .
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY shared/ /app/shared/
RUN pip install /app/shared

COPY services/orchestrator/requirements.txt /app/requirements.txt
RUN pip install -r /app/requirements.txt

COPY services/orchestrator/orchestrator/ /app/orchestrator/

ENV PORT=8080
CMD ["sh", "-c", "uvicorn orchestrator.main:app --host 0.0.0.0 --port ${PORT}"]
