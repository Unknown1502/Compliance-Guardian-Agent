"""Rate limiting for the API gateway.

Two limiter shapes, because auth routes and everything else need different
behaviour:

  TokenBucketRateLimiter — steady-rate limiter for ordinary traffic. Each key
  gets `capacity` tokens refilling at `refill_per_second`; a request costs one
  token and an empty bucket means HTTP 429.

  BackoffRateLimiter — for authentication routes (signup, and any future
  login/password-reset endpoint that terminates here rather than at Firebase).
  Instead of a hard lockout after N attempts, each failure past the free
  allowance doubles a cooldown window, capped at `max_delay_seconds`. That
  makes credential stuffing exponentially expensive while a legitimate user
  who mistyped something waits seconds, not hours, and is never permanently
  locked out — which is also what stops lockout itself becoming the DoS.

Auth routes are limited on BOTH the client IP and the account identifier.
Neither alone is sufficient: per-IP only lets an attacker rotate IPs against
one account, and per-account only lets them spray one attempt each across
many accounts from a single host.

Every threshold is read from the environment (see `limits_from_env`), so
tuning production does not require a code change or redeploy of new logic.

Scope note (unchanged from the original design, and still true): this state
is per-process. A multi-instance Cloud Run deployment therefore enforces
roughly N x the configured limit and loses counters on cold start. The
classes below are the seam where a shared backend (Memorystore/Redis) or an
edge limiter (Cloud Armor) swaps in; until then, treat these numbers as a
per-instance ceiling rather than a global guarantee.
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field


def _env_int(name: str, default: int) -> int:
    """Read a positive int from the environment, falling back on anything unusable.

    A malformed limit must never take the gateway down at import time, and it
    must never silently become 0 (which would block all traffic) or negative.
    """
    raw = os.environ.get(name, "")
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name, "")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


@dataclass(frozen=True)
class BucketLimits:
    """Configuration for one token bucket: burst size and sustained rate."""

    capacity: int
    refill_per_second: float


@dataclass(frozen=True)
class RateLimitSettings:
    """All gateway rate limits, resolved once at import from the environment.

    Grouped by how much a request costs us rather than by URL, so a new
    endpoint picks its tier by asking "what does this consume?":

      auth      — creates accounts / verifies credentials. Strictest, plus
                  exponential backoff on top.
      public    — reachable without a bearer token. Moderate.
      expensive — spends money or reaches a third party per call (Gemini,
                  BigQuery, payment providers, Slack, Firebase user creation).
      standard  — ordinary authenticated reads and writes. Loosest.
    """

    auth: BucketLimits
    public: BucketLimits
    expensive: BucketLimits
    standard: BucketLimits
    upload: BucketLimits
    backoff_free_attempts: int
    backoff_base_seconds: float
    backoff_max_seconds: float


def limits_from_env() -> RateLimitSettings:
    """Build the settings from environment variables, with usable defaults.

    Defaults are deliberately generous enough that a real small-business user
    never notices them, and tight enough that scripted abuse does.
    """
    return RateLimitSettings(
        # 5 signups per IP, refilling one every 2 minutes.
        auth=BucketLimits(
            capacity=_env_int("CG_RL_AUTH_CAPACITY", 5),
            refill_per_second=_env_float("CG_RL_AUTH_REFILL_PER_SEC", 1 / 120),
        ),
        public=BucketLimits(
            capacity=_env_int("CG_RL_PUBLIC_CAPACITY", 60),
            refill_per_second=_env_float("CG_RL_PUBLIC_REFILL_PER_SEC", 1.0),
        ),
        # Every one of these costs real money or hits a third party.
        expensive=BucketLimits(
            capacity=_env_int("CG_RL_EXPENSIVE_CAPACITY", 20),
            refill_per_second=_env_float("CG_RL_EXPENSIVE_REFILL_PER_SEC", 1 / 30),
        ),
        standard=BucketLimits(
            capacity=_env_int("CG_RL_STANDARD_CAPACITY", 120),
            refill_per_second=_env_float("CG_RL_STANDARD_REFILL_PER_SEC", 2.0),
        ),
        # Preserves the original upload limit: 20 burst, 0.5/s sustained.
        upload=BucketLimits(
            capacity=_env_int("CG_RL_UPLOAD_CAPACITY", 20),
            refill_per_second=_env_float("CG_RL_UPLOAD_REFILL_PER_SEC", 0.5),
        ),
        backoff_free_attempts=_env_int("CG_RL_BACKOFF_FREE_ATTEMPTS", 3),
        backoff_base_seconds=_env_float("CG_RL_BACKOFF_BASE_SECONDS", 2.0),
        backoff_max_seconds=_env_float("CG_RL_BACKOFF_MAX_SECONDS", 900.0),
    )


@dataclass
class _Bucket:
    tokens: float
    last_refill: float


class TokenBucketRateLimiter:
    def __init__(self, *, capacity: int = 20, refill_per_second: float = 0.5) -> None:
        self._capacity = capacity
        self._refill = refill_per_second
        self._buckets: dict[str, _Bucket] = {}
        self._lock = threading.Lock()

    @classmethod
    def from_limits(cls, limits: BucketLimits) -> TokenBucketRateLimiter:
        return cls(capacity=limits.capacity, refill_per_second=limits.refill_per_second)

    def allow(self, key: str, cost: float = 1.0) -> bool:
        now = time.monotonic()
        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                bucket = _Bucket(tokens=float(self._capacity), last_refill=now)
                self._buckets[key] = bucket
            # Refill based on elapsed time, capped at capacity.
            elapsed = now - bucket.last_refill
            bucket.tokens = min(self._capacity, bucket.tokens + elapsed * self._refill)
            bucket.last_refill = now
            if bucket.tokens >= cost:
                bucket.tokens -= cost
                return True
            return False

    def retry_after_seconds(self, key: str, cost: float = 1.0) -> int:
        """Seconds until `cost` tokens are available, for the Retry-After header.

        Read-only: it must not consume a token, or merely asking how long to
        wait would push the answer further out.
        """
        with self._lock:
            bucket = self._buckets.get(key)
            tokens = float(self._capacity) if bucket is None else bucket.tokens
        if tokens >= cost or self._refill <= 0:
            return 0
        return max(1, int((cost - tokens) / self._refill) + 1)


@dataclass
class _BackoffState:
    failures: int = 0
    blocked_until: float = 0.0


@dataclass
class _AttemptRecord:
    """Per-key backoff state, guarded by the owning limiter's lock."""

    state: _BackoffState = field(default_factory=_BackoffState)


