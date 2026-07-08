# Reporting Agent — Cloud Run container.
#   docker build -f services/reporting-agent/Dockerfile -t reporting-agent .
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY shared/ /app/shared/
RUN pip install /app/shared

COPY services/reporting-agent/requirements.txt /app/requirements.txt
RUN pip install -r /app/requirements.txt

COPY services/reporting-agent/reporting_agent/ /app/reporting_agent/

ENV PORT=8080
CMD ["sh", "-c", "uvicorn reporting_agent.main:app --host 0.0.0.0 --port ${PORT}"]
