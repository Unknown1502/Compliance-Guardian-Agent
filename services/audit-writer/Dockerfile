# Audit Writer — Cloud Run container.
# Build context is the monorepo root so shared/ is available:
#   docker build -f services/audit-writer/Dockerfile -t audit-writer .
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY shared/ /app/shared/
RUN pip install /app/shared

COPY services/audit-writer/requirements.txt /app/requirements.txt
RUN pip install -r /app/requirements.txt

COPY services/audit-writer/audit_writer/ /app/audit_writer/

ENV PORT=8080
CMD ["sh", "-c", "uvicorn audit_writer.main:app --host 0.0.0.0 --port ${PORT}"]
