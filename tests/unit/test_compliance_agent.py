"""Unit tests: Compliance Agent core (hermetic).

Covers the safeguards from the Phase 2 Thinking Protocol: fabricated-citation
rejection, severity score reconciliation, decision threshold, missing-verdict
injection, idempotent check_id, and failure auditing.
"""

from __future__ import annotations

import pytest
from conftest import RULESETS_ROOT, FakeAuditor, FakeGemini, FakeRepo, gemini_result

from compliance_agent.checker import (
    deterministic_check_id,
    run_compliance_check,
)
from schema_validators import CheckDecision, Document, DocumentStatus, RuleVerdictStatus


def _all_ndis_rule_ids() -> list[str]:
    """Rule ids straight from the real NDIS ruleset.

    Derived rather than hardcoded so expanding the ruleset can't quietly
    turn these scenarios into something they no longer test.
    """
    from schema_validators import load_ruleset

    return [r.id for r in load_ruleset(RULESETS_ROOT, "healthcare_ndis", "AU").rules]


def _processed_doc() -> Document:
    return Document(
        document_id="doc-ndis-1",
        tenant_id="tenant-sunrise-care",
        source="upload",
        storage_ref="gs://b/doc-ndis-1/x.txt",
        extracted_fields={
            "client_name": "Jane",
            "service_date": "2026-05-14",
            "consent_record": None,
            "record_retention_date": "2033-05-14",
            "provider_registration_number": "40512345",
        },
        status=DocumentStatus.PROCESSED,
    )


def _run(repo, gemini, auditor, threshold=60):
    return run_compliance_check(
        document_id="doc-ndis-1",
        tenant_id="tenant-sunrise-care",
        repo=repo,
        gemini=gemini,
        auditor=auditor,
        rulesets_root=RULESETS_ROOT,
        escalation_threshold=threshold,
    )


class TestDeterministicCheckId:
    def test_stable_across_calls(self):
        a = deterministic_check_id("doc-1", "1.0.0")
        b = deterministic_check_id("doc-1", "1.0.0")
        assert a == b

    def test_differs_by_version(self):
        assert deterministic_check_id("doc-1", "1.0.0") != deterministic_check_id("doc-1", "2.0.0")


