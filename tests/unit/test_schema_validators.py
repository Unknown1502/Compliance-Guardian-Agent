"""Unit tests: schema validators (models + ruleset loading).

These tests are pure — no emulators, no network. They pin the exact data
model from the spec so schema drift fails CI immediately.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from schema_validators import (
    AuditLogRow,
    CheckDecision,
    ComplianceCheck,
    Document,
    DocumentStatus,
    GeminiCallMetadata,
    ReportRow,
    RuleVerdict,
    RuleVerdictStatus,
    Tenant,
    load_ruleset,
    load_ruleset_file,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
RULESETS = REPO_ROOT / "rulesets"


# ---------------------------------------------------------------------------
# Entity models — exact spec fields
# ---------------------------------------------------------------------------


class TestTenant:
    def test_valid_tenant(self):
        t = Tenant(
            tenant_id="t1",
            name="Acme",
            industry="bookkeeping",
            jurisdiction="au",
            plan_tier="pro",
        )
        assert t.plan_tier.value == "pro"
        assert t.created_at.tzinfo is not None  # aware timestamp

    def test_rejects_unknown_fields(self):
        with pytest.raises(ValidationError):
            Tenant(
                tenant_id="t1",
                name="Acme",
                industry="x",
                jurisdiction="au",
                surprise_field="nope",
            )

    def test_rejects_bad_plan_tier(self):
        with pytest.raises(ValidationError):
            Tenant(tenant_id="t1", name="A", industry="x", jurisdiction="au", plan_tier="platinum")


class TestDocument:
    def test_defaults(self):
        d = Document(
            document_id="d1",
            tenant_id="t1",
            source="upload",
            storage_ref="gs://bucket/t1/d1/file.pdf",
        )
        assert d.status is DocumentStatus.PENDING
        assert d.extracted_fields == {}

    def test_status_enum_enforced(self):
        with pytest.raises(ValidationError):
            Document(
                document_id="d1",
                tenant_id="t1",
                source="upload",
                storage_ref="gs://b/x",
                status="in_review",  # not a spec status
            )


class TestComplianceCheck:
    def _base(self, **overrides):
        kwargs = dict(
            check_id="c1",
            document_id="d1",
            tenant_id="t1",
            rule_set_version="1.0.0",
            risk_score=42,
            justification="Two of five rules failed.",
            citations=["consent_documentation"],
            decision=CheckDecision.ESCALATED,
        )
        kwargs.update(overrides)
        return ComplianceCheck(**kwargs)

    def test_valid_check_with_verdicts_and_metadata(self):
        c = self._base(
            rule_verdicts=[
                RuleVerdict(
                    rule_id="consent_documentation",
                    status=RuleVerdictStatus.FAIL,
                    confidence=0.93,
                    explanation="No consent record found.",
                    triggering_data_point="consent_record=null",
                )
            ],
            gemini_metadata=GeminiCallMetadata(
                prompt_version="compliance_v1", model_name="gemini-2.5-flash"
            ),
        )
        assert c.decision is CheckDecision.ESCALATED
        assert c.reviewer_id is None
        assert c.gemini_metadata.prompt_version == "compliance_v1"

    def test_risk_score_bounds(self):
        with pytest.raises(ValidationError):
            self._base(risk_score=101)
        with pytest.raises(ValidationError):
            self._base(risk_score=-1)

    def test_blank_citation_rejected(self):
        with pytest.raises(ValidationError):
            self._base(citations=["  "])

    def test_confidence_bounds(self):
        with pytest.raises(ValidationError):
            RuleVerdict(
                rule_id="r",
                status=RuleVerdictStatus.PASS,
                confidence=1.5,
                explanation="x",
            )

    def test_non_string_trigger_coerced(self):
        v = RuleVerdict(
            rule_id="r",
            status=RuleVerdictStatus.FAIL,
            confidence=0.5,
            explanation="numeric trigger",
            triggering_data_point=82.5,
        )
        assert v.triggering_data_point == "82.5"


class TestAuditAndReportRows:
    def test_audit_row(self):
        r = AuditLogRow(
            event_id="e1",
            tenant_id="t1",
            actor="ingestion-agent",
            action="document.ingested",
            before_state=None,
            after_state={"status": "processed"},
        )
        assert r.before_state is None

    def test_report_row(self):
        r = ReportRow(
            report_id="r1",
            tenant_id="t1",
            period_start=datetime(2026, 6, 1, tzinfo=timezone.utc),
            period_end=datetime(2026, 7, 1, tzinfo=timezone.utc),
            generated_by="reporting-agent@reporting_v1",
            content_ref="gs://reports/t1/r1.html",
        )
        assert r.period_end > r.period_start


# ---------------------------------------------------------------------------
# Ruleset loading — the three seeded YAML files must all validate
# ---------------------------------------------------------------------------


class TestRulesets:
    @pytest.mark.parametrize(
        "rel_path,industry,version,rule_count",
        [
            ("healthcare_ndis/au.yaml", "healthcare_ndis", "1.0.0", 5),
            ("contract_review/generic.yaml", "contract_review", "1.0.0", 6),
            ("bookkeeping/au.yaml", "bookkeeping", "1.0.0", 5),
        ],
    )
    def test_seeded_rulesets_valid(self, rel_path, industry, version, rule_count):
        rs = load_ruleset_file(RULESETS / rel_path)
        assert rs.industry == industry
        assert rs.rule_set_version == version
        assert len(rs.rules) == rule_count
        assert rs.required_fields  # every seeded ruleset declares required fields

    def test_load_by_industry_jurisdiction_case_insensitive(self):
        rs = load_ruleset(RULESETS, "healthcare_ndis", "AU")
        assert rs.jurisdiction == "AU"

    def test_missing_ruleset_raises(self):
        from schema_validators.rulesets import RulesetNotFoundError

        with pytest.raises(RulesetNotFoundError):
            load_ruleset(RULESETS, "aviation", "mars")

    def test_path_traversal_blocked(self):
        with pytest.raises(ValueError):
            load_ruleset(RULESETS, "../secrets", "au")

    def test_bad_semver_rejected(self, tmp_path):
        bad = tmp_path / "x.yaml"
        bad.write_text(
            "rule_set_version: 'v1'\n"
            "industry: x\n"
            "jurisdiction: y\n"
            "rules:\n"
            "  - id: r1\n"
            "    description: d\n"
            "    check_type: field_presence\n"
            "    severity: low\n",
            encoding="utf-8",
        )
        with pytest.raises(ValidationError):
            load_ruleset_file(bad)

    def test_duplicate_rule_ids_rejected(self, tmp_path):
        dup = tmp_path / "dup.yaml"
        dup.write_text(
            "rule_set_version: '1.0.0'\n"
            "industry: x\n"
            "jurisdiction: y\n"
            "rules:\n"
            "  - id: r1\n"
            "    description: a\n"
            "    check_type: field_presence\n"
            "    severity: low\n"
            "  - id: r1\n"
            "    description: b\n"
            "    check_type: field_presence\n"
            "    severity: high\n",
            encoding="utf-8",
        )
        with pytest.raises(ValidationError):
            load_ruleset_file(dup)
