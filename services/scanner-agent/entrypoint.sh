#!/bin/sh
# Start clamd, then the API.
#
# The API is started even if clamd never becomes ready. That is deliberate: a
# scanner service that refuses to boot takes itself out of rotation and leaves
# uploads with no record of why they stalled. Booting anyway means every scan
# returns SCAN_FAILED, documents stay quarantined, and the audit trail says
# exactly what happened — contained failure, with evidence.
set -eu

echo "starting clamd..."
clamd &

# clamd loads ~350 MB of signatures before it accepts connections; on Cloud Run
# that is tens of seconds. Poll rather than sleeping a fixed guess.
i=0
while [ "$i" -lt 90 ]; do
    if clamdscan --ping 1 >/dev/null 2>&1; then
        echo "clamd ready after ${i}s"
        break
    fi
    i=$((i + 1))
    sleep 1
done

if [ "$i" -ge 90 ]; then
    echo "WARNING: clamd did not become ready in 90s — scans will fail closed"
fi

# Refresh signatures once in the background. The image ships with the set baked
# in at build time; this closes the gap for an instance that stays warm. Failure
# is logged and ignored — stale signatures still scan, and taking the service
# down over a failed update would be worse than the staleness.
(freshclam --quiet --stdout || echo "WARNING: freshclam update failed; using baked-in signatures") &

exec uvicorn scanner_agent.main:app --host 0.0.0.0 --port "${PORT:-8080}"
