"""Unit tests: shared analytics aggregation (hermetic)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from analytics import (
    aggregate_period,
    all_time_top_violations,
    weekly_trend,
)


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


# ---------------------------------------------------------------------------
# Trend analytics
# ---------------------------------------------------------------------------

NOW = datetime(2026, 8, 7, 12, 0, tzinfo=timezone.utc)


def _check_at(when: datetime, decision: str = "escalated", citations=None) -> dict:
    """A check stamped at a specific time, for bucketing tests."""
    return {
        "tenant_id": "tenant-a",
        "decision": decision,
        "citations": citations if citations is not None else [],
        "created_at": when.isoformat(),
    }


class CountingFirestore(FakeFirestore):
    """FakeFirestore that records how many queries were issued."""

    def __init__(self, checks):
        super().__init__(checks)
        self.stream_calls = 0

    def stream(self):
        self.stream_calls += 1
        return super().stream()


class TestWeeklyTrend:
    def test_returns_requested_number_of_weeks(self):
        buckets = weekly_trend(
            FakeFirestore([]), tenant_id="tenant-a", weeks=4, now=NOW
        )
        assert len(buckets) == 4

    def test_buckets_ordered_oldest_first(self):
        buckets = weekly_trend(
            FakeFirestore([]), tenant_id="tenant-a", weeks=3, now=NOW
        )
        starts = [b["week_start"] for b in buckets]
        assert starts == sorted(starts)

    def test_empty_tenant_returns_all_zero_buckets(self):
        buckets = weekly_trend(
            FakeFirestore([]), tenant_id="tenant-a", weeks=2, now=NOW
        )
        assert all(b["total_checks"] == 0 for b in buckets)

    def test_buckets_are_contiguous_and_seven_days_wide(self):
        buckets = weekly_trend(
            FakeFirestore([]), tenant_id="tenant-a", weeks=3, now=NOW
        )
        for b in buckets:
            start = datetime.fromisoformat(b["week_start"])
            end = datetime.fromisoformat(b["week_end"])
            assert (end - start).days == 7
        # Each bucket begins exactly where the previous one ended.
        for earlier, later in zip(buckets, buckets[1:]):
            assert earlier["week_end"] == later["week_start"]
        # The newest bucket ends at the reference instant.
        assert buckets[-1]["week_end"] == NOW.isoformat()

    def test_check_lands_in_the_week_it_belongs_to(self):
        """A check 10 days old belongs to the second-newest of 3 weeks."""
        checks = [_check_at(NOW - timedelta(days=10))]
        buckets = weekly_trend(
            CountingFirestore(checks), tenant_id="tenant-a", weeks=3, now=NOW
        )
        totals = [b["total_checks"] for b in buckets]
        assert totals == [0, 1, 0]

    def test_checks_are_distributed_across_their_own_weeks(self):
        checks = [
            _check_at(NOW - timedelta(days=1)),   # newest week
            _check_at(NOW - timedelta(days=2)),   # newest week
            _check_at(NOW - timedelta(days=9)),   # middle week
            _check_at(NOW - timedelta(days=17)),  # oldest week
        ]
        buckets = weekly_trend(
            FakeFirestore(checks), tenant_id="tenant-a", weeks=3, now=NOW
        )
        assert [b["total_checks"] for b in buckets] == [1, 1, 2]

    def test_checks_outside_the_window_are_excluded(self):
        checks = [
            _check_at(NOW - timedelta(days=3)),    # inside
            _check_at(NOW - timedelta(days=400)),  # far older than the window
            _check_at(NOW + timedelta(days=5)),    # in the future
        ]
        buckets = weekly_trend(
            FakeFirestore(checks), tenant_id="tenant-a", weeks=2, now=NOW
        )
        assert sum(b["total_checks"] for b in buckets) == 1

    def test_decision_mix_is_per_bucket(self):
        checks = [
            _check_at(NOW - timedelta(days=1), "auto_approved"),
            _check_at(NOW - timedelta(days=2), "rejected"),
            _check_at(NOW - timedelta(days=9), "escalated"),
        ]
        buckets = weekly_trend(
            FakeFirestore(checks), tenant_id="tenant-a", weeks=2, now=NOW
        )
        older, newer = buckets
        assert older["escalated"] == 1 and older["total_checks"] == 1
        assert newer["auto_approved"] == 1 and newer["rejected"] == 1

    def test_uses_a_single_query_regardless_of_week_count(self):
        """One range query, bucketed in memory -- not one query per week.

        The per-week shape would cost 12 Firestore round trips by default to
        answer what one range query already covers.
        """
        db = CountingFirestore([])
        weekly_trend(db, tenant_id="tenant-a", weeks=12, now=NOW)
        assert db.stream_calls == 1

    def test_stored_datetime_created_at_still_buckets_correctly(self):
        """Older records may hold a datetime rather than an ISO string."""
        raw = _check_at(NOW - timedelta(days=3))
        raw["created_at"] = NOW - timedelta(days=3)  # datetime, not str
        buckets = weekly_trend(
            FakeFirestore([raw]), tenant_id="tenant-a", weeks=2, now=NOW
        )
        assert sum(b["total_checks"] for b in buckets) == 1


class TestAllTimeTopViolations:
    def test_ranks_by_frequency_and_respects_limit(self):
        checks = [
            _check_at(NOW, citations=["rule_a"]),
            _check_at(NOW, citations=["rule_a"]),
            _check_at(NOW, citations=["rule_b"]),
            _check_at(NOW, citations=["rule_c"]),
        ]
        top = all_time_top_violations(
            FakeFirestore(checks), tenant_id="tenant-a", limit=2
        )
        assert len(top) == 2
        assert top[0] == {"rule_id": "rule_a", "count": 2}

    def test_empty_tenant_returns_empty_list(self):
        assert all_time_top_violations(FakeFirestore([]), tenant_id="tenant-a") == []

    def test_default_limit_caps_the_list(self):
        checks = [_check_at(NOW, citations=[f"rule_{i}"]) for i in range(25)]
        top = all_time_top_violations(FakeFirestore(checks), tenant_id="tenant-a")
        assert len(top) == 10

    def test_counts_every_citation_on_a_multi_citation_check(self):
        checks = [_check_at(NOW, citations=["rule_a", "rule_b"])]
        top = all_time_top_violations(FakeFirestore(checks), tenant_id="tenant-a")
        assert {t["rule_id"]: t["count"] for t in top} == {"rule_a": 1, "rule_b": 1}
