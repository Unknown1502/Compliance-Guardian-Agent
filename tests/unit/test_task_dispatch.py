"""Unit tests: task dispatch + rate limiter."""

from __future__ import annotations

import pytest

from api_gateway.rate_limit import TokenBucketRateLimiter
from task_dispatch import InlineDispatcher


class TestInlineDispatcher:
    def test_dispatch_calls_handler(self):
        received = {}
        d = InlineDispatcher({"ingest": lambda p: received.update(p)})
        task_id = d.dispatch(target="ingest", payload={"document_id": "doc-1"})
        assert received == {"document_id": "doc-1"}
        assert task_id == "inline:ingest"

    def test_unknown_target_raises(self):
        d = InlineDispatcher({})
        with pytest.raises(KeyError):
            d.dispatch(target="nope", payload={})

    def test_handler_exception_propagates(self):
        def boom(_):
            raise RuntimeError("handler failed")

        d = InlineDispatcher({"check": boom})
        with pytest.raises(RuntimeError):
            d.dispatch(target="check", payload={})


class TestRateLimiter:
    def test_allows_up_to_capacity_then_blocks(self):
        limiter = TokenBucketRateLimiter(capacity=3, refill_per_second=0.0)
        assert limiter.allow("tenant-a")
        assert limiter.allow("tenant-a")
        assert limiter.allow("tenant-a")
        assert not limiter.allow("tenant-a")  # 4th blocked

    def test_buckets_are_per_key(self):
        limiter = TokenBucketRateLimiter(capacity=1, refill_per_second=0.0)
        assert limiter.allow("tenant-a")
        assert not limiter.allow("tenant-a")
        # Different tenant unaffected.
        assert limiter.allow("tenant-b")

    def test_refill_grants_new_tokens(self, monkeypatch):
        import api_gateway.rate_limit as rl

        clock = {"t": 1000.0}
        monkeypatch.setattr(rl.time, "monotonic", lambda: clock["t"])
        limiter = TokenBucketRateLimiter(capacity=1, refill_per_second=1.0)
        assert limiter.allow("t")
        assert not limiter.allow("t")
        clock["t"] += 1.5  # 1.5s -> +1 token (capped at capacity)
        assert limiter.allow("t")
