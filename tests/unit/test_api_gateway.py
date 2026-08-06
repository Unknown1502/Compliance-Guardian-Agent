"""Unit tests: API Gateway routes — RBAC, tenant scoping, decision conflict.

Uses the local dev-auth mode (CG_AUTH_DEV_MODE=1) with base64 claim tokens and a
FakeGateway injected in place of real GCP clients. No emulators, no network.
"""

from __future__ import annotations

import base64
import json

import pytest
from fastapi.testclient import TestClient

from schema_validators import CheckDecision, ComplianceCheck, Document, DocumentStatus


def _dev_token(uid: str, tenant_id: str, role: str) -> str:
    claims = {"uid": uid, "tenant_id": tenant_id, "role": role}
    raw = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return f"dev:{raw}"


class FakeRepo:
    def __init__(self):
        self.tenants = {}
        self.users = {}
        self.docs = {
            "doc-a": Document(
                document_id="doc-a", tenant_id="tenant-a", source="upload",
                storage_ref="gs://b/doc-a/x.txt", extracted_fields={"k": "v"},
                status=DocumentStatus.PROCESSED,
            )
        }
        self.checks = {
            "check-a": ComplianceCheck(
                check_id="check-a", document_id="doc-a", tenant_id="tenant-a",
                rule_set_version="1.0.0", risk_score=85, justification="Needs review.",
                citations=["consent_documentation"], decision=CheckDecision.ESCALATED,
                reviewer_id=None,
            )
        }

    def upsert_user(self, user):
        self.users[user.uid] = user

    def list_users(self, tenant_id, limit=100):
        return [u for u in self.users.values() if u.tenant_id == tenant_id]

    def get_user(self, uid, tenant_id):
        from gcp_clients.firestore_repo import NotFoundError, TenantMismatchError

        u = self.users.get(uid)
        if u is None:
            raise NotFoundError(uid)
        if u.tenant_id != tenant_id:
            raise TenantMismatchError(uid)
        return u

    def delete_user(self, uid, tenant_id):
        self.get_user(uid, tenant_id)
        del self.users[uid]

    def get_document(self, document_id, tenant_id):
        from gcp_clients.firestore_repo import NotFoundError, TenantMismatchError

        d = self.docs.get(document_id)
        if d is None:
            raise NotFoundError(document_id)
        if d.tenant_id != tenant_id:
            raise TenantMismatchError(document_id)
        return d

    def get_check(self, check_id, tenant_id):
        from gcp_clients.firestore_repo import NotFoundError, TenantMismatchError

        c = self.checks.get(check_id)
        if c is None:
            raise NotFoundError(check_id)
        if c.tenant_id != tenant_id:
            raise TenantMismatchError(check_id)
        return c

    def apply_reviewer_decision(self, *, check_id, tenant_id, reviewer_id, decision):
        from gcp_clients.firestore_repo import DecisionConflictError

        c = self.get_check(check_id, tenant_id)
        if c.decision is not CheckDecision.ESCALATED or c.reviewer_id is not None:
            raise DecisionConflictError(check_id)
        updated = c.model_copy(update={"decision": decision, "reviewer_id": reviewer_id})
        self.checks[check_id] = updated
        return updated

    def upsert_tenant(self, tenant) -> None:
        self.tenants[tenant.tenant_id] = tenant


class FakeAuditor:
    def __init__(self):
        self.events = []

    def log(self, **kwargs):
        self.events.append(kwargs)
        return kwargs


class FakeGateway:
    def __init__(self):
        self.repo = FakeRepo()
        self.auditor = FakeAuditor()


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("CG_AUTH_DEV_MODE", "1")
    import api_gateway.main as main
    import auth_middleware

    monkeypatch.setattr(auth_middleware, "_ensure_firebase_app", lambda: None)
    fake = FakeGateway()
    monkeypatch.setattr(main, "_gateway", fake)
    monkeypatch.setattr(main, "gw", lambda: fake)
    return TestClient(main.app), fake


