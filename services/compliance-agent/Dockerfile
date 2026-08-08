# Compliance Agent — Cloud Run container.
#   docker build -f services/compliance-agent/Dockerfile -t compliance-agent .
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY shared/ /app/shared/
RUN pip install /app/shared

COPY services/compliance-agent/requirements.txt /app/requirements.txt
RUN pip install -r /app/requirements.txt

COPY services/compliance-agent/compliance_agent/ /app/compliance_agent/
# The compliance service generates the remediation plan immediately after
# writing its verdict, so this package ships with it.
COPY services/remediation-agent/remediation_agent/ /app/remediation_agent/
COPY rulesets/ /app/rulesets/

ENV RULESETS_ROOT=/app/rulesets
ENV PORT=8080
CMD ["sh", "-c", "uvicorn compliance_agent.main:app --host 0.0.0.0 --port ${PORT}"]
