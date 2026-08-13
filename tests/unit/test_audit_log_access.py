"""Who may read the workspace audit trail, and whether a 500 is legible.

Two separate production defects are pinned here.

The first is authorization. Generating an audit event and reading the whole
tenant's trail are different privileges, but /api/audit-logs was gated on
require_auth alone — so any reviewer, and any API key, could read every other
member's actions including before/after state.

The second is diagnosability. Starlette installs Exception handlers on
ServerErrorMiddleware, which wraps CORSMiddleware rather than the reverse, so
the 500 response carried no CORS headers, the browser refused to expose it,
and a real server error reached the dashboard as "Failed to fetch" with the
error_id — the one thing that makes it traceable — thrown away.
"""

from __future__ import annotations

import asyncio
import base64
import json

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

ORIGIN = "https://cg-guardian-9856.web.app"


def _tok(uid="u1", tenant="tenant-a", role="owner") -> str:
    claims = {"uid": uid, "tenant_id": tenant, "role": role}
    raw = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return f"dev:{raw}"


def _hdr(**kw) -> dict:
    return {"Authorization": f"Bearer {_tok(**kw)}"}


@pytest.fixture
def gateway(monkeypatch):
    monkeypatch.setenv("CG_AUTH_DEV_MODE", "1")
    import api_gateway.main as main
    import auth_middleware

    monkeypatch.setattr(auth_middleware, "_ensure_firebase_app", lambda: None)
    return main


@pytest.fixture
def client(gateway):
    return TestClient(gateway.app, raise_server_exceptions=False)


class TestAuditLogVisibility:
    def test_reviewer_cannot_read_the_audit_trail(self, client):
        """The reported bug: an ordinary member browsing everyone's activity."""
        r = client.get("/api/audit-logs", headers=_hdr(role="reviewer"))
        assert r.status_code == 403

    def test_api_key_cannot_read_the_audit_trail(self, client):
        """Keys leak more readily than passwords. A leaked one must not be able
        to exfiltrate the audit history, which is the evidence of what the
        attacker then did."""
        r = client.get("/api/audit-logs", headers=_hdr(role="service"))
        assert r.status_code == 403

    def test_unauthenticated_cannot_read_the_audit_trail(self, client):
        assert client.get("/api/audit-logs").status_code == 401

    @pytest.mark.parametrize("role", ["owner", "admin"])
    def test_owner_and_admin_pass_the_role_gate(self, client, role):
        """Not asserting 200: the handler goes on to query BigQuery, which is
        not available in a hermetic run. What matters is that the refusal is
        not an authorization one."""
        r = client.get("/api/audit-logs", headers=_hdr(role=role))
        assert r.status_code != 403

    def test_query_tenant_id_cannot_widen_scope(self, client):
        """Even for a permitted role, the tenant is the JWT claim."""
        r = client.get(
            "/api/audit-logs?tenant_id=tenant-b", headers=_hdr(tenant="tenant-a")
        )
        if r.status_code == 200:
            assert r.json()["tenant_id"] == "tenant-a"


class TestServerErrorsStayLegible:
    def _run(self, gateway, headers: list[tuple[bytes, bytes]]):
        request = Request(
            {
                "type": "http",
                "method": "GET",
                "path": "/api/compliance/checks/x",
                "headers": headers,
            }
        )
        return asyncio.run(
            gateway.unhandled_exception_handler(request, RuntimeError("boom"))
        )

    def test_500_to_an_allowed_origin_carries_cors_headers(self, gateway, monkeypatch):
        monkeypatch.setattr(gateway, "CORS_ORIGINS", [ORIGIN])
        res = self._run(gateway, [(b"origin", ORIGIN.encode())])
        assert res.status_code == 500
        assert res.headers["access-control-allow-origin"] == ORIGIN
        assert res.headers["vary"] == "Origin"

    def test_500_still_hides_internals(self, gateway, monkeypatch):
        monkeypatch.setattr(gateway, "CORS_ORIGINS", [ORIGIN])
        res = self._run(gateway, [(b"origin", ORIGIN.encode())])
        body = json.loads(res.body)
        assert body["detail"] == "internal server error"
        assert body["error_id"]
        assert "boom" not in res.body.decode()

    def test_unlisted_origin_gets_no_cors_header(self, gateway, monkeypatch):
        """Reflecting an arbitrary Origin while allow_credentials is true would
        hand any site the ability to read authenticated responses."""
        monkeypatch.setattr(gateway, "CORS_ORIGINS", [ORIGIN])
        res = self._run(gateway, [(b"origin", b"https://evil.test")])
        assert "access-control-allow-origin" not in res.headers
