"""Cross-service compliance-check aggregation.

Used by both the Reporting Agent (single-period report stats) and the API
Gateway (multi-week trend analytics) so the two never compute "top failing
rules" or decision-mix counts differently. Firestore-only, matching the
reporting-agent's existing cost-conscious choice to avoid a BigQuery query
job for aggregation a Firestore range query already answers.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from google.cloud import firestore

COLLECTION_CHECKS = "compliance_checks"


def _count_citations(checks: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for data in checks:
        for cit in data.get("citations", []) or []:
            counts[cit] = counts.get(cit, 0) + 1
    return counts


def _created_at_key(data: dict) -> str:
    """created_at as a comparable ISO string.

    The range queries here filter on isoformat strings, so records are
    written that way; a stored datetime is normalised to match rather than
    silently sorting into the wrong bucket.
    """
    value = data.get("created_at")
    if isinstance(value, str):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    return ""


def _summarise(checks: list[dict], period_start: datetime, period_end: datetime) -> dict:
    """Decision mix and top rule citations for an already-fetched set of checks.

    Split out from aggregate_period so weekly_trend can bucket one query's
    results in memory instead of issuing a query per week.
    """
    total = 0
    auto_approved = 0
    escalated = 0
    rejected = 0

    for data in checks:
        total += 1
        decision = data.get("decision", "")
        if decision == "auto_approved":
            auto_approved += 1
        elif decision == "escalated":
            escalated += 1
        elif decision == "rejected":
            rejected += 1

    citation_counts = _count_citations(checks)
    top_3 = sorted(citation_counts, key=lambda k: citation_counts[k], reverse=True)[:3]
    return {
        "total_checks": total,
        "auto_approved": auto_approved,
        "escalated": escalated,
        "rejected": rejected,
        "top_failing_rule_ids": top_3,
        "citation_frequency": {k: citation_counts[k] for k in top_3},
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
    }


def _fetch_period(
    db: firestore.Client, *, tenant_id: str, period_start: datetime, period_end: datetime
) -> list[dict]:
    """Every check for one tenant in [period_start, period_end)."""
    snaps = (
        db.collection(COLLECTION_CHECKS)
        .where("tenant_id", "==", tenant_id)
        .where("created_at", ">=", period_start.isoformat())
        .where("created_at", "<", period_end.isoformat())
        .stream()
    )
    return [snap.to_dict() for snap in snaps]


def aggregate_period(
    db: firestore.Client, *, tenant_id: str, period_start: datetime, period_end: datetime
) -> dict:
    """Aggregate compliance_checks for one tenant over [period_start, period_end)."""
    checks = _fetch_period(
        db, tenant_id=tenant_id, period_start=period_start, period_end=period_end
    )
    return _summarise(checks, period_start, period_end)


def weekly_trend(
    db: firestore.Client, *, tenant_id: str, weeks: int = 12, now: datetime | None = None
) -> list[dict]:
    """One bucket per 7-day window for the last `weeks` weeks, oldest first.

    Deliberately ONE query across the whole window, bucketed in memory,
    rather than a query per week: the per-week version costs `weeks` round
    trips (12 by default) to answer a question a single range query already
    covers, and this module's whole reason for being Firestore-only is to
    keep aggregation cheap.
    """
    reference = now or datetime.now(timezone.utc)
    window_start = reference - timedelta(days=7 * weeks)

    checks = _fetch_period(
        db, tenant_id=tenant_id, period_start=window_start, period_end=reference
    )

    buckets: list[dict] = []
    for i in range(weeks):
        # Oldest bucket first, so the chart reads left-to-right in time.
        bucket_start = window_start + timedelta(days=7 * i)
        bucket_end = bucket_start + timedelta(days=7)
        start_key = bucket_start.isoformat()
        end_key = bucket_end.isoformat()
        in_bucket = [c for c in checks if start_key <= _created_at_key(c) < end_key]
        buckets.append(
            {
                **_summarise(in_bucket, bucket_start, bucket_end),
                "week_start": start_key,
                "week_end": end_key,
            }
        )
    return buckets


def all_time_top_violations(
    db: firestore.Client, *, tenant_id: str, limit: int = 10
) -> list[dict]:
    """Rank rule citations across every check the tenant has ever had."""
    snaps = db.collection(COLLECTION_CHECKS).where("tenant_id", "==", tenant_id).stream()
    counts = _count_citations([snap.to_dict() for snap in snaps])
    ranked = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:limit]
    return [{"rule_id": rule_id, "count": count} for rule_id, count in ranked]
