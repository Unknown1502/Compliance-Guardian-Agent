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
                     - It can control ACCESS. It can never alter RECORDS.
                       The single cross-tenant write is suspending or
                       restoring a workspace's access; there is no path here
                       that changes a document, a verdict, or an audit entry.
                       A console able to rewrite compliance history would be a
                       liability in a product whose whole claim is that
                       history cannot be rewritten — but one unable to stop an
                       abusive or non-paying tenant is merely incomplete.
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
from api_gateway.composition import RULESETS_ROOT
from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from pydantic import BaseModel, Field
from schema_validators import RulesetNotFoundError, load_ruleset

logger = logging.getLogger("cg.gateway.admin")


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


# Same tokens the ruleset loader accepts. Constrained here so a crafted value
# is a clean 422 rather than something that reaches the filesystem at all.
_RULESET_TOKEN_PATTERN = r"^[a-z0-9_-]{1,64}$"


class ChangeJurisdictionRequest(BaseModel):
    model_config = {"extra": "forbid"}

    industry: str = Field(pattern=_RULESET_TOKEN_PATTERN)
    jurisdiction: str = Field(pattern=_RULESET_TOKEN_PATTERN)


class JurisdictionResponse(BaseModel):
    industry: str
    jurisdiction: str
    rule_set_version: str
    rule_count: int
    # False when the request named the pair already in force, so the client
    # can say "no change" instead of claiming a move that did not happen.
    changed: bool


class ChangeTenantStatusRequest(BaseModel):
    model_config = {"extra": "forbid"}

    status: str = Field(pattern="^(active|suspended)$")
    # Required, and required to be substantial. An operator who cannot say
    # why in twelve characters has not decided yet, and the reason is shown
    # to the customer at sign-in.
    reason: str = Field(min_length=12, max_length=300)


class TenantStatusResponse(BaseModel):
    tenant_id: str
    name: str
    status: str
    status_reason: str
    changed: bool


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
    # active | suspended. Access state, not compliance state — a suspended
    # workspace keeps every document and verdict it ever produced.
    status: str = "active"
    status_reason: str = ""
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



class PlatformDocumentRow(BaseModel):
    tenant_id: str
    tenant_name: str
    document_id: str
    filename: str
    status: str
    created_at: str
    risk_score: int | None = None
    decision: str | None = None
    citations: list[str] = []


class PlatformReviewRow(BaseModel):
    tenant_id: str
    tenant_name: str
    check_id: str
    document_id: str
    risk_score: int
    citations: list[str]
    assigned_to: str | None
    comments: int
    created_at: str
    age_hours: float


class AgentHealth(BaseModel):
    """Derived from the audit trail, which records every agent success and
    failure. Latency and queue depth are NOT recorded anywhere, so they are
    reported as unavailable rather than estimated."""

    agent: str
    succeeded: int
    failed: int
    success_rate: float | None
    last_seen: str | None
    latency_ms: None = None
    queue_depth: None = None


class ServiceStatus(BaseModel):
    service: str
    status: str  # healthy | degraded | unavailable | unknown
    detail: str


class PlatformSecurityEvent(BaseModel):
    created_at: str
    tenant_id: str
    actor: str
    action: str
    category: str


class PlatformRule(BaseModel):
    id: str
    description: str
    check_type: str
    severity: str
    # The parameter NAMES a rule evaluates on — never the values, which are
    # tenant data. Enough to see what a rule inspects without reading anyone's
    # documents from the control plane.
    params: list[str]


