"""Firebase Auth middleware for FastAPI services.

Security contract (from spec, non-negotiable):
  - Every endpoint verifies a Firebase Auth JWT.
  - tenant_id ALWAYS comes from the verified token's custom claims — never
    from request bodies, query params, or headers supplied by the client.
  - Roles: 'owner' (upload, view, reports) and 'reviewer' (approve/reject
    escalations). Owners are not reviewers unless explicitly granted.

Usage in a service:

    from auth_middleware import AuthContext, require_auth, require_role

    @app.get("/api/documents/{doc_id}")
    def get_doc(doc_id: str, auth: AuthContext = Depends(require_auth)):
        ...  # auth.tenant_id is trusted

    @app.patch("/api/compliance/checks/{check_id}")
    def decide(check_id: str, auth: AuthContext = Depends(require_role("reviewer"))):
        ...
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass

import firebase_admin
from fastapi import Depends, HTTPException, Request, status
from firebase_admin import auth as fb_auth

logger = logging.getLogger("cg.auth")

_init_lock = threading.Lock()

VALID_ROLES = frozenset({"owner", "reviewer", "admin"})


def _ensure_firebase_app() -> firebase_admin.App:
    """Initialize the default Firebase app exactly once (thread-safe).

    With FIREBASE_AUTH_EMULATOR_HOST set, firebase-admin verifies unsigned
    emulator tokens; in production it verifies real Google-signed JWTs via ADC.
    """
    with _init_lock:
        try:
            return firebase_admin.get_app()
        except ValueError:
            return firebase_admin.initialize_app()


@dataclass(frozen=True)
class AuthContext:
    """Verified identity passed to route handlers. tenant_id is trusted."""

    uid: str
    tenant_id: str
    role: str
    email: str | None = None


def _verify_bearer_token(request: Request) -> AuthContext:
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = header.removeprefix("Bearer ").strip()
    _ensure_firebase_app()
    try:
        decoded = fb_auth.verify_id_token(token)
    except Exception as exc:
        logger.info("token verification failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    tenant_id = decoded.get("tenant_id")
    role = decoded.get("role")
    if not tenant_id or not isinstance(tenant_id, str):
        # A token without a tenant claim must never touch tenant data.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Token missing tenant_id claim",
        )
    if role not in VALID_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Token missing or invalid role claim",
        )
    return AuthContext(
        uid=decoded["uid"],
        tenant_id=tenant_id,
        role=role,
        email=decoded.get("email"),
    )


def require_auth(request: Request) -> AuthContext:
    """FastAPI dependency: any authenticated tenant member."""
    return _verify_bearer_token(request)


def require_role(*allowed: str):
    """FastAPI dependency factory: authenticated AND role in `allowed`.

    'admin' implicitly satisfies every role check.
    """
    unknown = set(allowed) - VALID_ROLES
    if unknown:
        raise ValueError(f"unknown roles in require_role: {sorted(unknown)}")

    def dependency(auth: AuthContext = Depends(require_auth)) -> AuthContext:
        if auth.role != "admin" and auth.role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires role: {' or '.join(sorted(allowed))}",
            )
        return auth

    return dependency
