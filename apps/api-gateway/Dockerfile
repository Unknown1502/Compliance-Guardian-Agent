# API Gateway — Cloud Run container (public entry point).
# Copies all service packages so both inline and cloud dispatch modes work.
#   docker build -f apps/api-gateway/Dockerfile -t api-gateway .
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY shared/ /app/shared/
RUN pip install /app/shared

COPY apps/api-gateway/requirements.txt /app/requirements.txt
RUN pip install -r /app/requirements.txt

# Gateway code + the service packages it composes (task cores, escalation, orchestrator).
COPY apps/api-gateway/api_gateway/ /app/api_gateway/
COPY services/ingestion-agent/ingestion_agent/ /app/ingestion_agent/
COPY services/compliance-agent/compliance_agent/ /app/compliance_agent/
COPY services/escalation-service/escalation_service/ /app/escalation_service/
COPY services/orchestrator/orchestrator/ /app/orchestrator/
COPY services/reporting-agent/reporting_agent/ /app/reporting_agent/
COPY rulesets/ /app/rulesets/

ENV RULESETS_ROOT=/app/rulesets
ENV PORT=8080
CMD ["sh", "-c", "uvicorn api_gateway.main:app --host 0.0.0.0 --port ${PORT}"]
