"""Token-bucket rate limiter for the upload endpoint.

Spec requires rate-limiting the upload endpoint. This is an in-memory token
bucket keyed by tenant_id: each tenant gets `capacity` tokens that refill at
`refill_per_second`. A request costs one token; when the bucket is empty the
gateway returns HTTP 429.

Scope note (flagged): in-memory state is correct for a single instance. A
multi-instance Cloud Run deployment needs a shared limiter (Memorystore/Redis)
or an edge limiter (Cloud Armor / API Gateway quotas). The interface below is
the seam where that backend swaps in.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass


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
