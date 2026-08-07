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


def _check(decision: str, citations: list[str] | None) -> dict:
    return {
        "tenant_id": "tenant-a",
        "decision": decision,
        "citations": citations,
        "created_at": datetime(2026, 6, 15, tzinfo=timezone.utc).isoformat(),
    }


def _check_missing_citations_key(decision: str) -> dict:
    """A check dict shaped like older Firestore data written before the
    citations field existed -- no "citations" key at all, as opposed to
    a present-but-empty/None value."""
    return {
        "tenant_id": "tenant-a",
        "decision": decision,
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

    def test_top_failing_rules_truncated_to_exactly_three(self):
        """With more than 3 distinct cited rules, only the top 3 by frequency
        survive -- both in top_failing_rule_ids and in citation_frequency."""
        checks = (
            [_check("escalated", ["rule_a"])] * 4
            + [_check("escalated", ["rule_b"])] * 3
            + [_check("escalated", ["rule_c"])] * 2
            + [_check("escalated", ["rule_d"])] * 1
        )
        stats = aggregate_period(
            FakeFirestore(checks),
            tenant_id="tenant-a",
            period_start=datetime(2026, 6, 1, tzinfo=timezone.utc),
            period_end=datetime(2026, 7, 1, tzinfo=timezone.utc),
        )
        assert len(stats["top_failing_rule_ids"]) == 3
        assert stats["top_failing_rule_ids"] == ["rule_a", "rule_b", "rule_c"]
        assert set(stats["citation_frequency"]) == {"rule_a", "rule_b", "rule_c"}
        assert "rule_d" not in stats["citation_frequency"]

    def test_tied_citation_counts_preserve_first_seen_order(self):
        """When two rules are cited an equal number of times, ranking must not
        be arbitrary: the rule cited first (in check-stream order) sorts
        first. This pins down the sort's stability, which the pre-refactor
        code also relied on -- a future change to ranking logic must not
        silently reorder tied rules in customer-facing reports."""
        checks = [
            _check("escalated", ["rule_y"]),
            _check("escalated", ["rule_x"]),
            _check("escalated", ["rule_y"]),
            _check("escalated", ["rule_x"]),
        ]
        stats = aggregate_period(
            FakeFirestore(checks),
            tenant_id="tenant-a",
            period_start=datetime(2026, 6, 1, tzinfo=timezone.utc),
            period_end=datetime(2026, 7, 1, tzinfo=timezone.utc),
        )
        assert stats["citation_frequency"]["rule_y"] == stats["citation_frequency"]["rule_x"] == 2
        assert stats["top_failing_rule_ids"] == ["rule_y", "rule_x"]

    def test_missing_citations_key_counts_check_without_crashing(self):
        """A check dict with no "citations" key at all (older data shape)
        must still be counted in total/decision tallies and must not crash
        or contribute a phantom citation."""
        checks = [_check_missing_citations_key("auto_approved")]
        stats = aggregate_period(
            FakeFirestore(checks),
            tenant_id="tenant-a",
            period_start=datetime(2026, 6, 1, tzinfo=timezone.utc),
            period_end=datetime(2026, 7, 1, tzinfo=timezone.utc),
        )
        assert stats["total_checks"] == 1
        assert stats["auto_approved"] == 1
        assert stats["top_failing_rule_ids"] == []
        assert stats["citation_frequency"] == {}

    def test_none_citations_value_counts_check_without_crashing(self):
        """A check dict with citations explicitly set to None must still be
        counted in total/decision tallies and must not crash or contribute a
        phantom citation."""
        checks = [_check("escalated", None)]
        stats = aggregate_period(
            FakeFirestore(checks),
            tenant_id="tenant-a",
            period_start=datetime(2026, 6, 1, tzinfo=timezone.utc),
            period_end=datetime(2026, 7, 1, tzinfo=timezone.utc),
        )
        assert stats["total_checks"] == 1
        assert stats["escalated"] == 1
        assert stats["top_failing_rule_ids"] == []
        assert stats["citation_frequency"] == {}

    def test_period_bounds_returned_as_isoformat_of_inputs(self):
        """period_start/period_end in the returned stats must be the
        isoformat strings of the inputs -- reporter.py's HTML rendering and
        the fixture executive-summary prompt both consume these directly."""
        start = datetime(2026, 6, 1, tzinfo=timezone.utc)
        end = datetime(2026, 7, 1, tzinfo=timezone.utc)
        stats = aggregate_period(
            FakeFirestore([]),
            tenant_id="tenant-a",
            period_start=start,
            period_end=end,
        )
        assert stats["period_start"] == start.isoformat()
        assert stats["period_end"] == end.isoformat()
