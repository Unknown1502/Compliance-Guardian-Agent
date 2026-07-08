"""Phase 3 end-to-end demo — the gate artifact.

Demonstrates the reviewer approve/reject flow through the REAL API Gateway HTTP
handlers (FastAPI TestClient) against the REAL seeded emulators, then reads back
the resulting immutable audit_logs row from BigQuery.

Covered:
  1. RBAC            — an owner is forbidden from deciding (403); a reviewer can.
  2. Approve flow    — reviewer approves an escalated check -> decision resolves,
                       reviewer_id recorded, audit row written.
  3. Concurrency     — TWO reviewers hit the SAME escalation simultaneously (two
                       threads); exactly one wins (200) and one loses (409),
                       proving the Firestore transaction prevents a double
                       decision. THIS is the Phase 3 concurrency edge case.
  4. Audit trail     — the decision row (actor=reviewer_id, action, timestamp)
                       is read back from BigQuery.

FIXTURE NOTE (flagged): because the Phase 2 live Gemini run has not been executed
(no API key was provided), this demo seeds the escalated compliance_check as a
FIXTURE rather than producing it from a live Gemini reasoning call. The approve/
reject + audit-trail behaviour being demonstrated is fully real; only the
upstream risk score is fixture data. Run scripts/demo_phase2.py with a key to
produce that score for real.

Usage (emulators must be running + seeded):
    python scripts/demo_phase3.py
"""

from __future__ import annotations

import base64
import json
import os
import sys
import threading
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "shared"))
sys.path.insert(0, str(REPO_ROOT / "services" / "ingestion-agent"))
sys.path.insert(0, str(REPO_ROOT / "services" / "compliance-agent"))
sys.path.insert(0, str(REPO_ROOT / "services" / "escalation-service"))
sys.path.insert(0, str(REPO_ROOT / "services" / "orchestrator"))
sys.path.insert(0, str(REPO_ROOT / "apps" / "api-gateway"))

# Emulator + dev-auth wiring must be set BEFORE importing the app/clients.
os.environ.setdefault("GOOGLE_CLOUD_PROJECT", "cg-local")
os.environ.setdefault("FIRESTORE_EMULATOR_HOST", "localhost:8085")
os.environ.setdefault("BIGQUERY_EMULATOR_HOST", "http://localhost:9050")
os.environ.setdefault("STORAGE_EMULATOR_HOST", "http://localhost:4443")
os.environ["CG_AUTH_DEV_MODE"] = "1"
os.environ["CG_DISPATCH_MODE"] = "inline"

from fastapi.testclient import TestClient  # noqa: E402
from gcp_clients import (  # noqa: E402
    audit_dataset,
    audit_table,
    bigquery_client,
    firestore_client,
    project_id,
)
from schema_validators import (  # noqa: E402
    CheckDecision,
    ComplianceCheck,
    Document,
    DocumentStatus,
    RuleVerdict,
    RuleVerdictStatus,
)

TENANT = "tenant-sunrise-care"
DOC_ID = "doc-phase3-demo"
CHECK_ID = "check-phase3-demo"


def dev_token(uid: str, tenant_id: str, role: str) -> str:
    claims = {"uid": uid, "tenant_id": tenant_id, "role": role}
    raw = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return f"dev:{raw}"


def hr(title: str) -> None:
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)


def seed_escalated_fixture() -> None:
    """Write a processed document + an ESCALATED check (fixture) to Firestore."""
    fs = firestore_client()
    document = Document(
        document_id=DOC_ID,
        tenant_id=TENANT,
        source="phase3_demo_fixture",
        storage_ref=f"gs://cg-local-cg-raw-docs/{TENANT}/{DOC_ID}/record.txt",
        extracted_fields={"consent_record": None, "client_name": "Tom Rialto"},
        status=DocumentStatus.PROCESSED,
    )
    fs.collection("documents").document(DOC_ID).set(document.model_dump(mode="json"))

    check = ComplianceCheck(
        check_id=CHECK_ID,
        document_id=DOC_ID,
        tenant_id=TENANT,
        rule_set_version="1.0.0",
        risk_score=85,
        justification=(
            "Critical rule 'consent_documentation' failed: no consent record was "
            "found before data processing. Escalated for human review."
        ),
        citations=["consent_documentation"],
        decision=CheckDecision.ESCALATED,
        reviewer_id=None,
        rule_verdicts=[
            RuleVerdict(
                rule_id="consent_documentation",
                status=RuleVerdictStatus.FAIL,
                confidence=0.97,
                explanation="No consent record present in the document.",
                triggering_data_point="consent_record=null",
            ),
        ],
    )
    fs.collection("compliance_checks").document(CHECK_ID).set(check.model_dump(mode="json"))
    print(f"[fixture] seeded escalated check {CHECK_ID} (risk 85) for {DOC_ID}")


