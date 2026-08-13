# Scanner Agent — Cloud Run container running clamd alongside the API.
# Build context is the monorepo root so shared/ is available:
#   docker build -f services/scanner-agent/Dockerfile -t scanner-agent .
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# clamav-daemon is the scanner; clamav-freshclam fetches signature updates.
RUN apt-get update \
    && apt-get install -y --no-install-recommends clamav-daemon clamav-freshclam \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY shared/ /app/shared/
RUN pip install /app/shared

COPY services/scanner-agent/requirements.txt /app/requirements.txt
RUN pip install -r /app/requirements.txt

COPY services/scanner-agent/scanner_agent/ /app/scanner_agent/
# TaskService lives in the orchestrator package; the scanner uses it to hand a
# cleared document on to ingestion.
COPY services/orchestrator/orchestrator/ /app/orchestrator/
COPY services/scanner-agent/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# Bake the signature database into the image at build time.
#
# The alternative — downloading ~350 MB of signatures on every cold start —
# would add minutes to the first request and make the scanner's availability
# depend on database.clamav.net being reachable at exactly the wrong moment.
# The cost is that signatures are only as fresh as the last image build, so
# this image MUST be rebuilt on a schedule (see infra/cloudbuild-scanner.yaml);
# freshclam also runs once in the background at startup to close the gap on a
# long-lived instance.
RUN freshclam --quiet --stdout || \
    (echo "freshclam failed at build time — refusing to ship a scanner with no signatures" && exit 1)

# clamd listens on TCP rather than a unix socket, so the Python client is the
# same code locally and in the container.
#
# The config is REPLACED, not sed-patched. Patching Debian's shipped clamd.conf
# in place is how this broke the first time: the sed that was meant to enable
# TCPSocket matched nothing (the directive was absent, not commented), while
# the sed disabling LocalSocket did apply — leaving clamd with no listener at
# all. It exited with "Please define server type (local and/or TCP)" and every
# scan failed closed. Writing the file outright cannot half-apply.
RUN printf '%s\n' \
    'LogTime true' \
    'LogSyslog false' \
    'Foreground false' \
    'DatabaseDirectory /var/lib/clamav' \
    'TCPSocket 3310' \
    'TCPAddr 127.0.0.1' \
    'MaxScanSize 100M' \
    'MaxFileSize 25M' \
    'StreamMaxLength 25M' \
    'ScanArchive true' \
    '# Archive-bomb containment: stop expanding rather than exhausting the box.' \
    'MaxRecursion 10' \
    'MaxFiles 1000' \
    '# A file that trips those limits is reported as a threat, not waved' \
    '# through — an archive engineered to exhaust the scanner is hostile input.' \
    'AlertExceedsMax true' \
    > /etc/clamav/clamd.conf \
    && chown -R clamav:clamav /var/lib/clamav /etc/clamav/clamd.conf

ENV CLAMAV_HOST=127.0.0.1 \
    CLAMAV_PORT=3310 \
    PORT=8080

CMD ["/app/entrypoint.sh"]
