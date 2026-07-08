"""Seed script — Phase 1 gate artifact.

Creates against emulators (or a real project if emulator env vars are unset):
  1. BigQuery dataset + audit_logs / reports tables (from the same JSON schemas
     Terraform uses — one schema source, two consumers).
  2. Cloud Storage buckets for raw docs + reports.
  3. Firestore: 2 demo tenants, sample documents, and one pre-scored
     compliance check so the dashboard has data on first boot.
  4. Validates every ruleset YAML under /rulesets through the Pydantic models.
  5. Uploads the sample documents to the raw-docs bucket.
  6. Writes seed audit events through the real AuditLogger (proving the
     append-only write path works end to end).

Idempotent by design: Firestore writes use fixed IDs with set() (upsert),
bucket/dataset/table creation tolerates already-exists, and audit events use
deterministic event_ids — re-running the seed cannot duplicate audit rows
within BigQuery's dedup window nor corrupt state.

Run:  python scripts/seed.py
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "shared"))

from google.api_core.exceptions import Conflict, NotFound  # noqa: E402
from google.cloud import bigquery  # noqa: E402

from audit_logger import AuditLogger  # noqa: E402
from gcp_clients import (  # noqa: E402
    audit_dataset,
    audit_table,
    bigquery_client,
    firestore_client,
    project_id,
    raw_docs_bucket,
    reports_bucket,
    reports_table,
    storage_client,
)
from schema_validators import (  # noqa: E402
    CheckDecision,
    ComplianceCheck,
    Document,
    DocumentStatus,
    GeminiCallMetadata,
    RuleVerdict,
    RuleVerdictStatus,
    Tenant,
    load_ruleset_file,
)

RULESETS_DIR = REPO_ROOT / "rulesets"
SAMPLES_DIR = REPO_ROOT / "scripts" / "sample_documents"
SCHEMAS_DIR = REPO_ROOT / "infra" / "terraform" / "schemas"


def log(msg: str) -> None:
    print(f"[seed] {msg}")


# ---------------------------------------------------------------------------
# 1. BigQuery dataset + tables
# ---------------------------------------------------------------------------


def _schema_from_json(path: Path) -> list[bigquery.SchemaField]:
    with path.open("r", encoding="utf-8") as fh:
        fields = json.load(fh)
    return [
        bigquery.SchemaField(
            f["name"], f["type"], mode=f.get("mode", "NULLABLE"), description=f.get("description")
        )
        for f in fields
    ]


def seed_bigquery() -> None:
    bq = bigquery_client()
    ds_id = f"{project_id()}.{audit_dataset()}"
    # Check-then-create: the goccy emulator returns 500 (retryable) instead of
    # 409 on duplicate create_dataset, which would loop the client's retry.
    try:
        bq.get_dataset(ds_id)
        log(f"BigQuery dataset {ds_id} already exists")
    except NotFound:
        try:
            bq.create_dataset(bigquery.Dataset(ds_id), retry=None)
            log(f"created BigQuery dataset {ds_id}")
        except Conflict:
            log(f"BigQuery dataset {ds_id} already exists (create race)")

    for table_name, schema_file in (
        (audit_table(), "audit_logs.json"),
        (reports_table(), "reports.json"),
    ):
        table_ref = f"{ds_id}.{table_name}"
        schema = _schema_from_json(SCHEMAS_DIR / schema_file)
        try:
            bq.get_table(table_ref)
            log(f"BigQuery table {table_ref} already exists")
        except NotFound:
            bq.create_table(bigquery.Table(table_ref, schema=schema))
            log(f"created BigQuery table {table_ref}")

    # Show the live schema back (gate evidence).
    for table_name in (audit_table(), reports_table()):
        t = bq.get_table(f"{ds_id}.{table_name}")
        cols = ", ".join(f"{f.name}:{f.field_type}" for f in t.schema)
        log(f"schema {table_name}: {cols}")


# ---------------------------------------------------------------------------
# 2. Cloud Storage buckets
# ---------------------------------------------------------------------------


def seed_buckets() -> None:
    gcs = storage_client()
    for bucket_name in (raw_docs_bucket(), reports_bucket()):
        bucket = gcs.bucket(bucket_name)
        if bucket.exists():
            log(f"bucket {bucket_name} already exists")
        else:
            gcs.create_bucket(bucket)
            log(f"created bucket {bucket_name}")


# ---------------------------------------------------------------------------
# 3. Rulesets — validate every YAML through Pydantic
# ---------------------------------------------------------------------------


def validate_rulesets() -> dict[str, str]:
    """Returns {industry/jurisdiction: version} for all valid rulesets."""
    found: dict[str, str] = {}
    yaml_files = sorted(RULESETS_DIR.glob("*/*.yaml"))
    if not yaml_files:
        raise SystemExit("no ruleset YAML files found — cannot seed")
    for path in yaml_files:
        rs = load_ruleset_file(path)  # raises on any schema violation
        key = f"{rs.industry}/{rs.jurisdiction}"
        found[key] = rs.rule_set_version
        log(
            f"ruleset OK: {path.relative_to(REPO_ROOT)} -> {key} "
            f"v{rs.rule_set_version} ({len(rs.rules)} rules)"
        )
    return found


# ---------------------------------------------------------------------------
# 4. Firestore demo data
# ---------------------------------------------------------------------------

TENANTS = [
    Tenant(
        tenant_id="tenant-sunrise-care",
        name="Sunrise Community Care Pty Ltd",
        industry="healthcare_ndis",
        jurisdiction="AU",
        plan_tier="starter",
        created_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
    ),
    Tenant(
        tenant_id="tenant-coastal-fresh",
        name="Coastal Fresh Distributors Pty Ltd",
        industry="contract_review",
        jurisdiction="generic",
        plan_tier="free",
        created_at=datetime(2026, 6, 15, tzinfo=timezone.utc),
    ),
]

SAMPLE_UPLOADS = [
    # (tenant_id, doc_id, local filename)
    ("tenant-sunrise-care", "doc-ndis-compliant", "ndis_service_record_compliant.txt"),
    ("tenant-sunrise-care", "doc-ndis-violations", "ndis_service_record_violations.txt"),
    ("tenant-coastal-fresh", "doc-msa-contract", "msa_contract_compliant.txt"),
    ("tenant-coastal-fresh", "doc-supplier-invoice", "supplier_invoice_compliant.txt"),
]


def seed_firestore_and_storage() -> None:
    fs = firestore_client()
    gcs = storage_client()
    bucket = gcs.bucket(raw_docs_bucket())

    for tenant in TENANTS:
        fs.collection("tenants").document(tenant.tenant_id).set(
            tenant.model_dump(mode="json")
        )
        log(f"tenant upserted: {tenant.tenant_id} ({tenant.name})")

    for tenant_id, doc_id, filename in SAMPLE_UPLOADS:
        local = SAMPLES_DIR / filename
        blob_path = f"{tenant_id}/{doc_id}/{filename}"
        blob = bucket.blob(blob_path)
        blob.upload_from_filename(str(local), content_type="text/plain")
        storage_ref = f"gs://{raw_docs_bucket()}/{blob_path}"
        document = Document(
            document_id=doc_id,
            tenant_id=tenant_id,
            source="seed_upload",
            storage_ref=storage_ref,
            extracted_fields={},
            status=DocumentStatus.PENDING,
        )
        fs.collection("documents").document(doc_id).set(document.model_dump(mode="json"))
        log(f"document upserted: {doc_id} -> {storage_ref}")

    # One pre-scored check so the dashboard renders real data before Phase 2.
    demo_check = ComplianceCheck(
        check_id="check-seed-demo",
        document_id="doc-ndis-compliant",
        tenant_id="tenant-sunrise-care",
        rule_set_version="1.0.0",
        risk_score=12,
        justification=(
            "All five NDIS rules evaluated as passing. Consent record CF-2024-1187 is "
            "explicit and predates processing; retention date 2033-05-14 satisfies the "
            "7-year minimum from service date 2026-05-14; provider registration 40512345 "
            "matches the NDIS format; worker screening clearance is current. Residual "
            "score reflects a single low-confidence extraction (worker clearance expiry "
            "read from free text)."
        ),
        citations=[
            "data_retention_period",
            "consent_documentation",
            "provider_registration_current",
            "worker_screening_check",
        ],
        decision=CheckDecision.AUTO_APPROVED,
        reviewer_id=None,
        rule_verdicts=[
            RuleVerdict(
                rule_id="data_retention_period",
                status=RuleVerdictStatus.PASS,
                confidence=0.97,
                explanation="Retention date 2033-05-14 is exactly 7 years after service date 2026-05-14.",
                triggering_data_point="record_retention_date=2033-05-14",
            ),
            RuleVerdict(
                rule_id="consent_documentation",
                status=RuleVerdictStatus.PASS,
                confidence=0.99,
                explanation="Signed consent form CF-2024-1187 executed 2024-02-01 covers data processing.",
                triggering_data_point="consent_record=CF-2024-1187",
            ),
            RuleVerdict(
                rule_id="provider_registration_current",
                status=RuleVerdictStatus.PASS,
                confidence=0.98,
                explanation="Registration number 40512345 matches NDIS 4-prefix 8-digit format.",
                triggering_data_point="provider_registration_number=40512345",
            ),
            RuleVerdict(
                rule_id="incident_reporting_window",
                status=RuleVerdictStatus.PASS,
                confidence=0.95,
                explanation="No reportable incidents in the period; rule not triggered.",
                triggering_data_point=None,
            ),
            RuleVerdict(
                rule_id="worker_screening_check",
                status=RuleVerdictStatus.PASS,
                confidence=0.90,
                explanation="Worker screening clearance NDIS-WSC-88231-VIC valid to 2028-11-02.",
                triggering_data_point="worker_screening_clearance=NDIS-WSC-88231-VIC",
            ),
        ],
        gemini_metadata=GeminiCallMetadata(
            prompt_version="seed_fixture_v1",
            model_name="seed-fixture",
            model_version=None,
            response_id=None,
        ),
    )
    fs.collection("compliance_checks").document(demo_check.check_id).set(
        demo_check.model_dump(mode="json")
    )
    log(f"compliance check upserted: {demo_check.check_id} (risk={demo_check.risk_score})")


# ---------------------------------------------------------------------------
# 5. Audit events through the real logger
# ---------------------------------------------------------------------------


def seed_audit_events() -> None:
    auditor = AuditLogger(bigquery_client(), audit_dataset(), audit_table())
    for tenant in TENANTS:
        row = auditor.log(
            tenant_id=tenant.tenant_id,
            actor="seed-script",
            action="tenant.seeded",
            dedup_key=tenant.tenant_id,  # deterministic → re-runs dedup
            before_state=None,
            after_state={"name": tenant.name, "industry": tenant.industry},
        )
        log(f"audit event written: {row.event_id} tenant.seeded {tenant.tenant_id}")
    for tenant_id, doc_id, filename in SAMPLE_UPLOADS:
        row = auditor.log(
            tenant_id=tenant_id,
            actor="seed-script",
            action="document.seeded",
            dedup_key=doc_id,
            before_state=None,
            after_state={"document_id": doc_id, "file": filename, "status": "pending"},
        )
        log(f"audit event written: {row.event_id} document.seeded {doc_id}")


def verify_audit_rows() -> None:
    """Read back audit rows so the gate shows a real round-trip."""
    bq = bigquery_client()
    # CAST(created_at AS STRING): the goccy emulator serializes TIMESTAMP as
    # float epoch-seconds, which the python client can't parse as TIMESTAMP.
    # Casting server-side keeps the round-trip verifiable on both emulator
    # and live BigQuery.
    query = (
        f"SELECT event_id, tenant_id, actor, action, "
        f"CAST(created_at AS STRING) AS created_at "
        f"FROM `{project_id()}.{audit_dataset()}.{audit_table()}` "
        f"ORDER BY created_at DESC LIMIT 10"
    )
    rows = list(bq.query(query).result())
    log(f"audit_logs row count returned: {len(rows)}")
    for r in rows:
        log(f"  {r['created_at']} | {r['tenant_id']} | {r['actor']} | {r['action']}")


def main() -> None:
    log(f"project={project_id()}")
    log(f"FIRESTORE_EMULATOR_HOST={os.environ.get('FIRESTORE_EMULATOR_HOST', '(live)')}")
    log(f"BIGQUERY_EMULATOR_HOST={os.environ.get('BIGQUERY_EMULATOR_HOST', '(live)')}")
    log(f"STORAGE_EMULATOR_HOST={os.environ.get('STORAGE_EMULATOR_HOST', '(live)')}")

    validate_rulesets()
    seed_bigquery()
    seed_buckets()
    seed_firestore_and_storage()
    seed_audit_events()
    verify_audit_rows()
    log("seed complete ✓")


if __name__ == "__main__":
    main()