class TestAuthAndRbac:
    def test_unauthenticated_rejected(self, client):
        c, _ = client
        assert c.get("/api/documents/doc-a").status_code == 401

    def test_get_document_tenant_scoped(self, client):
        c, _ = client
        ok = c.get("/api/documents/doc-a", headers={"Authorization": f"Bearer {_dev_token('u1','tenant-a','owner')}"})
        assert ok.status_code == 200
        assert ok.json()["document_id"] == "doc-a"

    def test_cross_tenant_document_is_404(self, client):
        c, _ = client
        r = c.get("/api/documents/doc-a", headers={"Authorization": f"Bearer {_dev_token('u2','tenant-b','owner')}"})
        assert r.status_code == 404  # not leaked as 403

    def test_owner_cannot_decide(self, client):
        c, _ = client
        r = c.patch(
            "/api/compliance/checks/check-a",
            json={"action": "approve"},
            headers={"Authorization": f"Bearer {_dev_token('u1','tenant-a','owner')}"},
        )
        assert r.status_code == 403

    def test_reviewer_can_approve(self, client):
        c, fake = client
        r = c.patch(
            "/api/compliance/checks/check-a",
            json={"action": "approve"},
            headers={"Authorization": f"Bearer {_dev_token('rev1','tenant-a','reviewer')}"},
        )
        assert r.status_code == 200
        assert r.json()["decision"] == "auto_approved"
        assert r.json()["reviewer_id"] == "rev1"
        assert any(e["action"] == "check.approved" for e in fake.auditor.events)

    def test_second_reviewer_gets_409(self, client):
        c, _ = client
        hdr = {"Authorization": f"Bearer {_dev_token('rev1','tenant-a','reviewer')}"}
        assert c.patch("/api/compliance/checks/check-a", json={"action": "approve"}, headers=hdr).status_code == 200
        hdr2 = {"Authorization": f"Bearer {_dev_token('rev2','tenant-a','reviewer')}"}
        r = c.patch("/api/compliance/checks/check-a", json={"action": "reject"}, headers=hdr2)
        assert r.status_code == 409

    def test_reports_endpoint_requires_auth(self, client):
        """POST /api/reports is now live (Phase 4) and must require auth."""
        c, _ = client
        r = c.post("/api/reports", json={"period_start": "2026-06-01T00:00:00Z", "period_end": "2026-07-01T00:00:00Z"})
        assert r.status_code == 401


class TestSignup:
    """POST /api/signup — the only public write endpoint (it creates the tenant)."""

    def _payload(self, **overrides):
        payload = {
            "email": "owner@sunrisecare.example",
            "password": "correct-horse-battery-staple",
            "business_name": "Sunrise Community Care Pty Ltd",
            "industry": "healthcare_ndis",
            "jurisdiction": "AU",
        }
        payload.update(overrides)
        return payload

    def test_signup_creates_tenant_and_owner(self, client, monkeypatch):
        c, fake = client
        import api_gateway.main as main

        monkeypatch.setattr(main, "create_tenant_owner", lambda **kw: "uid-new-owner")

        r = c.post("/api/signup", json=self._payload())
        assert r.status_code == 201
        body = r.json()
        assert body["uid"] == "uid-new-owner"
        assert body["tenant_id"].startswith("tenant-")
        assert body["tenant_id"] in fake.repo.tenants
        assert fake.repo.tenants[body["tenant_id"]].name == "Sunrise Community Care Pty Ltd"
        assert any(e["action"] == "tenant.signed_up" for e in fake.auditor.events)

    def test_signup_no_auth_required(self, client, monkeypatch):
        c, _ = client
        import api_gateway.main as main

        monkeypatch.setattr(main, "create_tenant_owner", lambda **kw: "uid-x")
        r = c.post("/api/signup", json=self._payload())  # no Authorization header
        assert r.status_code == 201

    def test_signup_rejects_unknown_ruleset(self, client):
        c, _ = client
        r = c.post("/api/signup", json=self._payload(industry="astrology", jurisdiction="ZZ"))
        assert r.status_code == 400

    def test_signup_duplicate_email_is_409(self, client, monkeypatch):
        c, _ = client
        import api_gateway.main as main
        from firebase_admin.auth import EmailAlreadyExistsError

        def _raise(**kw):
            raise EmailAlreadyExistsError("email already exists", None, None)

        monkeypatch.setattr(main, "create_tenant_owner", _raise)
        r = c.post("/api/signup", json=self._payload())
        assert r.status_code == 409

    def test_signup_short_password_rejected(self, client):
        c, _ = client
        r = c.post("/api/signup", json=self._payload(password="short"))
        assert r.status_code == 422  # pydantic min_length validation


