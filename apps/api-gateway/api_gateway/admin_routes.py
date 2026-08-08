"""Admin surfaces — two of them, deliberately separate.

  /api/admin/*     Tenant admin. Everything about ONE workspace, scoped by the
                   caller's own tenant_id exactly like every other endpoint.
                   Owner/admin role. No change to the isolation model.

  /api/platform/*  Platform admin. Cross-tenant, for whoever operates the
                   service. This is the only place in the product that reads
                   across tenants, so it is fenced accordingly:

                     - Access comes from an environment allowlist
                       (CG_PLATFORM_ADMIN_UIDS), never from a role. Roles are
                       handed out by POST /api/team, so a "founder" role could
                       be minted by any tenant owner inviting themselves.
                     - Read-only. There is no cross-tenant write path here at
                       all, so the console cannot alter a customer's records.
                     - Every request is written to the append-only audit trail
                       before the data is returned. The product's promise is
                       that every access is accountable; the operator's own
                       access is not an exception to that.
                     - Non-admins get 404, not 403 — a 403 confirms the route
                       exists to anyone probing for it.

Built as a router factory rather than more routes in main.py: main.py is
already large, and this keeps the cross-tenant code in one auditable file.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from auth_middleware import (
    AuthContext,
    require_auth,
    require_platform_admin,
    require_role,
)
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

logger = logging.getLogger("cg.gateway.admin")


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class TenantAdminOverview(BaseModel):
    tenant_id: str
    name: str
    industry: str
    jurisdiction: str
    plan_tier: str
    created_at: str

    documents_total: int
    documents_by_status: dict[str, int]

    checks_total: int
    checks_auto_approved: int
    checks_escalated: int
    checks_rejected: int
    open_escalations: int

    members_total: int
    members_by_role: dict[str, int]
    api_keys_active: int

    top_failing_rules: list[str]
    slack_configured: bool
    retention_days: int


class RemediationItemOut(BaseModel):
    rule_id: str
    title: str
    action: str
    blocking: bool
    estimated_minutes: int
    severity: str


class RemediationPlanOut(BaseModel):
    plan_id: str
    check_id: str
    document_id: str
    items: list[RemediationItemOut]
    total_estimated_minutes: int
    used_fixture: bool
    created_at: str


class PlatformTenantRow(BaseModel):
    tenant_id: str
    name: str
    industry: str
    jurisdiction: str
    plan_tier: str
    created_at: str
    members: int
    documents: int
    checks: int
    open_escalations: int


class PlatformOverview(BaseModel):
    generated_at: str
    tenants_total: int
    tenants_by_plan: dict[str, int]
    members_total: int
    documents_total: int
    checks_total: int
    checks_auto_approved: int
    checks_escalated: int
    checks_rejected: int
    open_escalations_total: int
    signups_last_7d: int
    signups_last_30d: int
    tenants: list[PlatformTenantRow]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Firestore reads cost per document, and these views fan out across a whole
# tenant (or every tenant). Caps keep one dashboard load from turning into an
# unbounded bill; the counts they produce are labelled as "up to" in the UI.
_MAX_DOCS_SCANNED = 2000
_MAX_TENANTS_SCANNED = 500


def _count_by(items, attr: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for it in items:
        raw = getattr(it, attr, "")
        key = getattr(raw, "value", raw)  # unwrap enums
        key = str(key or "unknown")
        out[key] = out.get(key, 0) + 1
    return out


def _iso(value) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value or "")


def _tenant_check_stats(db, tenant_id: str) -> dict:
    """All-time check aggregate for one tenant, reusing the shared analytics."""
    from analytics import aggregate_period

    # A window wide enough to mean "all time" for this product's lifetime,
    # using the same range-query shape the reporting agent already relies on.
    start = datetime(2000, 1, 1, tzinfo=timezone.utc)
    end = datetime.now(timezone.utc) + timedelta(days=1)
    return aggregate_period(db, tenant_id=tenant_id, period_start=start, period_end=end)


def build_admin_router(gw) -> APIRouter:
    """Create the admin router.

    `gw` is the gateway accessor, injected rather than imported so this module
    does not import main.py (which imports this one).
    """
    router = APIRouter()

    # -----------------------------------------------------------------------
    # Tenant admin — one workspace, ordinary tenant scoping.
    # -----------------------------------------------------------------------

    @router.get("/admin/overview", response_model=TenantAdminOverview)
    def tenant_admin_overview(
        auth: AuthContext = Depends(require_role("owner", "admin")),
    ) -> TenantAdminOverview:
        """Everything about the caller's own workspace, in one request.

        tenant_id comes from the verified JWT, so this is the same isolation
        guarantee as every other endpoint — an admin of one tenant learns
        nothing about another.
        """
        g = gw()
        tenant = g.repo.get_tenant(auth.tenant_id)
        documents = g.repo.list_documents(auth.tenant_id, limit=_MAX_DOCS_SCANNED)
        members = g.repo.list_users(auth.tenant_id, limit=500)
        keys = g.repo.list_api_keys(auth.tenant_id, limit=200)
        escalations = g.repo.list_escalated_checks(auth.tenant_id, limit=500)
        stats = _tenant_check_stats(g.db, auth.tenant_id)

        return TenantAdminOverview(
            tenant_id=tenant.tenant_id,
            name=tenant.name,
            industry=tenant.industry,
            jurisdiction=tenant.jurisdiction,
            plan_tier=getattr(tenant.plan_tier, "value", str(tenant.plan_tier)),
            created_at=_iso(tenant.created_at),
            documents_total=len(documents),
            documents_by_status=_count_by(documents, "status"),
            checks_total=stats.get("total_checks", 0),
            checks_auto_approved=stats.get("auto_approved", 0),
            checks_escalated=stats.get("escalated", 0),
            checks_rejected=stats.get("rejected", 0),
            open_escalations=len(escalations),
            members_total=len(members),
            members_by_role=_count_by(members, "role"),
            api_keys_active=sum(1 for k in keys if not getattr(k, "revoked", False)),
            top_failing_rules=stats.get("top_failing_rule_ids", []),
            slack_configured=bool(getattr(tenant, "slack_webhook_url", "")),
            retention_days=getattr(tenant, "retention_days", 0),
        )

    @router.get(
        "/checks/{check_id}/remediation", response_model=RemediationPlanOut
    )
    def get_remediation_plan(
        check_id: str,
        auth: AuthContext = Depends(require_auth),
    ) -> RemediationPlanOut:
        """The fix list for one compliance check.

        Any member of the tenant can read it — the people who act on a
        remediation plan are usually the operations staff, not the owner.
        The lookup is tenant-scoped, so another tenant's plan is a 404.
        """
        from fastapi import HTTPException, status

        g = gw()
        plan = g.repo.get_remediation_plan_for_check(check_id, auth.tenant_id)
        if plan is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="not found"
            )
        return RemediationPlanOut(
            plan_id=plan.plan_id,
            check_id=plan.check_id,
            document_id=plan.document_id,
            items=[
                RemediationItemOut(
                    rule_id=i.rule_id,
                    title=i.title,
                    action=i.action,
                    blocking=i.blocking,
                    estimated_minutes=i.estimated_minutes,
                    severity=i.severity,
                )
                for i in plan.items
            ],
            total_estimated_minutes=plan.total_estimated_minutes,
            used_fixture=plan.used_fixture,
            created_at=_iso(plan.created_at),
        )

    # -----------------------------------------------------------------------
    # Platform admin — cross-tenant, allowlisted, read-only, audited.
    # -----------------------------------------------------------------------

    def _audit_platform_access(g, auth: AuthContext, action: str, detail: dict) -> None:
        """Record an operator's cross-tenant read.

        Written before the response is returned, and failures are swallowed:
        the audit attempt must not become a way to probe whether the endpoint
        works, and an audit outage must not silently drop the record without
        a log line.
        """
        try:
            g.auditor.log(
                tenant_id="__platform__",
                actor=auth.uid,
                action=action,
                dedup_key=f"{auth.uid}:{action}:{datetime.now(timezone.utc).isoformat()}",
                before_state=None,
                after_state={"actor_email": auth.email or "", **detail},
            )
        except Exception:
            logger.exception("failed to audit platform access %s by %s", action, auth.uid)

    @router.get("/platform/overview", response_model=PlatformOverview)
    def platform_overview(
        limit: int = Query(default=100, ge=1, le=_MAX_TENANTS_SCANNED),
        auth: AuthContext = Depends(require_platform_admin),
    ) -> PlatformOverview:
        """Every tenant, with usage. The operator's view of the whole service."""
        g = gw()
        _audit_platform_access(g, auth, "platform.overview_viewed", {"limit": limit})

        tenants = g.repo.list_all_tenants(limit=limit)
        now = datetime.now(timezone.utc)
        cutoff_7 = now - timedelta(days=7)
        cutoff_30 = now - timedelta(days=30)

        rows: list[PlatformTenantRow] = []
        totals = {
            "members": 0, "documents": 0, "checks": 0,
            "auto_approved": 0, "escalated": 0, "rejected": 0, "open_escalations": 0,
        }
        by_plan: dict[str, int] = {}
        signups_7 = signups_30 = 0

        for t in tenants:
            plan = getattr(t.plan_tier, "value", str(t.plan_tier))
            by_plan[plan] = by_plan.get(plan, 0) + 1

            created = t.created_at
            if isinstance(created, datetime):
                if created >= cutoff_7:
                    signups_7 += 1
                if created >= cutoff_30:
                    signups_30 += 1

            members = g.repo.list_users(t.tenant_id, limit=500)
            documents = g.repo.list_documents(t.tenant_id, limit=_MAX_DOCS_SCANNED)
            escalations = g.repo.list_escalated_checks(t.tenant_id, limit=500)
            stats = _tenant_check_stats(g.db, t.tenant_id)

            totals["members"] += len(members)
            totals["documents"] += len(documents)
            totals["checks"] += stats.get("total_checks", 0)
            totals["auto_approved"] += stats.get("auto_approved", 0)
            totals["escalated"] += stats.get("escalated", 0)
            totals["rejected"] += stats.get("rejected", 0)
            totals["open_escalations"] += len(escalations)

            rows.append(
                PlatformTenantRow(
                    tenant_id=t.tenant_id,
                    name=t.name,
                    industry=t.industry,
                    jurisdiction=t.jurisdiction,
                    plan_tier=plan,
                    created_at=_iso(t.created_at),
                    members=len(members),
                    documents=len(documents),
                    checks=stats.get("total_checks", 0),
                    open_escalations=len(escalations),
                )
            )

        rows.sort(key=lambda r: r.created_at, reverse=True)

        return PlatformOverview(
            generated_at=now.isoformat(),
            tenants_total=len(tenants),
            tenants_by_plan=by_plan,
            members_total=totals["members"],
            documents_total=totals["documents"],
            checks_total=totals["checks"],
            checks_auto_approved=totals["auto_approved"],
            checks_escalated=totals["escalated"],
            checks_rejected=totals["rejected"],
            open_escalations_total=totals["open_escalations"],
            signups_last_7d=signups_7,
            signups_last_30d=signups_30,
            tenants=rows,
        )

    @router.get("/platform/audit")
    def platform_audit(
        limit: int = Query(default=100, ge=1, le=500),
        auth: AuthContext = Depends(require_platform_admin),
    ) -> dict:
        """Recent audit events across every tenant — the operator decision log.

        Reads the append-only BigQuery trail directly. Unlike /api/audit-logs,
        this is not filtered to one tenant, which is exactly why reaching it
        requires the allowlist and why the read itself is audited.
        """
        from gcp_clients import audit_dataset, audit_table, project_id

        from google.cloud import bigquery

        g = gw()
        _audit_platform_access(g, auth, "platform.audit_viewed", {"limit": limit})

        table = f"{project_id()}.{audit_dataset()}.{audit_table()}"
        query = (
            f"SELECT event_id, tenant_id, actor, action, created_at "  # noqa: S608
            f"FROM `{table}` ORDER BY created_at DESC LIMIT @limit"
        )
        job = g.bq.query(
            query,
            job_config=bigquery.QueryJobConfig(
                query_parameters=[bigquery.ScalarQueryParameter("limit", "INT64", limit)]
            ),
        )
        events = [dict(r) for r in job.result()]
        return {"count": len(events), "events": events}

    @router.get("/platform/whoami")
    def platform_whoami(auth: AuthContext = Depends(require_platform_admin)) -> dict:
        """Cheap probe the console uses to decide whether to render at all."""
        return {"uid": auth.uid, "email": auth.email or "", "platform_admin": True}

    return router
