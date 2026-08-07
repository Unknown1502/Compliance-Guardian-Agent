"""Unit tests: rate limiting — token bucket, exponential backoff, env config.

Hermetic: no emulators, no network. Time is driven by monkeypatching
`time.monotonic` so the tests never actually sleep.
"""

from __future__ import annotations

import pytest

from api_gateway.rate_limit import (
    BackoffRateLimiter,
    BucketLimits,
    TokenBucketRateLimiter,
    limits_from_env,
)


class FakeClock:
    """Controllable stand-in for time.monotonic."""

    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture()
def clock(monkeypatch):
    c = FakeClock()
    monkeypatch.setattr("api_gateway.rate_limit.time.monotonic", c)
    return c


class TestTokenBucket:
    def test_allows_up_to_capacity_then_rejects(self, clock):
        limiter = TokenBucketRateLimiter(capacity=3, refill_per_second=1.0)
        assert [limiter.allow("k") for _ in range(3)] == [True, True, True]
        assert limiter.allow("k") is False

    def test_refills_over_time(self, clock):
        limiter = TokenBucketRateLimiter(capacity=2, refill_per_second=1.0)
        assert limiter.allow("k") is True
        assert limiter.allow("k") is True
        assert limiter.allow("k") is False
        clock.advance(1.0)
        assert limiter.allow("k") is True

    def test_refill_is_capped_at_capacity(self, clock):
        limiter = TokenBucketRateLimiter(capacity=2, refill_per_second=1.0)
        limiter.allow("k")
        limiter.allow("k")
        clock.advance(1000.0)  # far more than enough to overfill
        assert [limiter.allow("k") for _ in range(3)] == [True, True, False]

    def test_keys_are_independent(self, clock):
        limiter = TokenBucketRateLimiter(capacity=1, refill_per_second=1.0)
        assert limiter.allow("tenant-a") is True
        assert limiter.allow("tenant-a") is False
        assert limiter.allow("tenant-b") is True

    def test_retry_after_is_zero_when_tokens_available(self, clock):
        limiter = TokenBucketRateLimiter(capacity=2, refill_per_second=1.0)
        assert limiter.retry_after_seconds("k") == 0

    def test_retry_after_positive_once_exhausted(self, clock):
        limiter = TokenBucketRateLimiter(capacity=1, refill_per_second=0.5)
        limiter.allow("k")
        assert limiter.retry_after_seconds("k") >= 1

    def test_retry_after_does_not_consume_a_token(self, clock):
        limiter = TokenBucketRateLimiter(capacity=1, refill_per_second=1.0)
        limiter.retry_after_seconds("k")
        limiter.retry_after_seconds("k")
        # Asking how long to wait must not itself spend the budget.
        assert limiter.allow("k") is True

    def test_from_limits_uses_the_configured_values(self, clock):
        limiter = TokenBucketRateLimiter.from_limits(
            BucketLimits(capacity=2, refill_per_second=1.0)
        )
        assert [limiter.allow("k") for _ in range(3)] == [True, True, False]


class TestBackoffLimiter:
    def test_free_attempts_incur_no_cooldown(self, clock):
        limiter = BackoffRateLimiter(free_attempts=3, base_seconds=2.0)
        for _ in range(3):
            limiter.record_failure("user@example.com")
            assert limiter.allow("user@example.com") is True

    def test_first_penalised_failure_waits_base_seconds(self, clock):
        limiter = BackoffRateLimiter(free_attempts=1, base_seconds=2.0)
        limiter.record_failure("k")  # free
        limiter.record_failure("k")  # first penalised -> 2s
        assert limiter.allow("k") is False
        clock.advance(2.0)
        assert limiter.allow("k") is True

    def test_delay_doubles_each_additional_failure(self, clock):
        limiter = BackoffRateLimiter(free_attempts=0, base_seconds=1.0)
        limiter.record_failure("k")  # -> 1s
        assert limiter.retry_after_seconds("k") == pytest.approx(1, abs=1)
        clock.advance(1.0)
        limiter.record_failure("k")  # -> 2s
        assert limiter.allow("k") is False
        clock.advance(1.0)
        assert limiter.allow("k") is False  # 2s not yet elapsed
        clock.advance(1.0)
        assert limiter.allow("k") is True

    def test_delay_is_capped(self, clock):
        limiter = BackoffRateLimiter(free_attempts=0, base_seconds=1.0, max_seconds=10.0)
        for _ in range(20):
            limiter.record_failure("k")
        assert limiter.retry_after_seconds("k") <= 11

    def test_success_clears_penalty_state(self, clock):
        limiter = BackoffRateLimiter(free_attempts=0, base_seconds=5.0)
        limiter.record_failure("k")
        assert limiter.allow("k") is False
        limiter.record_success("k")
        assert limiter.allow("k") is True
        assert limiter.retry_after_seconds("k") == 0

    def test_never_permanently_locks_out(self, clock):
        """A lockout that never lifts is itself a denial-of-service primitive."""
        limiter = BackoffRateLimiter(free_attempts=0, base_seconds=1.0, max_seconds=60.0)
        for _ in range(50):
            limiter.record_failure("victim@example.com")
        clock.advance(61.0)
        assert limiter.allow("victim@example.com") is True

    def test_keys_are_independent(self, clock):
        limiter = BackoffRateLimiter(free_attempts=0, base_seconds=5.0)
        limiter.record_failure("a")
        assert limiter.allow("a") is False
        assert limiter.allow("b") is True

    def test_unknown_key_is_allowed(self, clock):
        limiter = BackoffRateLimiter()
        assert limiter.allow("never-seen") is True
        assert limiter.retry_after_seconds("never-seen") == 0


class TestLimitsFromEnv:
    def test_defaults_when_unset(self, monkeypatch):
        for var in (
            "CG_RL_AUTH_CAPACITY",
            "CG_RL_UPLOAD_CAPACITY",
            "CG_RL_EXPENSIVE_CAPACITY",
            "CG_RL_BACKOFF_FREE_ATTEMPTS",
        ):
            monkeypatch.delenv(var, raising=False)
        s = limits_from_env()
        assert s.auth.capacity == 5
        # Preserves the pre-existing upload limit exactly.
        assert s.upload.capacity == 20
        assert s.upload.refill_per_second == 0.5
        assert s.backoff_free_attempts == 3

    def test_env_overrides_are_honoured(self, monkeypatch):
        monkeypatch.setenv("CG_RL_AUTH_CAPACITY", "42")
        monkeypatch.setenv("CG_RL_EXPENSIVE_REFILL_PER_SEC", "0.25")
        monkeypatch.setenv("CG_RL_BACKOFF_MAX_SECONDS", "60")
        s = limits_from_env()
        assert s.auth.capacity == 42
        assert s.expensive.refill_per_second == 0.25
        assert s.backoff_max_seconds == 60.0

    def test_malformed_values_fall_back_to_defaults(self, monkeypatch):
        monkeypatch.setenv("CG_RL_AUTH_CAPACITY", "not-a-number")
        monkeypatch.setenv("CG_RL_UPLOAD_REFILL_PER_SEC", "")
        s = limits_from_env()
        assert s.auth.capacity == 5
        assert s.upload.refill_per_second == 0.5

    def test_zero_and_negative_are_rejected_as_defaults(self, monkeypatch):
        """A limit of 0 would block all traffic; a negative one is meaningless."""
        monkeypatch.setenv("CG_RL_AUTH_CAPACITY", "0")
        monkeypatch.setenv("CG_RL_STANDARD_CAPACITY", "-5")
        s = limits_from_env()
        assert s.auth.capacity == 5
        assert s.standard.capacity == 120
