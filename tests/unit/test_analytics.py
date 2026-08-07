"""Unit tests: shared analytics aggregation (hermetic)."""

from __future__ import annotations

from datetime import datetime, timezone

from analytics import aggregate_period


class _Snap:
    def __init__(self, data):
        self._data = data

    def to_dict(self):
        return self._data


class FakeFirestore:
    def __init__(self, checks: list[dict]):
        self._checks = checks

    def collection(self, name):
        return self

    def where(self, *args, **kwargs):
        return self

    def stream(self):
        return iter(_Snap(c) for c in self._checks)


def _check(decision: str, citations: list[str]) -> dict:
    return {
        "tenant_id": "tenant-a",
        "decision": decision,
        "citations": citations,
        "created_at": datetime(2026, 6, 15, tzinfo=timezone.utc).isoformat(),
    }


class TestAggregatePeriod:
    def test_empty_period(self):
        stats = aggregate_period(
            FakeFirestore([]),
            tenant_id="tenant-a",
            period_start=datetime(2026, 6, 1, tzinfo=timezone.utc),
            period_end=datetime(2026, 7, 1, tzinfo=timezone.utc),
        )
        assert stats["total_checks"] == 0
        assert stats["top_failing_rule_ids"] == []

    def test_counts_by_decision(self):
        checks = [
            _check("auto_approved", []),
            _check("auto_approved", []),
            _check("escalated", ["consent_documentation"]),
            _check("rejected", ["consent_documentation"]),
        ]
        stats = aggregate_period(
            FakeFirestore(checks),
            tenant_id="tenant-a",
            period_start=datetime(2026, 6, 1, tzinfo=timezone.utc),
            period_end=datetime(2026, 7, 1, tzinfo=timezone.utc),
        )
        assert stats["total_checks"] == 4
        assert stats["auto_approved"] == 2
        assert stats["escalated"] == 1
        assert stats["rejected"] == 1

    def test_top_failing_rules_ranked_by_frequency(self):
        checks = [
            _check("escalated", ["rule_a"]),
            _check("escalated", ["rule_a"]),
            _check("escalated", ["rule_b"]),
        ]
        stats = aggregate_period(
            FakeFirestore(checks),
            tenant_id="tenant-a",
            period_start=datetime(2026, 6, 1, tzinfo=timezone.utc),
            period_end=datetime(2026, 7, 1, tzinfo=timezone.utc),
        )
        assert stats["top_failing_rule_ids"][0] == "rule_a"
        assert stats["citation_frequency"]["rule_a"] == 2
