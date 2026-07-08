"""Phase 2 end-to-end demo — the gate artifact.

Runs the REAL pipeline against the seeded emulators + the REAL Gemini API:

    raw file (Cloud Storage)
      -> Ingestion Agent  -> Gemini extraction (strict JSON, missing-field flags)
      -> Compliance Agent -> Gemini reasoning  (per-rule verdicts, risk score,
                                                validated citations, decision)
      -> Firestore (live state) + BigQuery (audit trail)

Requires GEMINI_API_KEY in the environment. Emulator env vars must point at the
running docker-compose emulators (same as the seed script).

Usage:
    python scripts/demo_phase2.py                      # default: NDIS violations doc
    python scripts/demo_phase2.py doc-ndis-compliant   # a compliant doc
    python scripts/demo_phase2.py doc-supplier-invoice tenant-coastal-fresh
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "shared"))
sys.path.insert(0, str(REPO_ROOT / "services" / "ingestion-agent"))
sys.path.insert(0, str(REPO_ROOT / "services" / "compliance-agent"))

import os  # noqa: E402


def _load_local_env() -> None:
    """Load compliance-agent/.env (gitignored) into os.environ if present.

    Minimal KEY=VALUE parser — avoids a python-dotenv dependency. Never prints
    values, so the API key stays out of logs.
    """
    env_path = REPO_ROOT / ".env"
    if not env_path.is_file():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        # Real env vars take precedence over the file.
        os.environ.setdefault(key, value)


_load_local_env()

from audit_logger import AuditLogger  # noqa: E402
from compliance_agent.checker import run_compliance_check  # noqa: E402
from gcp_clients import (  # noqa: E402
    audit_dataset,
    audit_table,
    bigquery_client,
    firestore_client,
    project_id,
    storage_client,
)
from gcp_clients.firestore_repo import FirestoreRepo  # noqa: E402
from gemini_client import GeminiClient  # noqa: E402
from ingestion_agent.extractor import ingest_document  # noqa: E402

RULESETS_ROOT = str(REPO_ROOT / "rulesets")
ESCALATION_THRESHOLD = int(os.environ.get("RISK_ESCALATION_THRESHOLD", "60"))

# Document -> tenant map for the seeded demo docs.
DOC_TENANTS = {
    "doc-ndis-compliant": "tenant-sunrise-care",
    "doc-ndis-violations": "tenant-sunrise-care",
    "doc-msa-contract": "tenant-coastal-fresh",
    "doc-supplier-invoice": "tenant-coastal-fresh",
}


def hr(title: str) -> None:
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)


def main() -> None:
    document_id = sys.argv[1] if len(sys.argv) > 1 else "doc-ndis-violations"
    tenant_id = (
        sys.argv[2] if len(sys.argv) > 2 else DOC_TENANTS.get(document_id, "tenant-sunrise-care")
    )

    if not os.environ.get("GEMINI_API_KEY"):
        raise SystemExit(
            "GEMINI_API_KEY is not set. Set it in your shell before running the demo."
        )

    hr(f"ComplianceGuardian — Phase 2 live run: {document_id} (tenant {tenant_id})")
    print(f"project={project_id()}  model={os.environ.get('GEMINI_MODEL', 'gemini-2.5-flash')}")
    print(f"FIRESTORE_EMULATOR_HOST={os.environ.get('FIRESTORE_EMULATOR_HOST', '(live)')}")
    print(f"escalation_threshold={ESCALATION_THRESHOLD}")

    repo = FirestoreRepo(firestore_client())
    gemini = GeminiClient()
    auditor = AuditLogger(bigquery_client(), audit_dataset(), audit_table())

    # -- Ingestion (real Gemini extraction) --------------------------------
    hr("STEP 1 — Ingestion Agent (real Gemini extraction)")
    t0 = time.time()
    ing = ingest_document(
        document_id=document_id,
        tenant_id=tenant_id,
        repo=repo,
        storage_client=storage_client(),
        gemini=gemini,
        auditor=auditor,
        rulesets_root=RULESETS_ROOT,
    )
    print(f"status={ing.status.value}  ({time.time() - t0:.1f}s)")
    print(f"prompt_version={ing.prompt_version}  model={ing.model_name}  model_version={ing.model_version}")
    print("extracted_fields:")
    print(json.dumps(ing.extracted_fields, indent=2, default=str))
    print(f"missing_required_fields: {ing.missing_required_fields}")

    # -- Compliance (real Gemini reasoning) --------------------------------
    hr("STEP 2 — Compliance Agent (real Gemini reasoning)")
    t1 = time.time()
    out = run_compliance_check(
        document_id=document_id,
        tenant_id=tenant_id,
        repo=repo,
        gemini=gemini,
        auditor=auditor,
        rulesets_root=RULESETS_ROOT,
        escalation_threshold=ESCALATION_THRESHOLD,
    )
    c = out.check
    print(f"({time.time() - t1:.1f}s)")
    print(f"prompt_version={c.gemini_metadata.prompt_version}  model={c.gemini_metadata.model_name}  model_version={c.gemini_metadata.model_version}")
    print(f"\nRISK SCORE: {c.risk_score}/100   (Gemini raw: {out.gemini_raw_risk_score})")
    print(f"DECISION:   {c.decision.value.upper()}")
    print(f"CITATIONS:  {c.citations}")
    if out.dropped_citations:
        print(f"DROPPED (fabricated) citations: {out.dropped_citations}")
    print(f"\nJUSTIFICATION:\n  {c.justification}")
    print("\nPER-RULE VERDICTS:")
    for v in c.rule_verdicts:
        print(
            f"  [{v.status.value.upper():9}] {v.rule_id}  (conf {v.confidence:.2f})\n"
            f"      {v.explanation}\n"
            f"      trigger: {v.triggering_data_point}"
        )

    # -- Audit trail (real BigQuery read-back) -----------------------------
    hr("STEP 3 — Audit trail (BigQuery, append-only)")
    bq = bigquery_client()
    q = (
        f"SELECT actor, action, CAST(created_at AS STRING) AS created_at "
        f"FROM `{project_id()}.{audit_dataset()}.{audit_table()}` "
        f"WHERE tenant_id = @tenant AND actor IN ('ingestion-agent','compliance-agent') "
        f"ORDER BY created_at DESC LIMIT 6"
    )
    from google.cloud import bigquery as _bq  # local import to keep top clean

    job = bq.query(
        q,
        job_config=_bq.QueryJobConfig(
            query_parameters=[_bq.ScalarQueryParameter("tenant", "STRING", tenant_id)]
        ),
    )
    for r in job.result():
        print(f"  {r['created_at']} | {r['actor']} | {r['action']}")

    hr("DEMO COMPLETE ✓")
    print(f"Total wall time: {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
