"""Unit tests: escalation decision logic + concurrency conflict handling.

The Firestore transaction's true atomicity is proven in the Phase 3 live demo
against the emulator (two concurrent PATCH -> one 200, one 409). Here we test
the decision + audit logic and the conflict branch with an in-memory fake that
reproduces the transaction's state guard.
"""

from __future__ import annotations

import pytest

from escalation_service.decisions import apply_decision
from gcp_clients.firestore_repo import DecisionConflictError
from schema_validators import CheckDecision, ComplianceCheck


def _escalated_check() -> ComplianceCheck:
    return ComplianceCheck(
        check_id="check-1",
        document_id="doc-1",
        tenant_id="tenant-a",
        rule_set_version="1.0.0",
        risk_score=85,
        justification="Critical consent failure.",
        citations=["consent_documentation"],
        decision=CheckDecision.ESCALATED,
        reviewer_id=None,
    )


class FakeDecisionRepo:
    """Reproduces the transactional state guard from FirestoreRepo."""

    def __init__(self, check: ComplianceCheck):
        self._checks = {check.check_id: check}

    def get_check(self, check_id, tenant_id):
        from gcp_clients.firestore_repo import NotFoundError, TenantMismatchError

        c = self._checks.get(check_id)
        if c is None:
            raise NotFoundError(check_id)
        if c.tenant_id != tenant_id:
            raise TenantMismatchError(check_id)
        return c

    def apply_reviewer_decision(self, *, check_id, tenant_id, reviewer_id, decision):
        c = self.get_check(check_id, tenant_id)
        if c.decision is not CheckDecision.ESCALATED or c.reviewer_id is not None:
            raise DecisionConflictError(check_id)
        updated = c.model_copy(update={"decision": decision, "reviewer_id": reviewer_id})
        self._checks[check_id] = updated
        return updated


class FakeAuditor:
    def __init__(self):
        self.events = []

    def log(self, **kwargs):
        self.events.append(kwargs)
        return kwargs


class TestApplyDecision:
    def test_approve_maps_to_auto_approved_and_audits(self):
        repo = FakeDecisionRepo(_escalated_check())
        auditor = FakeAuditor()
        result = apply_decision(
            repo=repo, auditor=auditor, check_id="check-1", tenant_id="tenant-a",
            reviewer_id="rev-9", approve=True,
        )
        assert result.check.decision is CheckDecision.AUTO_APPROVED
        assert result.check.reviewer_id == "rev-9"
        assert result.action == "check.approved"
        evt = auditor.events[-1]
        assert evt["actor"] == "rev-9"  # reviewer id recorded as actor
        assert evt["action"] == "check.approved"

    def test_reject_maps_to_rejected(self):
        repo = FakeDecisionRepo(_escalated_check())
        auditor = FakeAuditor()
        result = apply_decision(
            repo=repo, auditor=auditor, check_id="check-1", tenant_id="tenant-a",
            reviewer_id="rev-9", approve=False,
        )
        assert result.check.decision is CheckDecision.REJECTED
        assert result.action == "check.rejected"

    def test_second_reviewer_conflict(self):
        repo = FakeDecisionRepo(_escalated_check())
        auditor = FakeAuditor()
        # First reviewer wins.
        apply_decision(
            repo=repo, auditor=auditor, check_id="check-1", tenant_id="tenant-a",
            reviewer_id="rev-1", approve=True,
        )
        # Second reviewer loses the race -> conflict.
        with pytest.raises(DecisionConflictError):
            apply_decision(
                repo=repo, auditor=auditor, check_id="check-1", tenant_id="tenant-a",
                reviewer_id="rev-2", approve=False,
            )

    def test_cross_tenant_blocked(self):
        repo = FakeDecisionRepo(_escalated_check())
        from gcp_clients.firestore_repo import TenantMismatchError

        with pytest.raises(TenantMismatchError):
            apply_decision(
                repo=repo, auditor=FakeAuditor(), check_id="check-1",
                tenant_id="tenant-b", reviewer_id="rev-x", approve=True,
            )