class BackoffRateLimiter:
    """Exponential-backoff limiter for authentication attempts.

    The first `free_attempts` failures cost nothing — people mistype
    passwords. Each failure after that sets a cooldown of
    `base_seconds * 2**(failures - free_attempts)`, capped at `max_seconds`.
    A success clears the record entirely, so a legitimate user is never
    carrying penalty state forward.

    Deliberately NOT a lockout: the key always becomes usable again on its
    own. A permanent lockout keyed on an account identifier is itself an
    attack — anyone could lock any user out by failing on their behalf.
    """

    def __init__(
        self,
        *,
        free_attempts: int = 3,
        base_seconds: float = 2.0,
        max_seconds: float = 900.0,
    ) -> None:
        self._free = free_attempts
        self._base = base_seconds
        self._max = max_seconds
        self._records: dict[str, _AttemptRecord] = {}
        self._lock = threading.Lock()

    @classmethod
    def from_settings(cls, settings: RateLimitSettings) -> BackoffRateLimiter:
        return cls(
            free_attempts=settings.backoff_free_attempts,
            base_seconds=settings.backoff_base_seconds,
            max_seconds=settings.backoff_max_seconds,
        )

    def allow(self, key: str) -> bool:
        """True if `key` is not currently in a cooldown window."""
        now = time.monotonic()
        with self._lock:
            record = self._records.get(key)
            if record is None:
                return True
            return now >= record.state.blocked_until

    def retry_after_seconds(self, key: str) -> int:
        now = time.monotonic()
        with self._lock:
            record = self._records.get(key)
            if record is None:
                return 0
            remaining = record.state.blocked_until - now
        return max(0, int(remaining) + 1) if remaining > 0 else 0

    def record_failure(self, key: str) -> None:
        """Count a failed attempt and extend the cooldown if past the allowance."""
        now = time.monotonic()
        with self._lock:
            record = self._records.setdefault(key, _AttemptRecord())
            record.state.failures += 1
            over = record.state.failures - self._free
            if over <= 0:
                return
            # 2**(over-1) so the first penalised failure waits base_seconds,
            # not double it. Exponent is clamped before use because a long-
            # running attacker would otherwise overflow the float.
            delay = min(self._max, self._base * (2 ** min(over - 1, 32)))
            record.state.blocked_until = now + delay

    def record_success(self, key: str) -> None:
        """Clear all penalty state for `key` after a successful attempt."""
        with self._lock:
            self._records.pop(key, None)
