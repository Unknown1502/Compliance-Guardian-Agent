"""Ingestion Agent core — read a raw file, extract structured fields via Gemini.

This module is HTTP-agnostic and Cloud-Tasks-agnostic: it exposes a single
`ingest_document()` function that the FastAPI handler (and the Phase 2 demo
script) call directly. That keeps the real end-to-end path identical whether
it's driven by a Cloud Task or a local runner.

Idempotency: writing extracted_fields to a fixed document_id is an upsert, so
Cloud Task redelivery re-extracts and overwrites the same document rather than
duplicating anything. On any failure the document is marked status=failed and
the failure is audit-logged — never left silently in `pending`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from urllib.parse import urlparse

from audit_logger import AuditLogger
from gcp_clients.firestore_repo import FirestoreRepo
from google.cloud import storage
from schema_validators import Document, DocumentStatus, RuleSet, load_ruleset

from ingestion_agent.prompts import (
    INGESTION_PROMPT_VERSION,
    INGESTION_SYSTEM_INSTRUCTION,
    build_ingestion_user_prompt,
)

logger = logging.getLogger("cg.ingestion")

# Extensions we send to Gemini as decoded text vs. as binary Parts.
_TEXT_EXTENSIONS = {".txt", ".md", ".csv", ".json"}
_MIME_BY_EXT = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".txt": "text/plain",
    ".md": "text/plain",
    ".csv": "text/csv",
    ".json": "application/json",
}


@dataclass(frozen=True)
class IngestionOutcome:
    document_id: str
    tenant_id: str
    status: DocumentStatus
    extracted_fields: dict
    missing_required_fields: list[str]
    prompt_version: str
    model_name: str
    model_version: str | None


def derive_field_list(ruleset: RuleSet) -> tuple[list[str], list[str]]:
    """Compute the dynamic extraction field list from the active ruleset.

    Fields of interest = required_fields ∪ every field referenced by any rule's
    params (field, fields[], relative_to). This ties extraction directly to what
    the compliance rules will consume — no more, no less.
    """
    fields: list[str] = list(ruleset.required_fields)
    seen = set(fields)

    def add(name: str | None) -> None:
        if name and name not in seen and name not in {"today"}:
            seen.add(name)
            fields.append(name)

    for rule in ruleset.rules:
        p = rule.params
        add(p.get("field"))
        add(p.get("relative_to"))
        add(p.get("total_field"))
        add(p.get("gst_field"))
        for f in p.get("fields", []) or []:
            add(f)
        for f in p.get("requires_fields_at_or_above", []) or []:
            add(f)

    return fields, list(ruleset.required_fields)


def _ext_of(storage_ref: str) -> str:
    path = urlparse(storage_ref).path
    dot = path.rfind(".")
    return path[dot:].lower() if dot != -1 else ""


def _read_blob(storage_client: storage.Client, storage_ref: str) -> bytes:
    parsed = urlparse(storage_ref)
    if parsed.scheme != "gs":
        raise ValueError(f"storage_ref must be a gs:// URI, got {storage_ref!r}")
    bucket_name = parsed.netloc
    blob_path = parsed.path.lstrip("/")
    blob = storage_client.bucket(bucket_name).blob(blob_path)
    return blob.download_as_bytes()


def ingest_document(
    *,
    document_id: str,
    tenant_id: str,
    repo: FirestoreRepo,
    storage_client: storage.Client,
    gemini,  # GeminiClient — untyped import to keep this module import-light
    auditor: AuditLogger,
    rulesets_root: str,
) -> IngestionOutcome:
    """Extract structured fields for one document. Tenant-scoped and idempotent."""
    document = repo.get_document(document_id, tenant_id)  # raises on tenant mismatch
    tenant = repo.get_tenant(tenant_id)

    try:
        ruleset = load_ruleset(rulesets_root, tenant.industry, tenant.jurisdiction)
        field_list, required_fields = derive_field_list(ruleset)
        document_type = f"{tenant.industry}/{tenant.jurisdiction}"

        raw = _read_blob(storage_client, document.storage_ref)
        ext = _ext_of(document.storage_ref)
        mime = _MIME_BY_EXT.get(ext, "application/octet-stream")

        user_prompt = build_ingestion_user_prompt(
            document_type=document_type,
            field_list=field_list,
            required_fields=required_fields,
        )

        if ext in _TEXT_EXTENSIONS:
            # Inline the text so the model sees it directly.
            text = raw.decode("utf-8", errors="replace")
            result = gemini.generate_json(
                prompt_version=INGESTION_PROMPT_VERSION,
                system_instruction=INGESTION_SYSTEM_INSTRUCTION,
                user_content=f"{user_prompt}\n\n--- DOCUMENT ---\n{text}",
            )
        else:
            # Binary (PDF/image): send as a Part alongside the instruction.
            result = gemini.generate_json(
                prompt_version=INGESTION_PROMPT_VERSION,
                system_instruction=INGESTION_SYSTEM_INSTRUCTION,
                user_content=user_prompt,
                file_bytes=raw,
                file_mime_type=mime,
            )

        extracted = result.data.get("fields")
        if not isinstance(extracted, dict):
            raise ValueError(
                f"extraction did not return a 'fields' object: {result.data!r}"
            )
        # Trust-but-verify the model's missing list: recompute from required set.
        model_missing = result.data.get("missing_required_fields") or []
        computed_missing = [
            f for f in required_fields if extracted.get(f) in (None, "", [])
        ]
        missing = sorted(set(computed_missing) | set(m for m in model_missing if m in required_fields))

        updated = document.model_copy(
            update={
                "extracted_fields": extracted,
                "status": DocumentStatus.PROCESSED,
            }
        )
        repo.upsert_document(updated)

        auditor.log(
            tenant_id=tenant_id,
            actor="ingestion-agent",
            action="document.ingested",
            dedup_key=f"{document_id}:{result.prompt_version}",
            before_state={"status": document.status.value, "extracted_fields": document.extracted_fields},
            after_state={
                "status": DocumentStatus.PROCESSED.value,
                "extracted_fields": extracted,
                "missing_required_fields": missing,
                "prompt_version": result.prompt_version,
                "model_name": result.model_name,
                "model_version": result.model_version,
            },
        )

        return IngestionOutcome(
            document_id=document_id,
            tenant_id=tenant_id,
            status=DocumentStatus.PROCESSED,
            extracted_fields=extracted,
            missing_required_fields=missing,
            prompt_version=result.prompt_version,
            model_name=result.model_name,
            model_version=result.model_version,
        )

    except Exception as exc:
        logger.exception("ingestion failed for document %s", document_id)
        # Partial-failure cleanup: mark failed, audit the failure, re-raise so
        # the caller (Cloud Task) can retry per the queue's retry policy.
        try:
            repo.update_document_fields(
                document_id, tenant_id, {"status": DocumentStatus.FAILED}
            )
        except Exception:  # noqa: BLE001 — never mask the original error
            logger.exception("failed to mark document %s as failed", document_id)
        auditor.log(
            tenant_id=tenant_id,
            actor="ingestion-agent",
            action="document.ingestion_failed",
            dedup_key=f"{document_id}:failure",
            before_state=None,
            after_state={"error": str(exc)[:500]},
        )
        raise
