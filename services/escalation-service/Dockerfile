# Escalation Service — Cloud Run container.
#   docker build -f services/escalation-service/Dockerfile -t escalation-service .
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY shared/ /app/shared/
RUN pip install /app/shared

COPY services/escalation-service/requirements.txt /app/requirements.txt
RUN pip install -r /app/requirements.txt

COPY services/escalation-service/escalation_service/ /app/escalation_service/

ENV PORT=8080
CMD ["sh", "-c", "uvicorn escalation_service.main:app --host 0.0.0.0 --port ${PORT}"]
