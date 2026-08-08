"""Unit tests: auth middleware — tenant isolation and role enforcement.

firebase_admin.auth.verify_id_token is monkeypatched at its documented
boundary; a minimal FastAPI app exercises the dependencies end to end.
"""

from __future__ import annotations

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

import auth_middleware
from auth_middleware import AuthContext, require_auth, require_role


@pytest.fixture()
def app_client(monkeypatch):
    """FastAPI test app with a patched token verifier."""

    tokens = {
        "owner-token": {
            "uid": "user-owner",
            "tenant_id": "tenant-a",
            "role": "owner",
            "email": "owner@a.example",
        },
        "reviewer-token": {
            "uid": "user-reviewer",
            "tenant_id": "tenant-a",
            "role": "reviewer",
            "email": "rev@a.example",
        },
        "admin-token": {
            "uid": "user-admin",
            "tenant_id": "tenant-a",
            "role": "admin",
            "email": "admin@a.example",
        },
        "no-tenant-token": {"uid": "user-x", "role": "owner"},
        "bad-role-token": {"uid": "user-y", "tenant_id": "tenant-a", "role": "superuser"},
    }

    def fake_verify(token, **kwargs):
        if token not in tokens:
            raise ValueError("invalid token")
        return tokens[token]

    monkeypatch.setattr(auth_middleware, "_ensure_firebase_app", lambda: None)
    monkeypatch.setattr(auth_middleware.fb_auth, "verify_id_token", fake_verify)

    app = FastAPI()

    @app.get("/whoami")
    def whoami(auth: AuthContext = Depends(require_auth)):
        return {"uid": auth.uid, "tenant_id": auth.tenant_id, "role": auth.role}

    @app.patch("/decide")
    def decide(auth: AuthContext = Depends(require_role("reviewer"))):
        return {"decided_by": auth.uid}

    return TestClient(app)


class TestRequireAuth:
    def test_missing_header_401(self, app_client):
        assert app_client.get("/whoami").status_code == 401

    def test_malformed_header_401(self, app_client):
        r = app_client.get("/whoami", headers={"Authorization": "Token abc"})
        assert r.status_code == 401

    def test_invalid_token_401(self, app_client):
        r = app_client.get("/whoami", headers={"Authorization": "Bearer forged"})
        assert r.status_code == 401

    def test_valid_token_returns_trusted_tenant(self, app_client):
        r = app_client.get("/whoami", headers={"Authorization": "Bearer owner-token"})
        assert r.status_code == 200
        assert r.json() == {"uid": "user-owner", "tenant_id": "tenant-a", "role": "owner"}

    def test_token_without_tenant_claim_403(self, app_client):
        r = app_client.get("/whoami", headers={"Authorization": "Bearer no-tenant-token"})
        assert r.status_code == 403

    def test_token_with_unknown_role_403(self, app_client):
        r = app_client.get("/whoami", headers={"Authorization": "Bearer bad-role-token"})
        assert r.status_code == 403


class TestRequireRole:
    def test_owner_cannot_review(self, app_client):
        r = app_client.patch("/decide", headers={"Authorization": "Bearer owner-token"})
        assert r.status_code == 403

    def test_reviewer_can_review(self, app_client):
        r = app_client.patch("/decide", headers={"Authorization": "Bearer reviewer-token"})
        assert r.status_code == 200
        assert r.json() == {"decided_by": "user-reviewer"}

    def test_admin_satisfies_any_role(self, app_client):
        r = app_client.patch("/decide", headers={"Authorization": "Bearer admin-token"})
        assert r.status_code == 200

    def test_unknown_role_in_factory_rejected(self):
        with pytest.raises(ValueError):
            require_role("wizard")


# ---------------------------------------------------------------------------
# Email verification enforcement
# ---------------------------------------------------------------------------


class _Req:
    """Minimal stand-in for a Starlette Request carrying only headers."""

    def __init__(self, token: str):
        self.headers = {"Authorization": f"Bearer {token}"}


class TestEmailVerification:
    def _verify(self, monkeypatch, *, claims: dict, required: bool):
        import auth_middleware as am

        monkeypatch.delenv("CG_AUTH_DEV_MODE", raising=False)
        monkeypatch.setenv("CG_REQUIRE_EMAIL_VERIFICATION", "1" if required else "0")
        monkeypatch.setattr(am, "_ensure_firebase_app", lambda: None)
        monkeypatch.setattr(am.fb_auth, "verify_id_token", lambda _t: claims)
        return am._verify_bearer_token(_Req("real-token"))

    BASE = {"uid": "u1", "tenant_id": "tenant-a", "role": "owner", "email": "a@b.example"}

    def test_unverified_allowed_when_enforcement_is_off(self, monkeypatch):
        """Default off: enabling it retroactively would lock out existing accounts."""
        ctx = self._verify(
            monkeypatch, claims={**self.BASE, "email_verified": False}, required=False
        )
        assert ctx.tenant_id == "tenant-a"
        assert ctx.email_verified is False

    def test_unverified_refused_when_enforcement_is_on(self, monkeypatch):
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            self._verify(
                monkeypatch, claims={**self.BASE, "email_verified": False}, required=True
            )
        # 403, not 401: the credential is valid, the account is unconfirmed.
        assert exc.value.status_code == 403
        assert "not verified" in exc.value.detail.lower()

    def test_verified_allowed_when_enforcement_is_on(self, monkeypatch):
        ctx = self._verify(
            monkeypatch, claims={**self.BASE, "email_verified": True}, required=True
        )
        assert ctx.email_verified is True
        assert ctx.uid == "u1"

    def test_missing_claim_counts_as_unverified(self, monkeypatch):
        """A token with no email_verified claim must not be treated as verified."""
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            self._verify(monkeypatch, claims=dict(self.BASE), required=True)
        assert exc.value.status_code == 403

    def test_api_key_context_defaults_to_verified(self):
        """A machine credential has no inbox, so it is not a failed verification."""
        from auth_middleware import AuthContext

        ctx = AuthContext(uid="api_key:k1", tenant_id="tenant-a", role="owner")
        assert ctx.email_verified is True
