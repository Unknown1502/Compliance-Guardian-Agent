"""A cross-tenant read must not reveal whether the record exists.

Tenant ownership is checked before the record is validated. If it were the
other way round, a *malformed* record belonging to another tenant would raise
ValidationError and surface as 500, while a record that simply is not there
surfaces as 404 — and the difference tells an unauthorised caller which ids
are real.

This is not theoretical for this codebase: a seeder wrote one unexpected field
into production records and every affected read 500'd. The same shape of bug
would have been an enumeration oracle for anyone probing another tenant.
"""

from __future__ import annotations

import pytest

from gcp_clients.firestore_repo import (
    FirestoreRepo,
    NotFoundError,
    TenantMismatchError,
)


class FakeSnap:
    def __init__(self, data, exists=True):
        self._data = data
        self.exists = exists
        self.id = "rec-1"

    def to_dict(self):
        return self._data


class FakeDocRef:
    def __init__(self, snap):
        self._snap = snap

    def get(self, transaction=None):
        return self._snap


class FakeCollection:
    def __init__(self, snap):
        self._snap = snap

    def document(self, _id):
        return FakeDocRef(self._snap)


class FakeDb:
    def __init__(self, snap):
        self._snap = snap

    def collection(self, _name):
        return FakeCollection(self._snap)


# A record that belongs to someone else AND cannot be validated — the exact
# combination that used to produce a 500.
MALFORMED_OTHER_TENANT = {
    "check_id": "chk-1",
    "tenant_id": "tenant-b",
    "surprise_field": True,
}

WELL_FORMED_OTHER_TENANT = {
    "check_id": "chk-1",
    "document_id": "doc-1",
    "tenant_id": "tenant-b",
    "rule_set_version": "1.0.0",
    "risk_score": 10,
    "justification": "x",
    "citations": [],
    "decision": "auto_approved",
    "rule_verdicts": [],
}

GETTERS = [
    ("get_check", "compliance_checks"),
    ("get_document", "documents"),
    ("get_task", "tasks"),
    ("get_user", "users"),
]


def _repo(data, exists=True) -> FirestoreRepo:
    return FirestoreRepo(FakeDb(FakeSnap(data, exists=exists)))


class TestCrossTenantReadsAreIndistinguishable:
    @pytest.mark.parametrize("method,_coll", GETTERS, ids=[m for m, _ in GETTERS])
    def test_malformed_foreign_record_is_refused_not_crashed(self, method, _coll):
        """The regression: this used to raise ValidationError → 500."""
        repo = _repo(MALFORMED_OTHER_TENANT)
        with pytest.raises(TenantMismatchError):
            getattr(repo, method)("rec-1", "tenant-a")

    @pytest.mark.parametrize("method,_coll", GETTERS, ids=[m for m, _ in GETTERS])
    def test_missing_record_is_not_found(self, method, _coll):
        repo = _repo(None, exists=False)
        with pytest.raises(NotFoundError):
            getattr(repo, method)("rec-1", "tenant-a")

    def test_well_formed_foreign_record_is_also_refused(self):
        repo = _repo(WELL_FORMED_OTHER_TENANT)
        with pytest.raises(TenantMismatchError):
            repo.get_check("chk-1", "tenant-a")

    def test_both_refusals_reach_the_client_as_the_same_status(self):
        """The gateway maps TenantMismatchError and NotFoundError alike to 404.

        Asserted here rather than assumed: the repo distinction only stays
        invisible if every handler keeps collapsing it.
        """
        import inspect

        import api_gateway.main as main

        src = inspect.getsource(main)
        # Every TenantMismatchError handler in the gateway answers 404.
        for block in src.split("except TenantMismatchError")[1:]:
            head = block[:400]
            assert "HTTP_404_NOT_FOUND" in head, (
                "a TenantMismatchError handler answers something other than 404, "
                "which reintroduces the existence oracle"
            )


class TestTheGuardItself:
    """apply_reviewer_decision runs inside @firestore.transactional, which needs
    a real transaction to drive. Its guard is the same helper, so that is what
    is tested — and a test asserts the call site still uses it."""

    def test_helper_refuses_a_foreign_record_before_validating(self):
        from gcp_clients.firestore_repo import _own_or_raise

        with pytest.raises(TenantMismatchError):
            _own_or_raise(FakeSnap(MALFORMED_OTHER_TENANT), "tenant-a", "check chk-1")

    def test_helper_reports_a_missing_record_as_not_found(self):
        from gcp_clients.firestore_repo import _own_or_raise

        with pytest.raises(NotFoundError):
            _own_or_raise(FakeSnap(None, exists=False), "tenant-a", "check chk-1")

    def test_helper_returns_the_raw_dict_for_an_owned_record(self):
        from gcp_clients.firestore_repo import _own_or_raise

        owned = dict(WELL_FORMED_OTHER_TENANT, tenant_id="tenant-a")
        assert _own_or_raise(FakeSnap(owned), "tenant-a", "x") == owned

    def test_the_decision_transaction_still_uses_the_guard(self):
        """Guards rot when someone inlines them back. This fails if the
        ownership check inside the transaction stops running first."""
        import inspect

        from gcp_clients import firestore_repo

        src = inspect.getsource(firestore_repo.FirestoreRepo.apply_reviewer_decision)
        assert "_own_or_raise" in src
        # Ownership is settled before anything reads the record's own fields —
        # otherwise the conflict check leaks state about a foreign check.
        assert src.index("_own_or_raise") < src.index("if current.decision")
