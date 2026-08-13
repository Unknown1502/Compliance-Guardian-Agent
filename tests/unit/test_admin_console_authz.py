"""Every Admin Control Center route refuses a customer — including the writes.

The existing platform test covers ten GET routes. It omits the entire Support
section and all three write endpoints, one of which suspends a workspace. Those
routes are guarded today, but nothing failed if a guard was removed, and the
write endpoints are exactly the ones where that would matter.

This enumerates the console's whole surface rather than a hand-kept list, so a
route added later without a guard shows up here instead of in an incident.
"""

from __future__ import annotations

import base64
import json

import pytest
from fastapi.testclient import TestClient

ADMIN = "operator@example.com"
CUSTOMER = "customer@acme.test"


def _tok(uid="u1", tenant="tenant-a", role="owner", email=None) -> str:
    claims = {"uid": uid, "tenant_id": tenant, "role": role}
    if email:
        claims["email"] = email
    raw = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return f"dev:{raw}"


def _hdr(**kw) -> dict:
    return {"Authorization": f"Bearer {_tok(**kw)}"}


# (method, path, body). The full console surface, writes included.
CONSOLE_ROUTES = [
    ("GET", "/api/platform/whoami", None),
    ("GET", "/api/platform/overview", None),
    ("GET", "/api/platform/audit", None),
    ("GET", "/api/platform/documents", None),
    ("GET", "/api/platform/reviews", None),
    ("GET", "/api/platform/agents", None),
    ("GET", "/api/platform/compliance", None),
    ("GET", "/api/platform/rulesets", None),
    ("GET", "/api/platform/security", None),
    ("GET", "/api/platform/system", None),
    # Previously untested — the Support section.
    ("GET", "/api/platform/support", None),
    ("GET", "/api/platform/support/permissions", None),
    # Previously untested — every write the console can perform.
    ("POST", "/api/platform/support/t-1/reply", {"body": "unauthorised reply"}),
    ("PUT", "/api/platform/support/t-1", {"status": "closed"}),
    (
        "PUT",
        "/api/platform/tenants/tenant-a/status",
        {"status": "suspended", "reason": "unauthorised suspension attempt"},
    ),
]

WRITES = [r for r in CONSOLE_ROUTES if r[0] != "GET"]


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("CG_AUTH_DEV_MODE", "1")
    monkeypatch.setenv("CG_PLATFORM_ADMIN_UIDS", ADMIN)
    import api_gateway.main as main
    import auth_middleware

    monkeypatch.setattr(auth_middleware, "_ensure_firebase_app", lambda: None)
    return TestClient(main.app, raise_server_exceptions=False)


def _call(c, method, path, body, headers=None):
    kw = {"headers": headers} if headers else {}
    if body is not None:
        kw["json"] = body
    return getattr(c, method.lower())(path, **kw)


class TestNoCustomerReachesTheConsole:
    @pytest.mark.parametrize(
        "method,path,body", CONSOLE_ROUTES, ids=[f"{m} {p}" for m, p, _ in CONSOLE_ROUTES]
    )
    def test_a_valid_customer_session_is_refused(self, client, method, path, body):
        """404 rather than 403 — a 403 would confirm the route exists."""
        r = _call(client, method, path, body, _hdr(email=CUSTOMER))
        assert r.status_code == 404, f"{method} {path} leaked {r.status_code}"

    @pytest.mark.parametrize(
        "method,path,body", CONSOLE_ROUTES, ids=[f"{m} {p}" for m, p, _ in CONSOLE_ROUTES]
    )
    def test_unauthenticated_is_refused(self, client, method, path, body):
        assert _call(client, method, path, body).status_code == 401

    @pytest.mark.parametrize("method,path,body", WRITES, ids=[f"{m} {p}" for m, p, _ in WRITES])
    def test_a_forged_admin_role_does_not_help(self, client, method, path, body):
        """Platform access comes from server-side config, not a token claim —
        so even a fully forged role/tenant cannot reach a write."""
        r = _call(client, method, path, body, _hdr(uid="attacker", role="admin", email="attacker@evil.test"))
        assert r.status_code == 404


class TestTheWritesAreTheOnlyWrites:
    """The console's write surface is deliberately tiny. If it grows, this
    fails and someone has to justify the addition."""

    def test_only_three_write_routes_exist(self):
        import re
        from pathlib import Path

        root = Path(__file__).resolve().parents[2] / "apps/api-gateway/api_gateway"
        found = []
        for f in ("admin_routes.py", "support_routes.py"):
            src = (root / f).read_text(encoding="utf-8")
            found += re.findall(r'@router\.(post|put|patch|delete)\("(/platform[^"]*)"', src)
        assert sorted(found) == sorted(
            [
                ("post", "/platform/support/{ticket_id}/reply"),
                ("put", "/platform/support/{ticket_id}"),
                ("put", "/platform/tenants/{tenant_id}/status"),
            ]
        ), f"the console's write surface changed: {found}"

    def test_no_console_route_can_delete(self):
        """Nothing on the operator console deletes a customer's records. That
        is the ACCESS-not-RECORDS guarantee expressed as a route inventory."""
        import re
        from pathlib import Path

        root = Path(__file__).resolve().parents[2] / "apps/api-gateway/api_gateway"
        for f in ("admin_routes.py", "support_routes.py"):
            src = (root / f).read_text(encoding="utf-8")
            assert not re.findall(r'@router\.delete\("(/platform[^"]*)"', src)


class TestEveryConsoleRouteIsCovered:
    def test_the_route_list_matches_the_code(self):
        """Stops this file going stale: a platform route added without a case
        here fails immediately rather than going untested."""
        import re
        from pathlib import Path

        root = Path(__file__).resolve().parents[2] / "apps/api-gateway/api_gateway"
        actual = set()
        for f in ("admin_routes.py", "support_routes.py"):
            src = (root / f).read_text(encoding="utf-8")
            for m, p in re.findall(
                r'@router\.(get|post|put|patch|delete)\("(/platform[^"]*)"', src
            ):
                actual.add((m.upper(), p))

        # The cases above call routes with concrete ids; the source declares
        # them as {ticket_id} / {tenant_id}. Collapse both sides to the same
        # shape so a parameterised route is recognised as covered.
        def norm(p: str) -> str:
            p = p.replace("/api", "")
            p = re.sub(r"\{[^}]+\}", "{}", p)
            return re.sub(r"/(t-1|tenant-a)(?=/|$)", "/{}", p)

        covered = {(m, norm(p)) for m, p, _ in CONSOLE_ROUTES}
        missing = {(m, norm(p)) for m, p in actual} - covered
        assert not missing, f"platform routes with no authorization test: {sorted(missing)}"
