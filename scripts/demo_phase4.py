"""Phase 4 end-to-end demo — the gate artifact.

Demonstrates:
  1. POST /api/reports → generates a Gemini report (or fixture) for a period
     → writes HTML to GCS → writes row to BigQuery reports table → audits
  2. GET  /api/reports/{id} → serves the HTML from GCS

All via the real API Gateway (FastAPI TestClient) against real seeded emulators.
"""

from __future__ import annotations

import base64
import json
import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "shared"))
sys.path.insert(0, str(REPO_ROOT / "services" / "ingestion-agent"))
sys.path.insert(0, str(REPO_ROOT / "services" / "compliance-agent"))
sys.path.insert(0, str(REPO_ROOT / "services" / "escalation-service"))
sys.path.insert(0, str(REPO_ROOT / "services" / "orchestrator"))
sys.path.insert(0, str(REPO_ROOT / "services" / "reporting-agent"))
sys.path.insert(0, str(REPO_ROOT / "apps" / "api-gateway"))

os.environ.setdefault("GOOGLE_CLOUD_PROJECT", "cg-local")
os.environ.setdefault("FIRESTORE_EMULATOR_HOST", "localhost:8085")
os.environ.setdefault("BIGQUERY_EMULATOR_HOST", "http://localhost:9050")
os.environ.setdefault("STORAGE_EMULATOR_HOST", "http://localhost:4443")
os.environ["CG_AUTH_DEV_MODE"] = "1"
os.environ["CG_DISPATCH_MODE"] = "inline"


def hr(title: str) -> None:
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)


def dev_token(uid: str, tenant_id: str, role: str) -> str:
    claims = {"uid": uid, "tenant_id": tenant_id, "role": role}
    raw = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return f"dev:{raw}"


def main() -> None:
    from fastapi.testclient import TestClient
    from gcp_clients import audit_dataset, audit_table, bigquery_client, project_id
    from google.cloud import bigquery as bq_module

    from api_gateway.main import app  # imported AFTER env vars are set

    client = TestClient(app)

    hr("ComplianceGuardian — Phase 4 live run: Reporting Agent")
    print(f"project={project_id()}  auth=DEV_MODE  dispatch=inline")
    print(f"GEMINI_API_KEY={'SET' if os.environ.get('GEMINI_API_KEY') else 'NOT SET — fixture mode'}")

    hdr_owner = {"Authorization": f"Bearer {dev_token('owner-1', 'tenant-sunrise-care', 'owner')}"}

    # -- Generate a report for the full seeded period ------------------------
    hr("STEP 1 — POST /api/reports (on-demand)")
    t0 = time.time()
    r = client.post(
        "/api/reports",
        json={"period_start": "2026-01-01T00:00:00Z", "period_end": "2026-07-08T23:59:59Z"},
        headers=hdr_owner,
    )
    print(f"POST /api/reports -> {r.status_code}  ({time.time()-t0:.1f}s)")
    body = r.json()
    assert r.status_code == 200, f"unexpected status: {r.status_code} {body}"

    print(f"report_id:         {body['report_id']}")
    print(f"tenant_id:         {body['tenant_id']}")
    print(f"total_checks:      {body['total_checks']}")
    print(f"pass_count:        {body['pass_count']}")
    print(f"escalated_count:   {body['escalated_count']}")
    print(f"rejected_count:    {body['fail_count']}")
    print(f"model_name:        {body['model_name']}")
    print(f"prompt_version:    {body['prompt_version']}")
    print(f"used_fixture:      {body['used_fixture']}")
    print(f"content_ref:       {body['content_ref']}")
    print(f"\nexecutive_summary:\n  {body['executive_summary']}")

    # -- Retrieve the HTML artifact from GCS ---------------------------------
    hr("STEP 2 — GET /api/reports/{id} (HTML from GCS)")
    report_id = body["report_id"]
    r2 = client.get(f"/api/reports/{report_id}", headers=hdr_owner)
    print(f"GET /api/reports/{report_id[:8]}... -> {r2.status_code}")
    print(f"content-type: {r2.headers.get('content-type', '?')}")
    print(f"HTML length:  {len(r2.text)} chars")
    assert "Compliance Report" in r2.text
    assert "Executive summary" in r2.text
    print("HTML contains expected section headers [OK]")

    # -- BigQuery reports table row ------------------------------------------
    hr("STEP 3 — BigQuery reports table row")
    bq = bigquery_client()
    q = (
        f"SELECT report_id, tenant_id, generated_by, content_ref, "
        f"CAST(created_at AS STRING) AS created_at "
        f"FROM `{project_id()}.{audit_dataset()}.reports` "
        f"WHERE tenant_id = @tenant ORDER BY created_at DESC LIMIT 3"
    )
    job = bq.query(q, job_config=bq_module.QueryJobConfig(
        query_parameters=[bq_module.ScalarQueryParameter("tenant", "STRING", "tenant-sunrise-care")]
    ))
    rows = list(job.result())
    print(f"reports rows for tenant: {len(rows)}")
    for row in rows:
        print(f"  {row['created_at']} | {row['report_id'][:12]}... | {row['generated_by']}")

    # -- Audit trail ---------------------------------------------------------
    hr("STEP 4 — Audit trail (report.generated event)")
    q2 = (
        f"SELECT actor, action, CAST(created_at AS STRING) AS created_at "
        f"FROM `{project_id()}.{audit_dataset()}.{audit_table()}` "
        f"WHERE tenant_id=@t AND action='report.generated' ORDER BY created_at DESC LIMIT 3"
    )
    job2 = bq.query(q2, job_config=bq_module.QueryJobConfig(
        query_parameters=[bq_module.ScalarQueryParameter("t", "STRING", "tenant-sunrise-care")]
    ))
    events = list(job2.result())
    for e in events:
        print(f"  {e['created_at']} | actor={e['actor']} | {e['action']}")

    hr("PHASE 4 DEMO COMPLETE")


if __name__ == "__main__":
    main()
