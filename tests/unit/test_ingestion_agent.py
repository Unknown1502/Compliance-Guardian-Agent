"""Unit tests: Ingestion Agent core (hermetic — fakes for repo/storage/gemini/audit)."""

from __future__ import annotations

import pytest
from conftest import (
    RULESETS_ROOT,
    FakeAuditor,
    FakeGemini,
    FakeRepo,
    FakeStorage,
    gemini_result,
)

from ingestion_agent.extractor import derive_field_list, ingest_document
from schema_validators import DocumentStatus, load_ruleset

SAMPLE_TEXT = b"NDIS record with client_name: Jane and consent_record: CF-1"


class TestDeriveFieldList:
    def test_includes_required_and_rule_referenced_fields(self):
        rs = load_ruleset(RULESETS_ROOT, "healthcare_ndis", "AU")
        fields, required = derive_field_list(rs)
        # required fields present
        for f in rs.required_fields:
            assert f in fields
        # rule-referenced field (incident dates) pulled in beyond required set
        assert "incident_report_date" in fields
        assert "incident_identified_date" in fields
        assert required == rs.required_fields


class TestIngestDocument:
    def test_happy_path_marks_processed(self, ndis_tenant, ndis_document):
        repo = FakeRepo(ndis_tenant, ndis_document)
        gemini = FakeGemini(
            [
                gemini_result(
                    {
                        "fields": {
                            "client_name": "Jane",
                            "service_date": "2026-05-14",
                            "consent_record": "CF-1",
                            "record_retention_date": "2033-05-14",
                            "provider_registration_number": "40512345",
                        },
                        "missing_required_fields": [],
                    },
                    prompt_version="ingestion_v1",
                )
            ]
        )
        auditor = FakeAuditor()
        outcome = ingest_document(
            document_id="doc-ndis-1",
            tenant_id="tenant-sunrise-care",
            repo=repo,
            storage_client=FakeStorage(SAMPLE_TEXT),
            gemini=gemini,
            auditor=auditor,
            rulesets_root=RULESETS_ROOT,
        )
        assert outcome.status is DocumentStatus.PROCESSED
        assert outcome.extracted_fields["client_name"] == "Jane"
        assert outcome.missing_required_fields == []
        assert outcome.prompt_version == "ingestion_v1"
        # document persisted as processed
        assert repo.get_document("doc-ndis-1", "tenant-sunrise-care").status is DocumentStatus.PROCESSED
        # audit event recorded
        assert any(e["action"] == "document.ingested" for e in auditor.events)

    def test_missing_required_field_flagged(self, ndis_tenant, ndis_document):
        repo = FakeRepo(ndis_tenant, ndis_document)
        gemini = FakeGemini(
            [
                gemini_result(
                    {
                        "fields": {
                            "client_name": "Jane",
                            "service_date": "2026-05-14",
                            "consent_record": None,  # missing critical field
                            "record_retention_date": "2033-05-14",
                            "provider_registration_number": "40512345",
                        },
                        "missing_required_fields": ["consent_record"],
                    }
                )
            ]
        )
        outcome = ingest_document(
            document_id="doc-ndis-1",
            tenant_id="tenant-sunrise-care",
            repo=repo,
            storage_client=FakeStorage(SAMPLE_TEXT),
            gemini=gemini,
            auditor=FakeAuditor(),
            rulesets_root=RULESETS_ROOT,
        )
        assert "consent_record" in outcome.missing_required_fields

    def test_recomputes_missing_even_if_model_omits_them(self, ndis_tenant, ndis_document):
        # Model returns empty missing list but a required field is actually null.
        repo = FakeRepo(ndis_tenant, ndis_document)
        gemini = FakeGemini(
            [
                gemini_result(
                    {
                        "fields": {
                            "client_name": None,
                            "service_date": None,
                            "consent_record": None,
                            "record_retention_date": None,
                            "provider_registration_number": None,
                        },
                        "missing_required_fields": [],  # model under-reports
                    }
                )
            ]
        )
        outcome = ingest_document(
            document_id="doc-ndis-1",
            tenant_id="tenant-sunrise-care",
            repo=repo,
            storage_client=FakeStorage(SAMPLE_TEXT),
            gemini=gemini,
            auditor=FakeAuditor(),
            rulesets_root=RULESETS_ROOT,
        )
        # All five required fields recomputed as missing despite model's empty list.
        assert set(outcome.missing_required_fields) == set(
            load_ruleset(RULESETS_ROOT, "healthcare_ndis", "AU").required_fields
        )

    def test_gemini_failure_marks_document_failed_and_audits(self, ndis_tenant, ndis_document):
        repo = FakeRepo(ndis_tenant, ndis_document)

        class BoomGemini:
            def generate_json(self, **kwargs):
                raise RuntimeError("gemini exploded mid-extraction")

        auditor = FakeAuditor()
        with pytest.raises(RuntimeError):
            ingest_document(
                document_id="doc-ndis-1",
                tenant_id="tenant-sunrise-care",
                repo=repo,
                storage_client=FakeStorage(SAMPLE_TEXT),
                gemini=BoomGemini(),
                auditor=auditor,
                rulesets_root=RULESETS_ROOT,
            )
        # Partial-failure cleanup: document marked failed, failure audited.
        assert repo.get_document("doc-ndis-1", "tenant-sunrise-care").status is DocumentStatus.FAILED
        assert any(e["action"] == "document.ingestion_failed" for e in auditor.events)

    def test_tenant_mismatch_blocks_access(self, ndis_tenant, ndis_document):
        repo = FakeRepo(ndis_tenant, ndis_document)
        from gcp_clients.firestore_repo import TenantMismatchError

        with pytest.raises(TenantMismatchError):
            ingest_document(
                document_id="doc-ndis-1",
                tenant_id="tenant-attacker",  # not the owner
                repo=repo,
                storage_client=FakeStorage(SAMPLE_TEXT),
                gemini=FakeGemini([]),
                auditor=FakeAuditor(),
                rulesets_root=RULESETS_ROOT,
            )