class TestComplianceReasoning:
    def test_critical_failure_forces_escalation(self, ndis_tenant):
        repo = FakeRepo(ndis_tenant, _processed_doc())
        # Gemini under-scores a critical failure at 10; reconciliation must floor to >=80.
        gemini = FakeGemini(
            [
                gemini_result(
                    {
                        "rule_verdicts": [
                            {
                                "rule_id": "consent_documentation",
                                "status": "fail",
                                "confidence": 0.98,
                                "explanation": "No consent record present.",
                                "triggering_data_point": "consent_record=null",
                            }
                        ],
                        "risk_score": 10,
                        "justification": "Mostly fine.",
                    }
                )
            ]
        )
        out = _run(repo, gemini, FakeAuditor())
        assert out.gemini_raw_risk_score == 10
        assert out.check.risk_score >= 80  # critical fail floor
        assert out.check.decision is CheckDecision.ESCALATED
        assert "consent_documentation" in out.check.citations

    def test_fabricated_citation_dropped(self, ndis_tenant):
        repo = FakeRepo(ndis_tenant, _processed_doc())
        gemini = FakeGemini(
            [
                gemini_result(
                    {
                        "rule_verdicts": [
                            {
                                "rule_id": "totally_made_up_rule",  # not in ruleset
                                "status": "fail",
                                "confidence": 0.9,
                                "explanation": "hallucinated",
                                "triggering_data_point": "x",
                            },
                            {
                                "rule_id": "consent_documentation",
                                "status": "pass",
                                "confidence": 0.9,
                                "explanation": "ok",
                                "triggering_data_point": "consent_record=CF-1",
                            },
                        ],
                        "risk_score": 30,
                        "justification": "Reviewed.",
                    }
                )
            ]
        )
        out = _run(repo, gemini, FakeAuditor())
        assert "totally_made_up_rule" in out.dropped_citations
        # dropped id never appears as a citation or verdict
        assert "totally_made_up_rule" not in out.check.citations
        assert all(v.rule_id != "totally_made_up_rule" for v in out.check.rule_verdicts)
        assert "unrecognized rule citation" in out.check.justification

    def test_missing_verdicts_injected_as_uncertain(self, ndis_tenant):
        repo = FakeRepo(ndis_tenant, _processed_doc())
        # Gemini returns only one of five rules.
        gemini = FakeGemini(
            [
                gemini_result(
                    {
                        "rule_verdicts": [
                            {
                                "rule_id": "consent_documentation",
                                "status": "pass",
                                "confidence": 0.9,
                                "explanation": "ok",
                                "triggering_data_point": "consent_record=CF-1",
                            }
                        ],
                        "risk_score": 5,
                        "justification": "Looks compliant.",
                    }
                )
            ]
        )
        out = _run(repo, gemini, FakeAuditor())
        # Every rule in the ruleset must be represented, no matter how many
        # rules the ruleset grows to — one answered, the rest injected.
        total = len(_all_ndis_rule_ids())
        assert len(out.check.rule_verdicts) == total
        injected = [v for v in out.check.rule_verdicts if v.confidence == 0.0]
        assert len(injected) == total - 1
        assert all(v.status is RuleVerdictStatus.UNCERTAIN for v in injected)

    def test_low_risk_auto_approved(self, ndis_tenant):
        repo = FakeRepo(ndis_tenant, _processed_doc())
        gemini = FakeGemini(
            [
                gemini_result(
                    {
                        "rule_verdicts": [
                            {"rule_id": r, "status": "pass", "confidence": 0.95,
                             "explanation": "ok", "triggering_data_point": "x"}
                            for r in _all_ndis_rule_ids()
                        ],
                        "risk_score": 8,
                        "justification": "All rules pass.",
                    }
                )
            ]
        )
        out = _run(repo, gemini, FakeAuditor())
        assert out.check.risk_score == 8
        assert out.check.decision is CheckDecision.AUTO_APPROVED
        assert out.check.citations == []  # nothing failed/uncertain

    def test_idempotent_check_id_on_reruns(self, ndis_tenant):
        repo = FakeRepo(ndis_tenant, _processed_doc())

        def fresh_gemini():
            return FakeGemini(
                [
                    gemini_result(
                        {
                            "rule_verdicts": [
                                {"rule_id": "consent_documentation", "status": "fail",
                                 "confidence": 0.9, "explanation": "no consent",
                                 "triggering_data_point": "consent_record=null"}
                            ],
                            "risk_score": 90,
                            "justification": "Critical issue.",
                        }
                    )
                ]
            )

        out1 = _run(repo, fresh_gemini(), FakeAuditor())
        out2 = _run(repo, fresh_gemini(), FakeAuditor())
        assert out1.check.check_id == out2.check.check_id  # redelivery-safe

    def test_check_before_processed_raises(self, ndis_tenant):
        pending = _processed_doc().model_copy(update={"status": DocumentStatus.PENDING})
        repo = FakeRepo(ndis_tenant, pending)
        from compliance_agent.checker import DocumentNotProcessedError

        with pytest.raises(DocumentNotProcessedError):
            _run(repo, FakeGemini([]), FakeAuditor())

    def test_gemini_failure_audited_and_raised(self, ndis_tenant):
        repo = FakeRepo(ndis_tenant, _processed_doc())

        class BoomGemini:
            def generate_json(self, **kwargs):
                raise RuntimeError("reasoning call failed")

        auditor = FakeAuditor()
        with pytest.raises(RuntimeError):
            _run(repo, BoomGemini(), auditor)
        assert any(e["action"] == "compliance.check_failed" for e in auditor.events)
