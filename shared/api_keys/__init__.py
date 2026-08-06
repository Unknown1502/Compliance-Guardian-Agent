"""Programmatic API keys.

Design constraints, in priority order:

  1. A stolen database must not yield usable keys. Only a SHA-256 hash is
     stored; the plaintext is returned exactly once, at creation, and is
     unrecoverable afterwards.
  2. Verification must not leak timing information, so comparison uses
     hmac.compare_digest rather than ==.
  3. A key must carry its tenant, and that tenant is what scopes every
     request — identical to how the Firebase JWT path works. There is no
     path where an API key can address another tenant's data.
  4. A key must be identifiable in a list without revealing it, hence the
     stored prefix.

Format: cg_<env>_<32 url-safe random chars>, e.g. cg_live_3f9a...
The random part carries ~190 bits of entropy from secrets.token_urlsafe.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone

KEY_PREFIX = "cg_live_"
_RANDOM_BYTES = 24  # -> 32 url-safe chars
PREFIX_DISPLAY_LEN = 12  # cg_live_ + first 4 random chars


@dataclass(frozen=True)
class GeneratedKey:
    plaintext: str
    key_hash: str
    display_prefix: str


def generate_api_key() -> GeneratedKey:
    """Mint a new key. The plaintext is only ever available from this call."""
    random_part = secrets.token_urlsafe(_RANDOM_BYTES)
    plaintext = f"{KEY_PREFIX}{random_part}"
    return GeneratedKey(
        plaintext=plaintext,
        key_hash=hash_api_key(plaintext),
        display_prefix=plaintext[:PREFIX_DISPLAY_LEN],
    )


def hash_api_key(plaintext: str) -> str:
    """SHA-256 of the key. Not a password hash on purpose.

    A password needs a slow KDF because it is low-entropy and human-chosen.
    This key is 190+ bits of CSPRNG output, so brute force is infeasible
    regardless of hash speed, and a slow KDF would add latency to every
    single API request for no security gain.
    """
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


def verify_api_key(plaintext: str, expected_hash: str) -> bool:
    """Constant-time comparison of a presented key against a stored hash."""
    return hmac.compare_digest(hash_api_key(plaintext), expected_hash)


def looks_like_api_key(value: str) -> bool:
    """Cheap shape check so obviously-wrong values skip the datastore hit."""
    return bool(value) and value.startswith(KEY_PREFIX) and len(value) > len(KEY_PREFIX) + 16


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