def reset_to_escalated() -> None:
    fs = firestore_client()
    ref = fs.collection("compliance_checks").document(CHECK_ID)
    snap = ref.get().to_dict()
    snap["decision"] = CheckDecision.ESCALATED.value
    snap["reviewer_id"] = None
    ref.set(snap)


def main() -> None:
    from api_gateway.main import app  # import after env is set

    client = TestClient(app)

    hr("ComplianceGuardian — Phase 3 live run: reviewer approve/reject + audit")
    print(f"project={project_id()}  auth=DEV_MODE  dispatch=inline")

    seed_escalated_fixture()

    owner = {"Authorization": f"Bearer {dev_token('owner-1', TENANT, 'owner')}"}
    rev1 = {"Authorization": f"Bearer {dev_token('reviewer-alice', TENANT, 'reviewer')}"}
    rev2 = {"Authorization": f"Bearer {dev_token('reviewer-bob', TENANT, 'reviewer')}"}

    # 1. Owner sees the escalated check but cannot decide.
    hr("STEP 1 — RBAC: owner can read, cannot decide")
    r = client.get(f"/api/compliance/checks/{CHECK_ID}", headers=owner)
    print(f"GET  (owner)   -> {r.status_code}  decision={r.json().get('decision')}")
    r = client.patch(f"/api/compliance/checks/{CHECK_ID}", json={"action": "approve"}, headers=owner)
    print(f"PATCH (owner)  -> {r.status_code}  (expected 403 — owners cannot review)")

    # 2. Reviewer approves.
    hr("STEP 2 — Reviewer approves the escalation")
    r = client.patch(f"/api/compliance/checks/{CHECK_ID}", json={"action": "approve"}, headers=rev1)
    print(f"PATCH (reviewer-alice) -> {r.status_code}")
    print(json.dumps(r.json(), indent=2))

    # 3. A second reviewer acting on the now-resolved item is rejected.
    hr("STEP 3 — Second reviewer on an already-decided item")
    r = client.patch(f"/api/compliance/checks/{CHECK_ID}", json={"action": "reject"}, headers=rev2)
    print(f"PATCH (reviewer-bob)   -> {r.status_code}  (expected 409 — already decided)")
    print(f"  detail: {r.json().get('detail')}")

    # 4. True concurrency: reset + two reviewers hit it at once.
    hr("STEP 4 — Concurrency proof: two reviewers decide the SAME item at once")
    reset_to_escalated()
    results: dict[str, int] = {}

    def do_decision(name: str, headers: dict, action: str) -> None:
        resp = client.patch(
            f"/api/compliance/checks/{CHECK_ID}", json={"action": action}, headers=headers
        )
        results[name] = resp.status_code

    t1 = threading.Thread(target=do_decision, args=("alice", rev1, "approve"))
    t2 = threading.Thread(target=do_decision, args=("bob", rev2, "reject"))
    t1.start(); t2.start(); t1.join(); t2.join()
    print(f"alice -> {results['alice']}   bob -> {results['bob']}")
    codes = sorted(results.values())
    if codes == [200, 409]:
        print("RESULT: exactly one succeeded (200) and one was blocked (409) ✓")
    else:
        print(f"RESULT: UNEXPECTED status combination {codes} — investigate")

    # 5. Audit trail read-back.
    hr("STEP 5 — Immutable audit trail (BigQuery)")
    time.sleep(1)  # allow streaming insert visibility
    bq = bigquery_client()
    from google.cloud import bigquery as _bq

    q = (
        f"SELECT actor, action, CAST(created_at AS STRING) AS created_at "
        f"FROM `{project_id()}.{audit_dataset()}.{audit_table()}` "
        f"WHERE tenant_id=@t AND action IN "
        f"('check.approved','check.rejected') ORDER BY created_at DESC LIMIT 5"
    )
    job = bq.query(q, job_config=_bq.QueryJobConfig(
        query_parameters=[_bq.ScalarQueryParameter("t", "STRING", TENANT)]
    ))
    rows = list(job.result())
    for r in rows:
        print(f"  {r['created_at']} | actor={r['actor']} | {r['action']}")
    print(f"\n{len(rows)} decision audit row(s) — each carries reviewer_id + timestamp.")

    hr("PHASE 3 DEMO COMPLETE ✓")


if __name__ == "__main__":
    main()
