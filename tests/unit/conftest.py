"""Shared fakes for agent unit tests (hermetic — no emulators, no network)."""

from __future__ import annotations

from pathlib import Path

import pytest

from gemini_client import GeminiResult
from schema_validators import Document, DocumentStatus, Tenant

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
RULESETS_ROOT = str(REPO_ROOT / "rulesets")


class FakeGemini:
    """Returns queued GeminiResults; records prompts it was called with."""

    def __init__(self, results: list[GeminiResult]):
        self._results = list(results)
        self.calls: list[dict] = []

    def generate_json(self, **kwargs) -> GeminiResult:
        self.calls.append(kwargs)
        if not self._results:
            raise AssertionError("FakeGemini ran out of queued results")
        return self._results.pop(0)


def gemini_result(data: dict, prompt_version: str = "test_v1") -> GeminiResult:
    return GeminiResult(
        data=data,
        prompt_version=prompt_version,
        model_name="gemini-2.5-flash",
        model_version="gemini-2.5-flash-test",
        response_id="resp-test-1",
        raw_text="{}",
        attempts=1,
    )


class FakeRepo:
    """In-memory FirestoreRepo stand-in with tenant-scoping semantics."""

    def __init__(self, tenant: Tenant, document: Document):
        self._tenants = {tenant.tenant_id: tenant}
        self._documents = {document.document_id: document}
        self._checks: dict = {}

    def get_tenant(self, tenant_id: str) -> Tenant:
        if tenant_id not in self._tenants:
            from gcp_clients.firestore_repo import NotFoundError

            raise NotFoundError(tenant_id)
        return self._tenants[tenant_id]

    def get_document(self, document_id: str, tenant_id: str) -> Document:
        from gcp_clients.firestore_repo import NotFoundError, TenantMismatchError

        if document_id not in self._documents:
            raise NotFoundError(document_id)
        doc = self._documents[document_id]
        if doc.tenant_id != tenant_id:
            raise TenantMismatchError(document_id)
        return doc

    def upsert_document(self, document: Document) -> None:
        self._documents[document.document_id] = document

    def update_document_fields(self, document_id, tenant_id, updates) -> Document:
        doc = self.get_document(document_id, tenant_id)
        patched = doc.model_copy(update=updates)
        self._documents[document_id] = patched
        return patched

    def upsert_check(self, check) -> None:
        self._checks[check.check_id] = check

    def get_check(self, check_id, tenant_id):
        return self._checks.get(check_id)


class FakeBlob:
    def __init__(self, data: bytes):
        self._data = data

    def download_as_bytes(self) -> bytes:
        return self._data


class FakeBucket:
    def __init__(self, data: bytes):
        self._data = data

    def blob(self, _path: str) -> FakeBlob:
        return FakeBlob(self._data)


class FakeStorage:
    def __init__(self, data: bytes):
        self._data = data

    def bucket(self, _name: str) -> FakeBucket:
        return FakeBucket(self._data)


class FakeAuditor:
    def __init__(self):
        self.events: list[dict] = []

    def log(self, **kwargs):
        self.events.append(kwargs)
        return kwargs


@pytest.fixture()
def ndis_tenant() -> Tenant:
    return Tenant(
        tenant_id="tenant-sunrise-care",
        name="Sunrise Community Care Pty Ltd",
        industry="healthcare_ndis",
        jurisdiction="AU",
        plan_tier="starter",
    )


@pytest.fixture()
def ndis_document() -> Document:
    return Document(
        document_id="doc-ndis-1",
        tenant_id="tenant-sunrise-care",
        source="upload",
        storage_ref="gs://cg-local-cg-raw-docs/tenant-sunrise-care/doc-ndis-1/record.txt",
        extracted_fields={},
        status=DocumentStatus.PENDING,
    )
