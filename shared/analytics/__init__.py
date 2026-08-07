"""Cross-service compliance-check aggregation.

Used by both the Reporting Agent (single-period report stats) and the API
Gateway (multi-week trend analytics) so the two never compute "top failing
rules" or decision-mix counts differently. Firestore-only, matching the
reporting-agent's existing cost-conscious choice to avoid a BigQuery query
job for aggregation a Firestore range query already answers.
"""

from __future__ import annotations

from datetime import datetime

from google.cloud import firestore

COLLECTION_CHECKS = "compliance_checks"


def _count_citations(checks: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for data in checks:
        for cit in data.get("citations", []) or []:
            counts[cit] = counts.get(cit, 0) + 1
    return counts


def aggregate_period(
    db: firestore.Client, *, tenant_id: str, period_start: datetime, period_end: datetime
) -> dict:
    """Aggregate compliance_checks for one tenant over [period_start, period_end)."""
    checks = (
        db.collection(COLLECTION_CHECKS)
        .where("tenant_id", "==", tenant_id)
        .where("created_at", ">=", period_start.isoformat())
        .where("created_at", "<", period_end.isoformat())
        .stream()
    )
    total = 0
    auto_approved = 0
    escalated = 0
    rejected = 0
    all_data: list[dict] = []

    for snap in checks:
        data = snap.to_dict()
        all_data.append(data)
        total += 1
        decision = data.get("decision", "")
        if decision == "auto_approved":
            auto_approved += 1
        elif decision == "escalated":
            escalated += 1
        elif decision == "rejected":
            rejected += 1

    citation_counts = _count_citations(all_data)
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
