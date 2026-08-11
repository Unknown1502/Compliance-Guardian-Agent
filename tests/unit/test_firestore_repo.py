"""Unit tests: FirestoreRepo tenant enumeration (hermetic).

list_all_tenants feeds two unattended jobs — the retention sweep and the
weekly report's tenant list — so its behaviour when a single document is
malformed decides whether one bad record quietly stops work for everybody
else.
"""

from __future__ import annotations

import logging


class FakeSnap:
    def __init__(self, doc_id: str, data: dict):
        self.id = doc_id
        self._data = data

    def to_dict(self) -> dict:
        return self._data


class FakeCollection:
    def __init__(self, snaps: list[FakeSnap]):
        self._snaps = snaps
        self._limit = len(snaps)

    def limit(self, n: int) -> "FakeCollection":
        self._limit = n
        return self

    def stream(self):
        return iter(self._snaps[: self._limit])


class FakeDb:
    def __init__(self, snaps: list[FakeSnap]):
        self._snaps = snaps
        self.requested: list[str] = []

    def collection(self, name: str) -> FakeCollection:
        self.requested.append(name)
        return FakeCollection(self._snaps)


def _valid(tenant_id: str) -> dict:
    return {
        "tenant_id": tenant_id,
        "name": f"{tenant_id} Pty Ltd",
        "industry": "disability-services",
        "jurisdiction": "AU-NDIS",
    }


class TestListAllTenants:
    def test_returns_every_valid_tenant(self):
        from gcp_clients.firestore_repo import FirestoreRepo

        db = FakeDb([FakeSnap("t-1", _valid("t-1")), FakeSnap("t-2", _valid("t-2"))])
        assert [t.tenant_id for t in FirestoreRepo(db).list_all_tenants()] == [
            "t-1",
            "t-2",
        ]

    def test_unknown_field_does_not_hide_the_other_tenants(self):
        """Tenant forbids extra fields, so schema drift on one doc used to
        raise and take the entire list with it."""
        from gcp_clients.firestore_repo import FirestoreRepo

        drifted = _valid("t-drift") | {"field_from_a_future_version": True}
        db = FakeDb(
            [
                FakeSnap("t-1", _valid("t-1")),
                FakeSnap("t-drift", drifted),
                FakeSnap("t-2", _valid("t-2")),
            ]
        )
        assert [t.tenant_id for t in FirestoreRepo(db).list_all_tenants()] == [
            "t-1",
            "t-2",
        ]

    def test_missing_required_field_is_skipped(self):
        from gcp_clients.firestore_repo import FirestoreRepo

        db = FakeDb(
            [FakeSnap("t-broken", {"tenant_id": "t-broken"}), FakeSnap("t-1", _valid("t-1"))]
        )
        assert [t.tenant_id for t in FirestoreRepo(db).list_all_tenants()] == ["t-1"]

    def test_skipped_document_is_logged_with_its_id(self, caplog):
        """Skipping silently would trade a loud failure for an invisible one."""
        from gcp_clients.firestore_repo import FirestoreRepo

        db = FakeDb([FakeSnap("t-broken", {"tenant_id": "t-broken"})])
        with caplog.at_level(logging.ERROR, logger="cg.firestore_repo"):
            assert FirestoreRepo(db).list_all_tenants() == []
        assert "t-broken" in caplog.text

    def test_all_documents_malformed_yields_empty_not_an_exception(self):
        from gcp_clients.firestore_repo import FirestoreRepo

        db = FakeDb([FakeSnap("a", {}), FakeSnap("b", {})])
        assert FirestoreRepo(db).list_all_tenants() == []