class PlatformRuleset(BaseModel):
    industry: str
    jurisdiction: str
    rule_set_version: str
    rule_count: int
    required_fields: list[str]
    severity_counts: dict[str, int]
    check_type_counts: dict[str, int]
    # How many workspaces this ruleset actually governs. A ruleset nobody is
    # assigned to is maintenance cost with no customer behind it, and that is
    # invisible without this number.
    tenants_assigned: int
    rules: list[PlatformRule]


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

    @router.put("/admin/jurisdiction", response_model=JurisdictionResponse)
    def change_jurisdiction(
        req: ChangeJurisdictionRequest,
        auth: AuthContext = Depends(require_role("owner", "admin")),
    ) -> JurisdictionResponse:
        """Move a workspace to a different industry / jurisdiction.

        Exists because the pair was previously fixed at signup with no way to
        change it, so a business that picked wrong — or expanded into another
        market — had to abandon the workspace and its entire audit history.

        Owner and admin, stated explicitly rather than written as
        require_role("owner"): 'admin' implicitly satisfies every role check
        in this codebase, so the narrower spelling would read as owner-only
        while behaving identically. Allowing admin is also consistent — an
        admin can already approve and reject compliance decisions, so which
        ruleset those decisions cite is not a larger power than they hold.

        Two properties worth stating explicitly:

          * The pair is validated by actually loading the ruleset before
            anything is written, so a workspace can never be left pointing at
            rules that do not exist.
          * Past checks are NOT re-evaluated. Every completed verdict stays
            cited to the ruleset that was genuinely applied at the time, which
            is the only honest thing an audit trail can do. The change is
            recorded as its own event, so the trail shows precisely when the
            applicable rules changed and who changed them.
        """
        g = gw()
        tenant = g.repo.get_tenant(auth.tenant_id)
        before = (tenant.industry, tenant.jurisdiction)
        # Case-insensitive, because rulesets on disk are lowercase (au.yaml)
        # while tenants created before this endpoint stored "AU". Comparing
        # raw values would treat a genuine no-op as a change and write an
        # audit event saying the jurisdiction moved when it did not.
        unchanged = (before[0].lower(), before[1].lower()) == (
            req.industry.lower(),
            req.jurisdiction.lower(),
        )

        try:
            ruleset = load_ruleset(RULESETS_ROOT, req.industry, req.jurisdiction)
        except (RulesetNotFoundError, ValueError) as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"no ruleset for industry={req.industry!r} "
                    f"jurisdiction={req.jurisdiction!r}"
                ),
            ) from exc

        if unchanged:
            # Not an error, but nothing happened — do not write a misleading
            # audit event saying the jurisdiction changed when it did not.
            return JurisdictionResponse(
                industry=tenant.industry,
                jurisdiction=tenant.jurisdiction,
                rule_set_version=ruleset.rule_set_version,
                rule_count=len(ruleset.rules),
                changed=False,
            )

        tenant.industry = req.industry
        tenant.jurisdiction = req.jurisdiction
        g.repo.upsert_tenant(tenant)
        g.auditor.log(
            tenant_id=auth.tenant_id,
            actor=auth.email or auth.uid,
            action="workspace.jurisdiction_changed",
            # Keyed on the destination so a double-submit collapses, but a
            # genuine later change back is still its own event.
            dedup_key=f"{req.industry}/{req.jurisdiction}",
            before_state={"industry": before[0], "jurisdiction": before[1]},
            after_state={
                "industry": req.industry,
                "jurisdiction": req.jurisdiction,
                "rule_set_version": ruleset.rule_set_version,
            },
        )
        logger.info(
            "tenant %s moved from %s/%s to %s/%s by %s",
            auth.tenant_id,
            before[0],
            before[1],
            req.industry,
            req.jurisdiction,
            auth.uid,
        )
        return JurisdictionResponse(
            industry=req.industry,
            jurisdiction=req.jurisdiction,
            rule_set_version=ruleset.rule_set_version,
            rule_count=len(ruleset.rules),
            changed=True,
        )

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
                    status=t.status.value if hasattr(t.status, "value") else str(t.status),
                    status_reason=t.status_reason,
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

    # -----------------------------------------------------------------------
    # Platform: documents, reviews, agents, compliance, security, system.
    # Everything below is computed from data the product actually stores. Where
    # a metric genuinely is not recorded anywhere (latency, queue depth,
    # managed-service internals), it is reported as unavailable instead of
    # being estimated — a fabricated ops number is worse than a blank.
    # -----------------------------------------------------------------------

    @router.get("/platform/documents", response_model=list[PlatformDocumentRow])
    def platform_documents(
        limit: int = Query(default=100, ge=1, le=500),
        auth: AuthContext = Depends(require_platform_admin),
    ) -> list[PlatformDocumentRow]:
        """Documents across every tenant, newest first."""
        g = gw()
        _audit_platform_access(g, auth, "platform.documents_viewed", {"limit": limit})

        rows: list[PlatformDocumentRow] = []
        for t in g.repo.list_all_tenants(limit=_MAX_TENANTS_SCANNED):
            docs = g.repo.list_documents(t.tenant_id, limit=200)
            checks = {c.document_id: c for c in g.repo.list_checks(t.tenant_id, limit=200)}
            for d in docs:
                chk = checks.get(d.document_id)
                rows.append(
                    PlatformDocumentRow(
                        tenant_id=t.tenant_id,
                        tenant_name=t.name,
                        document_id=d.document_id,
                        filename=getattr(d, "filename", "") or "",
                        status=getattr(d.status, "value", str(d.status)),
                        created_at=_iso(d.created_at),
                        risk_score=chk.risk_score if chk else None,
                        decision=getattr(chk.decision, "value", str(chk.decision)) if chk else None,
                        citations=list(chk.citations) if chk else [],
                    )
                )
        rows.sort(key=lambda r: r.created_at, reverse=True)
        return rows[:limit]

    @router.get("/platform/reviews", response_model=list[PlatformReviewRow])
    def platform_reviews(
        auth: AuthContext = Depends(require_platform_admin),
    ) -> list[PlatformReviewRow]:
        """Open escalations across every tenant, highest risk first."""
        g = gw()
        _audit_platform_access(g, auth, "platform.reviews_viewed", {})

        now = datetime.now(timezone.utc)
        rows: list[PlatformReviewRow] = []
        for t in g.repo.list_all_tenants(limit=_MAX_TENANTS_SCANNED):
            for c in g.repo.list_escalated_checks(t.tenant_id, limit=200):
                created = c.created_at if isinstance(c.created_at, datetime) else now
                rows.append(
                    PlatformReviewRow(
                        tenant_id=t.tenant_id,
                        tenant_name=t.name,
                        check_id=c.check_id,
                        document_id=c.document_id,
                        risk_score=c.risk_score,
                        citations=list(c.citations),
                        assigned_to=getattr(c, "assigned_to", None),
                        comments=len(getattr(c, "comments", None) or []),
                        created_at=_iso(c.created_at),
                        age_hours=round((now - created).total_seconds() / 3600, 1),
                    )
                )
        rows.sort(key=lambda r: r.risk_score, reverse=True)
        return rows

    @router.get("/platform/agents", response_model=list[AgentHealth])
    def platform_agents(
        auth: AuthContext = Depends(require_platform_admin),
    ) -> list[AgentHealth]:
        """Agent success/failure from the audit trail.

        Every agent writes a success action and a distinct failure action, so
        success rate is a real measurement, not a guess. Latency and queue
        depth are not recorded and stay null.
        """
        from gcp_clients import audit_dataset, audit_table, project_id

        from google.cloud import bigquery

        g = gw()
        _audit_platform_access(g, auth, "platform.agents_viewed", {})

        table = f"{project_id()}.{audit_dataset()}.{audit_table()}"
        query = (
            f"SELECT actor, action, COUNT(*) AS n, MAX(created_at) AS last_seen "  # noqa: S608
            f"FROM `{table}` GROUP BY actor, action"
        )
        stats: dict[str, dict] = {}
        for r in g.bq.query(query).result():
            actor = str(r["actor"])
            if not any(k in actor for k in ("agent", "orchestrator", "service")):
                continue
            entry = stats.setdefault(
                actor, {"succeeded": 0, "failed": 0, "last_seen": None}
            )
            action = str(r["action"])
            n = int(r["n"])
            if "fail" in action:
                entry["failed"] += n
            else:
                entry["succeeded"] += n
            seen = _iso(r["last_seen"])
            if entry["last_seen"] is None or seen > entry["last_seen"]:
                entry["last_seen"] = seen

        out: list[AgentHealth] = []
        for actor, e in sorted(stats.items()):
            total = e["succeeded"] + e["failed"]
            out.append(
                AgentHealth(
                    agent=actor,
                    succeeded=e["succeeded"],
                    failed=e["failed"],
                    success_rate=round(e["succeeded"] / total, 4) if total else None,
                    last_seen=e["last_seen"],
                )
            )
        return out

    @router.get("/platform/compliance")
    def platform_compliance(
        auth: AuthContext = Depends(require_platform_admin),
    ) -> dict:
        """Rule and ruleset intelligence across the platform.

        Rulesets are read from the repository files that actually drive
        evaluation, so this cannot drift from what the engine uses.
        """
        from pathlib import Path as _Path

        from schema_validators import load_ruleset_file

        g = gw()
        _audit_platform_access(g, auth, "platform.compliance_viewed", {})

        rule_hits: dict[str, int] = {}
        risk_buckets = {"low": 0, "medium": 0, "high": 0}
        by_tenant_risk: list[dict] = []
        jurisdictions: dict[str, int] = {}

        for t in g.repo.list_all_tenants(limit=_MAX_TENANTS_SCANNED):
            jurisdictions[t.jurisdiction] = jurisdictions.get(t.jurisdiction, 0) + 1
            checks = g.repo.list_checks(t.tenant_id, limit=500)
            if not checks:
                continue
            scores = [c.risk_score for c in checks]
            for s in scores:
                if s >= 60:
                    risk_buckets["high"] += 1
                elif s >= 30:
                    risk_buckets["medium"] += 1
                else:
                    risk_buckets["low"] += 1
            for c in checks:
                for cite in c.citations:
                    rule_hits[cite] = rule_hits.get(cite, 0) + 1
            by_tenant_risk.append(
                {
                    "tenant_id": t.tenant_id,
                    "name": t.name,
                    "checks": len(checks),
                    "avg_risk": round(sum(scores) / len(scores), 1),
                }
            )

        by_tenant_risk.sort(key=lambda r: r["avg_risk"], reverse=True)

        rulesets: list[dict] = []
        root = _Path(RULESETS_ROOT)
        if root.is_dir():
            for path in sorted(root.glob("*/*.yaml")):
                try:
                    rs = load_ruleset_file(path)
                except Exception:
                    continue
                rulesets.append(
                    {
                        "industry": rs.industry,
                        "jurisdiction": rs.jurisdiction,
                        "version": rs.rule_set_version,
                        "rules": len(rs.rules),
                    }
                )

        return {
            "risk_distribution": risk_buckets,
            "top_rules": sorted(
                [{"rule_id": k, "hits": v} for k, v in rule_hits.items()],
                key=lambda r: r["hits"],
                reverse=True,
            )[:20],
            "highest_risk_tenants": by_tenant_risk[:20],
            "jurisdictions": jurisdictions,
            "rulesets": rulesets,
        }

    @router.get("/platform/security", response_model=list[PlatformSecurityEvent])
    def platform_security(
        limit: int = Query(default=200, ge=1, le=500),
        auth: AuthContext = Depends(require_platform_admin),
    ) -> list[PlatformSecurityEvent]:
        """Security-relevant events, drawn from the same append-only trail.

        Only actions the system genuinely records are surfaced. Nothing here
        is inferred, and no secret ever appears: the trail stores action names
        and identifiers, never credentials.
        """
        from gcp_clients import audit_dataset, audit_table, project_id

        from google.cloud import bigquery

        g = gw()
        _audit_platform_access(g, auth, "platform.security_viewed", {"limit": limit})

        table = f"{project_id()}.{audit_dataset()}.{audit_table()}"
        query = (
            f"SELECT created_at, tenant_id, actor, action FROM `{table}` "  # noqa: S608
            f"WHERE action LIKE '%fail%' OR action LIKE '%denied%' "
            f"OR action LIKE '%revoked%' OR action LIKE '%api_key%' "
            f"OR action LIKE '%platform.%' OR action LIKE '%team.%' "
            f"OR action LIKE '%settings.%' "
            f"ORDER BY created_at DESC LIMIT @limit"
        )
        job = g.bq.query(
            query,
            job_config=bigquery.QueryJobConfig(
                query_parameters=[bigquery.ScalarQueryParameter("limit", "INT64", limit)]
            ),
        )

        def categorize(action: str) -> str:
            if "fail" in action or "denied" in action:
                return "failure"
            if "api_key" in action:
                return "credential"
            if action.startswith("platform."):
                return "privileged access"
            if action.startswith("team.") or action.startswith("settings."):
                return "configuration"
            return "other"

        return [
            PlatformSecurityEvent(
                created_at=_iso(r["created_at"]),
                tenant_id=str(r["tenant_id"]),
                actor=str(r["actor"]),
                action=str(r["action"]),
                category=categorize(str(r["action"])),
            )
            for r in job.result()
        ]

    @router.put("/platform/tenants/{tenant_id}/status", response_model=TenantStatusResponse)
    def change_tenant_status(
        req: ChangeTenantStatusRequest,
        tenant_id: str = Path(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$"),
        auth: AuthContext = Depends(require_platform_admin),
    ) -> TenantStatusResponse:
        """Suspend or restore a workspace's access to the platform.

        The only write on this console, and deliberately narrow. It controls
        ACCESS and nothing else: a suspended workspace cannot sign in and its
        API keys stop working, but not one document, verdict or audit record
        is altered. Everything the customer produced is exactly where they
        left it, and is returned intact on reactivation.

        That line is the point. An operator console that can rewrite a
        customer's compliance history is a liability in a product whose whole
        claim is that history cannot be rewritten. An operator console that
        cannot stop an abusive or non-paying tenant is merely incomplete. So
        this exists, and nothing broader does.

        A reason is mandatory and is shown to the customer at sign-in, so it
        has to be something a person can act on. It is also written to the
        append-only trail with the operator's identity — suspending someone
        is exactly the kind of action that should be impossible to do quietly.
        """
        from schema_validators import TenantStatus

        g = gw()
        tenant = g.repo.get_tenant(tenant_id)
        before = tenant.status.value if hasattr(tenant.status, "value") else str(tenant.status)

        if before == req.status:
            # Not an error, but nothing happened — do not write an audit entry
            # claiming a change that did not occur.
            return TenantStatusResponse(
                tenant_id=tenant.tenant_id,
                name=tenant.name,
                status=before,
                status_reason=tenant.status_reason,
                changed=False,
            )

        tenant.status = TenantStatus(req.status)
        tenant.status_reason = req.reason if req.status == "suspended" else ""
        g.repo.upsert_tenant(tenant)

        g.auditor.log(
            tenant_id=tenant_id,
            actor=f"operator:{auth.email or auth.uid}",
            action="tenant.suspended" if req.status == "suspended" else "tenant.reactivated",
            # Timestamped, so suspending and restoring the same workspace
            # twice produces two events rather than collapsing into one.
            dedup_key=f"{req.status}:{datetime.now(timezone.utc).isoformat()}",
            before_state={"status": before},
            after_state={"status": req.status, "reason": tenant.status_reason},
        )
        logger.warning(
            "tenant %s %s by %s: %s",
            tenant_id,
            req.status,
            auth.uid,
            req.reason,
        )
        return TenantStatusResponse(
            tenant_id=tenant.tenant_id,
            name=tenant.name,
            status=req.status,
            status_reason=tenant.status_reason,
            changed=True,
        )

    @router.get("/platform/rulesets", response_model=list[PlatformRuleset])
    def platform_rulesets(
        auth: AuthContext = Depends(require_platform_admin),
    ) -> list[PlatformRuleset]:
        """Every ruleset the engine can load, down to the individual rule.

        Read from the same YAML files the compliance agent evaluates against,
        via the same loader — so this cannot drift from what actually runs. A
        control plane that reports a rule the engine does not apply is worse
        than one that reports nothing.

        Rule params are surfaced as NAMES only. The names say what a rule
        inspects (record_retention_date, consent_record); the values are
        tenant documents and have no business being readable from a
        cross-tenant console.

        A malformed ruleset is omitted rather than failing the request —
        available_rulesets() already skips files that will not parse, which
        means this list is exactly the set the engine can use.
        """
        from collections import Counter

        from schema_validators import available_rulesets, load_ruleset

        g = gw()
        _audit_platform_access(g, auth, "platform.rulesets_viewed", {})

        # One pass over tenants, so assignment counts do not cost a query per
        # ruleset. Case-insensitive: tenants created before the jurisdiction
        # picker stored "AU" while the files are lowercase ("au.yaml").
        assigned: Counter[tuple[str, str]] = Counter()
        try:
            for t in g.repo.list_all_tenants(limit=1000):
                assigned[(t.industry.lower(), t.jurisdiction.lower())] += 1
        except Exception:
            logger.exception("could not count ruleset assignment")

        out: list[PlatformRuleset] = []
        for option in available_rulesets(RULESETS_ROOT):
            try:
                ruleset = load_ruleset(RULESETS_ROOT, option.industry, option.jurisdiction)
            except Exception:
                logger.warning(
                    "ruleset %s/%s listed but failed to load",
                    option.industry,
                    option.jurisdiction,
                )
                continue
            out.append(
                PlatformRuleset(
                    industry=option.industry,
                    jurisdiction=option.jurisdiction,
                    rule_set_version=ruleset.rule_set_version,
                    rule_count=len(ruleset.rules),
                    required_fields=list(ruleset.required_fields),
                    severity_counts=dict(Counter(r.severity.value for r in ruleset.rules)),
                    check_type_counts=dict(Counter(r.check_type.value for r in ruleset.rules)),
                    tenants_assigned=assigned.get(
                        (option.industry.lower(), option.jurisdiction.lower()), 0
                    ),
                    rules=[
                        PlatformRule(
                            id=r.id,
                            description=r.description,
                            check_type=r.check_type.value,
                            severity=r.severity.value,
                            params=sorted(r.params.keys()),
                        )
                        for r in ruleset.rules
                    ],
                )
            )
        return out

    @router.get("/platform/system", response_model=list[ServiceStatus])
    def platform_system(
        auth: AuthContext = Depends(require_platform_admin),
    ) -> list[ServiceStatus]:
        """Dependency status, measured rather than assumed.

        Firestore, BigQuery and Cloud Storage are probed with a real, cheap
        call. Cloud Run agents, Cloud Tasks, Workflows and Scheduler are not
        reachable from inside this request without extra IAM and the Monitoring
        API, so they report 'unknown' with the reason stated — the spec's rule
        is to show a metric as unavailable rather than fabricate it.
        """
        g = gw()
        _audit_platform_access(g, auth, "platform.system_viewed", {})

        out: list[ServiceStatus] = [
            ServiceStatus(service="API Gateway", status="healthy", detail="serving this request")
        ]

        try:
            next(iter(g.db.collection("tenants").limit(1).stream()), None)
            out.append(ServiceStatus(service="Firestore", status="healthy", detail="read succeeded"))
        except Exception as exc:
            out.append(
                ServiceStatus(service="Firestore", status="unavailable", detail=str(exc)[:160])
            )

        try:
            from gcp_clients import audit_dataset, audit_table, project_id

            table = f"{project_id()}.{audit_dataset()}.{audit_table()}"
            next(iter(g.bq.query(f"SELECT 1 FROM `{table}` LIMIT 1").result()), None)  # noqa: S608
            out.append(ServiceStatus(service="BigQuery", status="healthy", detail="query succeeded"))
        except Exception as exc:
            out.append(
                ServiceStatus(service="BigQuery", status="unavailable", detail=str(exc)[:160])
            )

        try:
            from gcp_clients import raw_docs_bucket

            # Deliberately an OBJECT-level call. bucket.exists() needs
            # storage.buckets.get, which the runtime service account does not
            # hold (it has objectAdmin, by least privilege). Probing with
            # exists() therefore returned 403 and reported Cloud Storage as
            # unavailable while uploads were working perfectly — a false alarm
            # that made the health page actively misleading. Listing one object
            # exercises the permission the product actually depends on.
            next(iter(g.storage.bucket(raw_docs_bucket()).list_blobs(max_results=1)), None)
            out.append(
                ServiceStatus(
                    service="Cloud Storage", status="healthy", detail="object listing succeeded"
                )
            )
        except Exception as exc:
            out.append(
                ServiceStatus(service="Cloud Storage", status="unavailable", detail=str(exc)[:160])
            )

        # Agent status from the audit trail rather than a probe. Each agent
        # writes a distinct success and failure action, so recent activity is a
        # real signal: failures present means degraded, successes only means
        # healthy, silence means we genuinely do not know.
        agent_actors = {
            "Ingestion Agent": "ingestion-agent",
            "Compliance Agent": "compliance-agent",
            "Reporting Agent": "reporting-agent",
            "Escalation Service": "escalation-service",
        }
        try:
            from gcp_clients import audit_dataset, audit_table, project_id

            table = f"{project_id()}.{audit_dataset()}.{audit_table()}"
            rows = list(
                g.bq.query(
                    f"SELECT actor, "  # noqa: S608
                    f"COUNTIF(action LIKE '%fail%') AS failed, "
                    f"COUNTIF(action NOT LIKE '%fail%') AS ok, "
                    f"MAX(created_at) AS last_seen "
                    f"FROM `{table}` "
                    f"WHERE created_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR) "
                    f"GROUP BY actor"
                ).result()
            )
            recent = {str(r["actor"]): r for r in rows}
        except Exception:
            recent = {}

        for label, actor in agent_actors.items():
            r = recent.get(actor)
            if r is None:
                out.append(
                    ServiceStatus(
                        service=label,
                        status="unknown",
                        detail="No activity in the last 24h - nothing to measure",
                    )
                )
                continue
            failed = int(r["failed"] or 0)
            ok = int(r["ok"] or 0)
            if failed and ok:
                status, detail = "degraded", f"{ok} succeeded, {failed} failed in 24h"
            elif failed:
                status, detail = "unavailable", f"{failed} failed, none succeeded in 24h"
            else:
                status, detail = "healthy", f"{ok} succeeded in 24h, no failures"
            out.append(ServiceStatus(service=label, status=status, detail=detail))

        # No data source reaches these from inside a request, and inventing a
        # status for infrastructure is worse than admitting the gap.
        for name in ("Cloud Tasks", "Cloud Workflows", "Cloud Scheduler"):
            out.append(
                ServiceStatus(
                    service=name,
                    status="unknown",
                    detail="Not measured - requires the Cloud Monitoring API",
                )
            )
        return out

    @router.get("/platform/whoami")
    def platform_whoami(auth: AuthContext = Depends(require_platform_admin)) -> dict:
        """Cheap probe the console uses to decide whether to render at all."""
        return {"uid": auth.uid, "email": auth.email or "", "platform_admin": True}

    return router