class TestTeam:
    """Team roster: /api/team. Roster reads are open to any member; roster
    mutations are owner/admin only and must never cross a tenant boundary."""

    def _seed(self, fake, uid="u-existing", tenant="tenant-a", role="reviewer"):
        from schema_validators import TenantUser

        fake.repo.upsert_user(
            TenantUser(
                uid=uid,
                tenant_id=tenant,
                email=f"{uid}@example.com",
                role=role,
                job_title="Compliance Manager",
            )
        )

    def test_signup_records_job_title(self, client, monkeypatch):
        c, fake = client
        import api_gateway.main as main

        monkeypatch.setattr(main, "create_tenant_owner", lambda **kw: "uid-owner-1")
        r = c.post(
            "/api/signup",
            json={
                "email": "owner@x.example",
                "password": "correct-horse-battery-staple",
                "business_name": "X Pty Ltd",
                "job_title": "Director of Operations",
            },
        )
        assert r.status_code == 201
        stored = fake.repo.users["uid-owner-1"]
        assert stored.job_title == "Director of Operations"
        assert stored.role == "owner"

    def test_list_team_is_tenant_scoped(self, client):
        c, fake = client
        self._seed(fake, uid="u-mine", tenant="tenant-a")
        self._seed(fake, uid="u-theirs", tenant="tenant-b")

        r = c.get(
            "/api/team",
            headers={"Authorization": f"Bearer {_dev_token('u1','tenant-a','owner')}"},
        )
        assert r.status_code == 200
        uids = {m["uid"] for m in r.json()}
        assert uids == {"u-mine"}

    def test_reviewer_cannot_add_member(self, client):
        c, _ = client
        r = c.post(
            "/api/team",
            headers={"Authorization": f"Bearer {_dev_token('u1','tenant-a','reviewer')}"},
            json={"email": "new@x.example", "password": "hunter2hunter2", "role": "reviewer"},
        )
        assert r.status_code == 403

    def test_owner_adds_member_with_role_and_title(self, client, monkeypatch):
        c, fake = client
        import api_gateway.main as main

        monkeypatch.setattr(main, "create_tenant_member", lambda **kw: "uid-new-member")
        r = c.post(
            "/api/team",
            headers={"Authorization": f"Bearer {_dev_token('u1','tenant-a','owner')}"},
            json={
                "email": "reviewer@x.example",
                "password": "hunter2hunter2",
                "role": "reviewer",
                "job_title": "Quality Lead",
            },
        )
        assert r.status_code == 201, r.text
        assert r.json()["job_title"] == "Quality Lead"
        assert fake.repo.users["uid-new-member"].tenant_id == "tenant-a"

    def test_invalid_role_rejected(self, client):
        c, _ = client
        r = c.post(
            "/api/team",
            headers={"Authorization": f"Bearer {_dev_token('u1','tenant-a','owner')}"},
            json={"email": "x@x.example", "password": "hunter2hunter2", "role": "superuser"},
        )
        assert r.status_code == 400

    def test_cannot_remove_self(self, client):
        c, _ = client
        r = c.delete(
            "/api/team/u1",
            headers={"Authorization": f"Bearer {_dev_token('u1','tenant-a','owner')}"},
        )
        assert r.status_code == 400

    def test_cannot_remove_user_from_other_tenant(self, client, monkeypatch):
        c, fake = client
        import api_gateway.main as main

        self._seed(fake, uid="u-theirs", tenant="tenant-b")
        monkeypatch.setattr(main, "delete_tenant_member", lambda **kw: None)
        r = c.delete(
            "/api/team/u-theirs",
            headers={"Authorization": f"Bearer {_dev_token('u1','tenant-a','owner')}"},
        )
        assert r.status_code == 404
        # The cross-tenant user must still exist.
        assert "u-theirs" in fake.repo.users


