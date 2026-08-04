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

import base64
import binascii
import json
import logging
import os
import threading
from dataclasses import dataclass

import firebase_admin
from fastapi import Depends, HTTPException, Request, status
from firebase_admin import auth as fb_auth

logger = logging.getLogger("cg.auth")

_init_lock = threading.Lock()

VALID_ROLES = frozenset({"owner", "reviewer", "admin"})

# LOCAL-ONLY dev auth. When CG_AUTH_DEV_MODE=1, the middleware accepts tokens of
# the form "dev:<base64url(json claims)>" instead of verifying a real Firebase
# JWT. This exists ONLY so the dashboard + API gateway can be demonstrated
# end-to-end against local emulators (the Firebase Auth emulator requires Java,
# which is not available here). It is gated behind an env var that defaults OFF
# and logs a loud warning when enabled. Production NEVER sets this flag and uses
# real Firebase Auth verification below.
_DEV_MODE_ENV = "CG_AUTH_DEV_MODE"
_DEV_PREFIX = "dev:"


def _dev_mode_enabled() -> bool:
    return os.environ.get(_DEV_MODE_ENV) == "1"


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


def create_tenant_owner(*, email: str, password: str, tenant_id: str) -> str:
    """Create a brand-new Firebase Auth user as the 'owner' of a brand-new tenant.

    Sets the tenant_id/role custom claims immediately, so the very first ID
    token the client mints after sign-in already carries them — no separate
    claims-propagation step needed. Raises firebase_admin.auth.EmailAlreadyExistsError
    if the email is taken; callers map that to HTTP 409.
    """
    _ensure_firebase_app()
    user = fb_auth.create_user(email=email, password=password)
    fb_auth.set_custom_user_claims(user.uid, {"tenant_id": tenant_id, "role": "owner"})
    return user.uid


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

    # Local-only dev bypass (see module-level note). Never active in production.
    if _dev_mode_enabled() and token.startswith(_DEV_PREFIX):
        return _decode_dev_token(token)

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


def _decode_dev_token(token: str) -> AuthContext:
    """Decode a local dev token: 'dev:<base64url(json claims)>'. Local only."""
    logger.warning("CG_AUTH_DEV_MODE active — accepting a dev token (LOCAL ONLY)")
    raw = token[len(_DEV_PREFIX) :]
    try:
        padding = "=" * (-len(raw) % 4)
        decoded_bytes = base64.urlsafe_b64decode(raw + padding)
        claims = json.loads(decoded_bytes.decode("utf-8"))
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid dev token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    tenant_id = claims.get("tenant_id")
    role = claims.get("role")
    uid = claims.get("uid")
    if not tenant_id or not isinstance(tenant_id, str):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="dev token missing tenant_id")
    if role not in VALID_ROLES:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="dev token invalid role")
    if not uid:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="dev token missing uid")
    return AuthContext(uid=uid, tenant_id=tenant_id, role=role, email=claims.get("email"))


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