class TestApiKeyAuth:
    """X-API-Key is an alternative credential, so it must carry exactly the
    same tenant-isolation guarantees as the Firebase JWT path."""

    def _register(self, monkeypatch, record):
        """Point auth_middleware at an in-memory key store."""
        import auth_middleware
        from api_keys import hash_api_key, looks_like_api_key

        def resolve(plaintext):
            if not looks_like_api_key(plaintext):
                return None
            if record is None or hash_api_key(plaintext) != record["key_hash"]:
                return None
            if record.get("revoked"):
                return None
            return auth_middleware.AuthContext(
                uid=f"api_key:{record['key_id']}",
                tenant_id=record["tenant_id"],
                role="owner",
            )

        auth_middleware.set_api_key_resolver(resolve)
        monkeypatch.setattr(
            auth_middleware, "_api_key_resolver", resolve, raising=False
        )

    def test_valid_key_authenticates(self, client, monkeypatch):
        from api_keys import generate_api_key

        c, _ = client
        g = generate_api_key()
        self._register(
            monkeypatch,
            {"key_id": "k1", "tenant_id": "tenant-a", "key_hash": g.key_hash},
        )
        r = c.get("/api/documents/doc-a", headers={"X-API-Key": g.plaintext})
        assert r.status_code == 200

    def test_key_is_scoped_to_its_own_tenant(self, client, monkeypatch):
        from api_keys import generate_api_key

        c, _ = client
        g = generate_api_key()
        # Key belongs to tenant-b; doc-a belongs to tenant-a.
        self._register(
            monkeypatch,
            {"key_id": "k1", "tenant_id": "tenant-b", "key_hash": g.key_hash},
        )
        r = c.get("/api/documents/doc-a", headers={"X-API-Key": g.plaintext})
        assert r.status_code == 404  # not found, not leaked

    def test_invalid_key_rejected(self, client, monkeypatch):
        from api_keys import generate_api_key

        c, _ = client
        real = generate_api_key()
        self._register(
            monkeypatch,
            {"key_id": "k1", "tenant_id": "tenant-a", "key_hash": real.key_hash},
        )
        r = c.get(
            "/api/documents/doc-a",
            headers={"X-API-Key": generate_api_key().plaintext},
        )
        assert r.status_code == 401

    def test_revoked_key_rejected(self, client, monkeypatch):
        from api_keys import generate_api_key

        c, _ = client
        g = generate_api_key()
        self._register(
            monkeypatch,
            {
                "key_id": "k1",
                "tenant_id": "tenant-a",
                "key_hash": g.key_hash,
                "revoked": True,
            },
        )
        r = c.get("/api/documents/doc-a", headers={"X-API-Key": g.plaintext})
        assert r.status_code == 401

    def test_malformed_key_rejected(self, client, monkeypatch):
        c, _ = client
        self._register(monkeypatch, None)
        r = c.get("/api/documents/doc-a", headers={"X-API-Key": "totally-bogus"})
        assert r.status_code == 401

    def test_no_credential_still_401(self, client, monkeypatch):
        c, _ = client
        self._register(monkeypatch, None)
        assert c.get("/api/documents/doc-a").status_code == 401
