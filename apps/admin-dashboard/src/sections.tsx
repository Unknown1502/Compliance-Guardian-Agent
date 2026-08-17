// Console sections. Each one loads from the platform API and renders exactly
// what the backend returned — nothing is synthesised to fill a gap. Where a
// metric is not measured anywhere, the section says so rather than showing a
// zero that would read as a real measurement.

import { useCallback, useEffect, useMemo, useState } from "react";
import { useParams, Link } from "react-router-dom";
import {
  api,
  type Overview,
  type DocumentRow,
  type ReviewRow,
  type AgentHealth,
  type ServiceStatus,
  type SecurityEvent,
  type AuditEvent,
  type ComplianceIntel,
  type PlatformRuleset,
  type SupportTicketRow,
  type SupportPermissions,
  type PlatformUsersPage,
  type PlatformUserDetail,
  ApiError,
} from "./api";
import { useAuth } from "./auth";
import {
  Panel,
  Metric,
  Status,
  Risk,
  Distribution,
  Empty,
  Unavailable,
  Loading,
  ErrorNote,
  Mono,
  ago,
  cn,
  ConfirmAction,
} from "./ui";

/** Loads once, exposes refresh, and surfaces errors instead of hiding them. */
function useData<T>(fn: (t: () => Promise<string>) => Promise<T>) {
  const { getToken } = useAuth();
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(() => {
    setLoading(true);
    fn(getToken)
      .then((d) => {
        setData(d);
        setError(null);
      })
      .catch((e) => setError((e as Error).message))
      .finally(() => setLoading(false));
    // fn is a stable module-level reference in every call site here.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [getToken]);

  useEffect(load, [load]);
  return { data, error, loading, reload: load };
}

function Head({ title, sub, right }: { title: string; sub?: string; right?: React.ReactNode }) {
  return (
    <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
        {sub && <p className="mt-0.5 text-sm text-muted">{sub}</p>}
      </div>
      {right}
    </div>
  );
}

function Filter({
  value,
  onChange,
  placeholder,
}: {
  value: string;
  onChange: (v: string) => void;
  placeholder: string;
}) {
  return (
    <input
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder}
      className="w-64 border border-line bg-base px-2.5 py-1.5 text-sm text-fg placeholder:text-faint focus:border-accent focus:outline-none"
    />
  );
}

// ---------------------------------------------------------------- Overview

export function OverviewSection() {
  const { data, error, loading } = useData<Overview>(api.overview);
  const agents = useData<AgentHealth[]>(api.agents);

  if (loading) return <Loading />;
  if (error) return <ErrorNote error={error} />;
  if (!data) return null;

  const avgRisk = null; // Not aggregated server-side; see Compliance for the real distribution.
  const highRisk = data.checks_escalated;

  return (
    <div>
      <Head
        title="Overview"
        sub={`Platform state as of ${new Date(data.generated_at).toLocaleString()}`}
      />

      <div className="grid grid-cols-2 overflow-hidden rounded-xl border border-line bg-panel shadow-soft md:grid-cols-4">
        <Metric label="Tenants" value={data.tenants_total} hint={`${data.members_total} members`} />
        <Metric label="Documents" value={data.documents_total} />
        <Metric label="Checks" value={data.checks_total} />
        <Metric
          label="Open escalations"
          value={data.open_escalations_total}
          tone={data.open_escalations_total > 0 ? "warn" : "neutral"}
        />
      </div>

      <div className="mt-3 grid grid-cols-2 overflow-hidden rounded-xl border border-line bg-panel shadow-soft md:grid-cols-4">
        <Metric label="Auto-approved" value={data.checks_auto_approved} tone="ok" />
        <Metric label="Escalated" value={highRisk} tone={highRisk ? "warn" : "neutral"} />
        <Metric label="Rejected" value={data.checks_rejected} tone="crit" />
        <div className="px-3 py-2.5">
          <div className="label">Avg risk score</div>
          <div className="mt-1">
            {avgRisk === null ? (
              <Unavailable reason="Not aggregated by the API; see Compliance for the risk distribution." />
            ) : (
              avgRisk
            )}
          </div>
        </div>
      </div>

      <div className="mt-3 grid gap-3 lg:grid-cols-2">
        <Panel title="Decision distribution">
          <Distribution
            segments={[
              { label: "auto-approved", value: data.checks_auto_approved, cls: "bg-ok" },
              { label: "escalated", value: data.checks_escalated, cls: "bg-warn" },
              { label: "rejected", value: data.checks_rejected, cls: "bg-crit" },
            ]}
          />
        </Panel>

        <Panel title="Growth">
          <div className="grid grid-cols-2">
            <Metric label="Signups · 7d" value={data.signups_last_7d} />
            <Metric label="Signups · 30d" value={data.signups_last_30d} />
          </div>
        </Panel>
      </div>

      <Panel className="mt-3" title="Agent health">
        {agents.loading ? (
          <Loading />
        ) : agents.error ? (
          <ErrorNote error={agents.error} />
        ) : !agents.data?.length ? (
          <Empty>No agent activity recorded yet.</Empty>
        ) : (
          <AgentTable agents={agents.data} />
        )}
      </Panel>
    </div>
  );
}

// ----------------------------------------------------------------- Tenants

/**
 * Plan + entitlement badge.
 *
 * The distinction this exists to preserve: a customer who bought ONE report
 * is not a subscriber. Both have paid, both currently have allowance, and
 * conflating them would misreport revenue and mislead anyone reading the
 * console. plan_tier says what was bought; entitlement_source says what is
 * currently in force.
 */
function PlanBadge({ row }: { row: Overview["tenants"][number] }) {
  const src = row.entitlement_source;
  if (src === "pro") {
    return <span className="text-accent">PRO · monthly</span>;
  }
  if (src === "single") {
    return (
      <span>
        <span className="text-fg-dim">FREE</span>
        <span className="ml-1.5 border border-line px-1 py-0.5 text-2xs text-ok">SINGLE</span>
      </span>
    );
  }
  return <span className="text-muted">FREE</span>;
}

/** Reports used against granted, and whether anything is left. */
function ReportsCell({ row }: { row: Overview["tenants"][number] }) {
  const remaining = row.reports_granted - row.reports_consumed;
  return (
    <span className={cn("num", remaining <= 0 && "text-warn")}>
      {row.reports_consumed}/{row.reports_granted}
      {remaining <= 0 && <span className="ml-1.5 text-2xs">exhausted</span>}
    </span>
  );
}

export function TenantsSection() {
  const { getToken } = useAuth();
  const { data, error, loading, reload } = useData<Overview>(api.overview);
  const [q, setQ] = useState("");
  const [sort, setSort] = useState<keyof Overview["tenants"][number]>("created_at");

  // The console's only write. Access control, never record alteration.
  const [target, setTarget] = useState<Overview["tenants"][number] | null>(null);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  const suspending = target?.status !== "suspended";

  const applyStatus = async (reason: string) => {
    if (!target) return;
    setBusy(true);
    setActionError(null);
    try {
      await api.setTenantStatus(
        getToken,
        target.tenant_id,
        suspending ? "suspended" : "active",
        reason,
      );
      setTarget(null);
      reload();
    } catch (e) {
      setActionError(e instanceof ApiError ? e.message : (e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const rows = useMemo(() => {
    if (!data) return [];
    const needle = q.trim().toLowerCase();
    const filtered = needle
      ? data.tenants.filter((t) =>
          [t.name, t.tenant_id, t.industry, t.jurisdiction].some((v) =>
            String(v).toLowerCase().includes(needle),
          ),
        )
      : data.tenants;
    return [...filtered].sort((a, b) => {
      const av = a[sort];
      const bv = b[sort];
      if (typeof av === "number" && typeof bv === "number") return bv - av;
      return String(bv).localeCompare(String(av));
    });
  }, [data, q, sort]);

  if (loading) return <Loading />;
  if (error) return <ErrorNote error={error} />;

  return (
    <div>
      <Head
        title="Tenants"
        sub={`${rows.length} of ${data?.tenants_total ?? 0}`}
        right={<Filter value={q} onChange={setQ} placeholder="Filter tenants…" />}
      />
      <Panel>
        <div className="max-h-[70vh] overflow-auto">
          <table className="tbl">
            <thead>
              <tr>
                {(
                  [
                    ["name", "Tenant"],
                    ["industry", "Industry"],
                    ["jurisdiction", "Juris."],
                    ["plan_tier", "Plan"],
                    ["reports_consumed", "Reports"],
                    ["members", "Users"],
                    ["documents", "Docs"],
                    ["checks", "Checks"],
                    ["open_escalations", "Open"],
                    ["created_at", "Created"],
                  ] as const
                ).map(([key, label]) => (
                  <th
                    key={key}
                    onClick={() => setSort(key)}
                    className={cn("cursor-pointer select-none", sort === key && "text-accent")}
                  >
                    {label}
                  </th>
                ))}
                <th>Access</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((t) => (
                <tr key={t.tenant_id}>
                  <td>
                    <Link to={`/tenants/${t.tenant_id}`} className="text-accent hover:underline">
                      {t.name}
                    </Link>
                    <div>
                      <Mono dim>{t.tenant_id}</Mono>
                    </div>
                  </td>
                  <td className="text-fg-dim">{t.industry}</td>
                  <td className="text-fg-dim">{t.jurisdiction}</td>
                  <td className="whitespace-nowrap">
                    <PlanBadge row={t} />
                  </td>
                  <td>
                    <ReportsCell row={t} />
                  </td>
                  <td className="num">{t.members}</td>
                  <td className="num">{t.documents}</td>
                  <td className="num">{t.checks}</td>
                  <td className={cn("num", t.open_escalations > 0 && "text-warn")}>
                    {t.open_escalations}
                  </td>
                  <td className="text-faint">{ago(t.created_at)}</td>
                  <td className="whitespace-nowrap">
                    {t.status === "suspended" ? (
                      <span className="text-crit" title={t.status_reason}>
                        Suspended
                      </span>
                    ) : (
                      <span className="text-muted">Active</span>
                    )}
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        setActionError(null);
                        setTarget(t);
                      }}
                      className="ml-2 text-accent hover:underline"
                    >
                      {t.status === "suspended" ? "Restore" : "Suspend"}
                    </button>
                  </td>
                </tr>
              ))}
              {rows.length === 0 && (
                <tr>
                  <td colSpan={11}>
                    <Empty>No tenants match.</Empty>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </Panel>

      <ConfirmAction
        open={target !== null}
        intent={suspending ? "crit" : "ok"}
        title={
          suspending
            ? `Suspend ${target?.name ?? ""}`
            : `Restore access for ${target?.name ?? ""}`
        }
        confirmLabel={suspending ? "Suspend workspace" : "Restore access"}
        busy={busy}
        error={actionError}
        onCancel={() => setTarget(null)}
        onConfirm={applyStatus}
        reasonLabel={suspending ? "Why is this workspace being suspended?" : "Why is access being restored?"}
        reasonPlaceholder={
          suspending
            ? "Payment failed on three consecutive attempts."
            : "Payment received and cleared."
        }
        consequence={
          suspending ? (
            <>
              Everyone in this workspace will be signed out of the product and its API keys
              will stop working. {target?.members ?? 0} member
              {target?.members === 1 ? "" : "s"} affected.
            </>
          ) : (
            <>
              Members can sign in again immediately and API keys resume working. Everything is
              exactly as they left it.
            </>
          )
        }
        preserved={
          suspending ? (
            <>
              <strong className="text-fg">Nothing is deleted.</strong> All{" "}
              {target?.documents ?? 0} documents, {target?.checks ?? 0} checks and the entire
              audit trail are preserved untouched and return intact on restore. This controls
              access only — it cannot alter a record.
            </>
          ) : undefined
        }
      />
    </div>
  );
}

export function TenantDetailSection() {
  const { tenantId } = useParams<{ tenantId: string }>();
  const { data, error, loading } = useData<Overview>(api.overview);
  const docs = useData<DocumentRow[]>(api.documents);
  const reviews = useData<ReviewRow[]>(api.reviews);

  if (loading) return <Loading />;
  if (error) return <ErrorNote error={error} />;

  const tenant = data?.tenants.find((t) => t.tenant_id === tenantId);
  if (!tenant) return <ErrorNote error={`Tenant ${tenantId} not found in the current window.`} />;

  const tDocs = (docs.data ?? []).filter((d) => d.tenant_id === tenantId);
  const tReviews = (reviews.data ?? []).filter((r) => r.tenant_id === tenantId);

  return (
    <div>
      <Head
        title={tenant.name}
        sub={`${tenant.industry} · ${tenant.jurisdiction} · ${tenant.plan_tier}`}
        right={
          <Link to="/tenants" className="text-sm text-accent hover:underline">
            ← All tenants
          </Link>
        }
      />
      <div className="grid grid-cols-2 overflow-hidden rounded-xl border border-line bg-panel shadow-soft md:grid-cols-4">
        <Metric label="Users" value={tenant.members} />
        <Metric label="Documents" value={tenant.documents} />
        <Metric label="Checks" value={tenant.checks} />
        <Metric
          label="Open escalations"
          value={tenant.open_escalations}
          tone={tenant.open_escalations > 0 ? "warn" : "neutral"}
        />
      </div>

      <Panel className="mt-3" title={`Documents (${tDocs.length})`}>
        {docs.loading ? <Loading /> : <DocumentTable rows={tDocs} hideTenant />}
      </Panel>

      <Panel className="mt-3" title={`Open escalations (${tReviews.length})`}>
        {reviews.loading ? <Loading /> : <ReviewTable rows={tReviews} hideTenant />}
      </Panel>
    </div>
  );
}

// --------------------------------------------------------------- Documents

function DocumentActions({ doc }: { doc: DocumentRow }) {
  const { getToken } = useAuth();
  const [busy, setBusy] = useState<"extraction" | "check" | null>(null);
  const [result, setResult] = useState<string | null>(null);

  const run = async (kind: "extraction" | "check") => {
    const verb = kind === "extraction" ? "retry extraction for" : "re-run the compliance check for";
    if (!window.confirm(`Reprocess this document — ${verb} ${doc.filename || doc.document_id}?`)) {
      return;
    }
    setBusy(kind);
    setResult(null);
    try {
      const res =
        kind === "extraction"
          ? await api.retryExtraction(getToken, doc.document_id, doc.tenant_id)
          : await api.reanalyzeDocument(getToken, doc.document_id, doc.tenant_id);
      setResult(`Task ${res.task_id} dispatched`);
    } catch (e) {
      setResult(e instanceof ApiError ? e.message : (e as Error).message);
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="flex flex-col items-start gap-1">
      <div className="flex gap-2 whitespace-nowrap">
        <button
          onClick={() => run("extraction")}
          disabled={busy !== null}
          className="text-2xs text-accent hover:underline disabled:opacity-40"
        >
          {busy === "extraction" ? "Retrying…" : "Retry extraction"}
        </button>
        <span className="text-faint">·</span>
        <button
          onClick={() => run("check")}
          disabled={busy !== null}
          className="text-2xs text-accent hover:underline disabled:opacity-40"
        >
          {busy === "check" ? "Running…" : "Re-run analysis"}
        </button>
      </div>
      {result && <span className="text-2xs text-faint">{result}</span>}
    </div>
  );
}

function DocumentTable({ rows, hideTenant }: { rows: DocumentRow[]; hideTenant?: boolean }) {
  if (rows.length === 0) return <Empty>No documents.</Empty>;
  return (
    <div className="max-h-[70vh] overflow-auto">
      <table className="tbl">
        <thead>
          <tr>
            {!hideTenant && <th>Tenant</th>}
            <th>Document</th>
            <th>Status</th>
            <th>Risk</th>
            <th>Decision</th>
            <th>Rules cited</th>
            <th>Uploaded</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((d) => (
            <tr key={d.document_id}>
              {!hideTenant && <td className="text-fg-dim">{d.tenant_name}</td>}
              <td>
                <div className="text-fg-dim">{d.filename || "—"}</div>
                <Mono dim>{d.document_id}</Mono>
              </td>
              <td>
                <Status status={d.status} />
              </td>
              <td>
                <Risk score={d.risk_score} />
              </td>
              <td>{d.decision ? <Status status={d.decision} /> : <span className="text-faint">—</span>}</td>
              <td className="num text-fg-dim">{d.citations.length || "—"}</td>
              <td className="text-faint">{ago(d.created_at)}</td>
              <td>
                <DocumentActions doc={d} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function DocumentsSection() {
  const { data, error, loading } = useData<DocumentRow[]>(api.documents);
  const [q, setQ] = useState("");

  const rows = useMemo(() => {
    const needle = q.trim().toLowerCase();
    if (!needle) return data ?? [];
    return (data ?? []).filter((d) =>
      [d.tenant_name, d.document_id, d.filename, d.status, d.decision ?? ""].some((v) =>
        String(v).toLowerCase().includes(needle),
      ),
    );
  }, [data, q]);

  if (loading) return <Loading />;
  if (error) return <ErrorNote error={error} />;

  return (
    <div>
      <Head
        title="Documents"
        sub={`${rows.length} most recent across all tenants`}
        right={<Filter value={q} onChange={setQ} placeholder="Filter documents…" />}
      />
      <Panel>
        <DocumentTable rows={rows} />
      </Panel>
    </div>
  );
}

// ----------------------------------------------------------------- Reviews

function ReviewTable({ rows, hideTenant }: { rows: ReviewRow[]; hideTenant?: boolean }) {
  if (rows.length === 0) return <Empty>Nothing awaiting review.</Empty>;
  return (
    <div className="max-h-[70vh] overflow-auto">
      <table className="tbl">
        <thead>
          <tr>
            {!hideTenant && <th>Tenant</th>}
            <th>Risk</th>
            <th>Document</th>
            <th>Rules cited</th>
            <th>Assigned</th>
            <th>Notes</th>
            <th>Age</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.check_id}>
              {!hideTenant && <td className="text-fg-dim">{r.tenant_name}</td>}
              <td>
                <Risk score={r.risk_score} />
              </td>
              <td>
                <Mono dim>{r.document_id}</Mono>
              </td>
              <td className="text-fg-dim">{r.citations.join(", ") || "—"}</td>
              <td>
                {r.assigned_to ? (
                  <Mono>{r.assigned_to.slice(0, 12)}…</Mono>
                ) : (
                  <span className="text-warn">unassigned</span>
                )}
              </td>
              <td className="num text-fg-dim">{r.comments || "—"}</td>
              <td className={cn("num", r.age_hours > 48 && "text-warn")}>{r.age_hours}h</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function ReviewsSection() {
  const { data, error, loading } = useData<ReviewRow[]>(api.reviews);
  if (loading) return <Loading />;
  if (error) return <ErrorNote error={error} />;

  const rows = data ?? [];
  const critical = rows.filter((r) => r.risk_score >= 80).length;
  const unassigned = rows.filter((r) => !r.assigned_to).length;
  const oldest = rows.reduce((m, r) => Math.max(m, r.age_hours), 0);

  return (
    <div>
      <Head title="Human review" sub="Open escalations across every tenant" />
      <div className="grid grid-cols-2 overflow-hidden rounded-xl border border-line bg-panel shadow-soft md:grid-cols-4">
        <Metric label="Open" value={rows.length} tone={rows.length ? "warn" : "neutral"} />
        <Metric label="Critical (80+)" value={critical} tone={critical ? "crit" : "neutral"} />
        <Metric label="Unassigned" value={unassigned} tone={unassigned ? "warn" : "neutral"} />
        <Metric label="Oldest" value={rows.length ? `${oldest}h` : "—"} />
      </div>
      <Panel className="mt-3">
        <ReviewTable rows={rows} />
      </Panel>
      <p className="mt-2 text-xs text-faint">
        Average review time is not recorded — decision timestamps exist in the audit trail but are
        not aggregated by the API, so it is omitted rather than estimated.
      </p>
    </div>
  );
}

// ------------------------------------------------------------------ Agents

function AgentTable({ agents }: { agents: AgentHealth[] }) {
  return (
    <div className="overflow-auto">
      <table className="tbl">
        <thead>
          <tr>
            <th>Agent</th>
            <th>Succeeded</th>
            <th>Failed</th>
            <th>Success rate</th>
            <th>Latency</th>
            <th>Queue</th>
            <th>Last seen</th>
          </tr>
        </thead>
        <tbody>
          {agents.map((a) => {
            const rate = a.success_rate;
            const tone = rate === null ? "" : rate >= 0.99 ? "text-ok" : rate >= 0.9 ? "text-warn" : "text-crit";
            return (
              <tr key={a.agent}>
                <td className="text-fg-dim">{a.agent}</td>
                <td className="num">{a.succeeded}</td>
                <td className={cn("num", a.failed > 0 && "text-crit")}>{a.failed}</td>
                <td className={cn("num font-semibold", tone)}>
                  {rate === null ? "—" : `${(rate * 100).toFixed(1)}%`}
                </td>
                <td>
                  <Unavailable reason="Per-request latency is not recorded in the audit trail." />
                </td>
                <td>
                  <Unavailable reason="Cloud Tasks queue depth is not exposed to this service." />
                </td>
                <td className="text-faint">{a.last_seen ? ago(a.last_seen) : "—"}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export function AgentsSection() {
  const { data, error, loading } = useData<AgentHealth[]>(api.agents);
  if (loading) return <Loading />;
  if (error) return <ErrorNote error={error} />;
  return (
    <div>
      <Head
        title="AI operations"
        sub="Success and failure counts derived from the append-only audit trail"
      />
      <Panel>
        {data?.length ? <AgentTable agents={data} /> : <Empty>No agent activity recorded.</Empty>}
      </Panel>
      <p className="mt-2 text-xs text-faint">
        Counts come from the audit trail, where every agent writes a distinct success and failure
        action — so the rate is measured, not sampled. Latency and queue depth are not recorded
        anywhere and are shown as unavailable rather than estimated.
      </p>
    </div>
  );
}

// -------------------------------------------------------------- Compliance

export function ComplianceSection() {
  const { data, error, loading } = useData<ComplianceIntel>(api.compliance);
  if (loading) return <Loading />;
  if (error) return <ErrorNote error={error} />;
  if (!data) return null;

  return (
    <div>
      <Head title="Compliance intelligence" sub="Risk and rule activity across the platform" />

      <Panel title="Risk distribution">
        <Distribution
          segments={[
            { label: "low (0-29)", value: data.risk_distribution.low, cls: "bg-ok" },
            { label: "medium (30-59)", value: data.risk_distribution.medium, cls: "bg-warn" },
            { label: "high (60+)", value: data.risk_distribution.high, cls: "bg-crit" },
          ]}
        />
      </Panel>

      <div className="mt-3 grid gap-3 lg:grid-cols-2">
        <Panel title="Most-triggered rules">
          {data.top_rules.length === 0 ? (
            <Empty>No rules triggered yet.</Empty>
          ) : (
            <table className="tbl">
              <thead>
                <tr>
                  <th>Rule</th>
                  <th>Hits</th>
                </tr>
              </thead>
              <tbody>
                {data.top_rules.map((r) => (
                  <tr key={r.rule_id}>
                    <td>
                      <Mono>{r.rule_id}</Mono>
                    </td>
                    <td className="num">{r.hits}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Panel>

        <Panel title="Highest-risk tenants">
          {data.highest_risk_tenants.length === 0 ? (
            <Empty>No scored checks yet.</Empty>
          ) : (
            <table className="tbl">
              <thead>
                <tr>
                  <th>Tenant</th>
                  <th>Checks</th>
                  <th>Avg risk</th>
                </tr>
              </thead>
              <tbody>
                {data.highest_risk_tenants.map((t) => (
                  <tr key={t.tenant_id}>
                    <td>
                      <Link to={`/tenants/${t.tenant_id}`} className="text-accent hover:underline">
                        {t.name}
                      </Link>
                    </td>
                    <td className="num">{t.checks}</td>
                    <td>
                      <Risk score={Math.round(t.avg_risk)} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Panel>
      </div>

      <Panel className="mt-3" title={`Rulesets in use (${data.rulesets.length})`}>
        <table className="tbl">
          <thead>
            <tr>
              <th>Industry</th>
              <th>Jurisdiction</th>
              <th>Version</th>
              <th>Rules</th>
            </tr>
          </thead>
          <tbody>
            {data.rulesets.map((r) => (
              <tr key={`${r.industry}/${r.jurisdiction}`}>
                <td className="text-fg-dim">{r.industry}</td>
                <td className="text-fg-dim">{r.jurisdiction}</td>
                <td>
                  <Mono>{r.version}</Mono>
                </td>
                <td className="num">{r.rules}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>
    </div>
  );
}

// ------------------------------------------------------------------- Audit

export function AuditSection() {
  const { data, error, loading } = useData<{ count: number; events: AuditEvent[] }>(api.audit);
  const [q, setQ] = useState("");

  const rows = useMemo(() => {
    const needle = q.trim().toLowerCase();
    const all = data?.events ?? [];
    if (!needle) return all;
    return all.filter((e) =>
      [e.actor, e.action, e.tenant_id, e.event_id].some((v) =>
        String(v).toLowerCase().includes(needle),
      ),
    );
  }, [data, q]);

  if (loading) return <Loading />;
  if (error) return <ErrorNote error={error} />;

  return (
    <div>
      <Head
        title="Audit log"
        sub="Append-only. Read-only here by construction — there is no delete path in the product."
        right={<Filter value={q} onChange={setQ} placeholder="Filter events…" />}
      />
      <Panel>
        <div className="max-h-[75vh] overflow-auto">
          <table className="tbl">
            <thead>
              <tr>
                <th>Time</th>
                <th>Actor</th>
                <th>Action</th>
                <th>Tenant</th>
                <th>Event ID</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((e) => (
                <tr key={e.event_id}>
                  <td className="text-faint">{e.created_at}</td>
                  <td className="text-fg-dim">{e.actor}</td>
                  <td>
                    <Mono>{e.action}</Mono>
                  </td>
                  <td>
                    <Mono dim>{e.tenant_id}</Mono>
                  </td>
                  <td>
                    <Mono dim>{e.event_id.slice(0, 8)}</Mono>
                  </td>
                </tr>
              ))}
              {rows.length === 0 && (
                <tr>
                  <td colSpan={5}>
                    <Empty>No matching events.</Empty>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </Panel>
    </div>
  );
}

// ---------------------------------------------------------------- Security

export function SecuritySection() {
  const { data, error, loading } = useData<SecurityEvent[]>(api.security);
  if (loading) return <Loading />;
  if (error) return <ErrorNote error={error} />;

  const rows = data ?? [];
  const counts = rows.reduce<Record<string, number>>((acc, e) => {
    acc[e.category] = (acc[e.category] ?? 0) + 1;
    return acc;
  }, {});

  return (
    <div>
      <Head title="Security center" sub="Failures, credential changes, and privileged access" />
      <div className="grid grid-cols-2 overflow-hidden rounded-xl border border-line bg-panel shadow-soft md:grid-cols-4">
        <Metric label="Failures" value={counts.failure ?? 0} tone={counts.failure ? "crit" : "neutral"} />
        <Metric label="Credential events" value={counts.credential ?? 0} />
        <Metric label="Privileged access" value={counts["privileged access"] ?? 0} />
        <Metric label="Config changes" value={counts.configuration ?? 0} />
      </div>
      <Panel className="mt-3">
        {rows.length === 0 ? (
          <Empty>No security-relevant events recorded.</Empty>
        ) : (
          <div className="max-h-[65vh] overflow-auto">
            <table className="tbl">
              <thead>
                <tr>
                  <th>Time</th>
                  <th>Category</th>
                  <th>Actor</th>
                  <th>Action</th>
                  <th>Tenant</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((e, i) => (
                  <tr key={`${e.created_at}-${i}`}>
                    <td className="text-faint">{e.created_at}</td>
                    <td
                      className={cn(
                        e.category === "failure" && "text-crit",
                        e.category === "privileged access" && "text-warn",
                      )}
                    >
                      {e.category}
                    </td>
                    <td className="text-fg-dim">{e.actor}</td>
                    <td>
                      <Mono>{e.action}</Mono>
                    </td>
                    <td>
                      <Mono dim>{e.tenant_id}</Mono>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
      <p className="mt-2 text-xs text-faint">
        Sourced from the audit trail, which records action names and identifiers only. Credentials
        are never written to it, so none can appear here.
      </p>
    </div>
  );
}

// ------------------------------------------------------------------ System

export function SystemSection() {
  const { data, error, loading } = useData<ServiceStatus[]>(api.system);
  if (loading) return <Loading />;
  if (error) return <ErrorNote error={error} />;

  return (
    <div>
      <Head title="System health" sub="Dependencies probed at request time" />
      <Panel>
        <table className="tbl">
          <thead>
            <tr>
              <th>Service</th>
              <th>Status</th>
              <th>Detail</th>
            </tr>
          </thead>
          <tbody>
            {(data ?? []).map((s) => (
              <tr key={s.service}>
                <td className="text-fg-dim">{s.service}</td>
                <td>
                  <Status status={s.status} />
                </td>
                <td className="text-faint">{s.detail}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>
      <p className="mt-2 text-xs text-faint">
        Firestore, BigQuery and Cloud Storage are probed with a real call. The rest are not
        reachable from this service without additional IAM and the Cloud Monitoring API, so they
        report unknown rather than a guessed status.
      </p>
    </div>
  );
}

// ------------------------------------------------------------------- Users

const USER_STATUS_LABEL: Record<string, string> = {
  active: "Active",
  disabled: "Disabled",
  pending: "Pending verification",
};

function StatusPill({ status: s }: { status: string }) {
  return (
    <span
      className={cn(
        "text-2xs font-semibold uppercase tracking-wide",
        s === "active" && "text-ok",
        s === "disabled" && "text-crit",
        s === "pending" && "text-warn",
      )}
    >
      {USER_STATUS_LABEL[s] ?? s}
    </span>
  );
}

const USERS_PAGE_SIZE = 25;

/**
 * Cross-tenant user directory.
 *
 * Status and last-login are real Firebase Auth state, not Firestore fields —
 * see PlatformUserRow in api.ts. Filtering/sorting/pagination happen
 * server-side per request; there is no client-side slicing of a bulk fetch
 * here, unlike some of the sections above that reuse a single overview call.
 */
export function UsersSection() {
  const { getToken } = useAuth();
  const [q, setQ] = useState("");
  const [debouncedQ, setDebouncedQ] = useState("");
  const [role, setRole] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [sort, setSort] = useState("created_at");
  const [direction, setDirection] = useState<"asc" | "desc">("desc");
  const [offset, setOffset] = useState(0);

  const [data, setData] = useState<PlatformUsersPage | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const id = setTimeout(() => setDebouncedQ(q), 300);
    return () => clearTimeout(id);
  }, [q]);

  useEffect(() => {
    setOffset(0);
  }, [debouncedQ, role, statusFilter, sort, direction]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    api
      .users(getToken, {
        limit: USERS_PAGE_SIZE,
        offset,
        q: debouncedQ,
        role,
        status: statusFilter,
        sort,
        direction,
      })
      .then((d) => {
        if (cancelled) return;
        setData(d);
        setError(null);
      })
      .catch((e) => {
        if (cancelled) return;
        setError(e instanceof ApiError ? e.message : (e as Error).message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [getToken, offset, debouncedQ, role, statusFilter, sort, direction]);

  const toggleSort = (key: string) => {
    if (sort === key) {
      setDirection((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSort(key);
      setDirection("asc");
    }
  };

  const field =
    "rounded border border-line bg-panel px-2 py-1 text-sm text-fg focus:border-accent focus:outline-none";

  const rows = data?.users ?? [];
  const total = data?.total ?? 0;
  const from = total === 0 ? 0 : offset + 1;
  const to = Math.min(offset + USERS_PAGE_SIZE, total);
  const filtered = Boolean(debouncedQ || role || statusFilter);

  return (
    <div>
      <Head
        title="Users"
        sub={loading ? "Loading…" : `Showing ${from}–${to} of ${total} users`}
        right={
          <div className="flex flex-wrap items-center gap-2">
            <select className={field} value={role} onChange={(e) => setRole(e.target.value)}>
              <option value="">All roles</option>
              <option value="owner">Owner</option>
              <option value="admin">Admin</option>
              <option value="reviewer">Reviewer</option>
            </select>
            <select
              className={field}
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
            >
              <option value="">All statuses</option>
              <option value="active">Active</option>
              <option value="pending">Pending verification</option>
              <option value="disabled">Disabled</option>
            </select>
            <Filter value={q} onChange={setQ} placeholder="Search name, email, tenant…" />
          </div>
        }
      />

      {error && <ErrorNote error={error} />}

      <Panel>
        {loading && !data ? (
          <Loading />
        ) : rows.length === 0 ? (
          <Empty>{filtered ? "No users match your current filters." : "No users found."}</Empty>
        ) : (
          <div className="max-h-[65vh] overflow-auto">
            <table className="tbl">
              <thead>
                <tr>
                  {(
                    [
                      ["email", "User"],
                      ["tenant_name", "Tenant"],
                      ["role", "Role"],
                      ["status", "Status"],
                      ["created_at", "Created"],
                      ["last_sign_in", "Last login"],
                    ] as const
                  ).map(([key, label]) => (
                    <th
                      key={key}
                      onClick={() => toggleSort(key)}
                      className={cn("cursor-pointer select-none", sort === key && "text-accent")}
                    >
                      {label}
                      {sort === key && (direction === "asc" ? " ↑" : " ↓")}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((u) => (
                  <tr key={u.uid}>
                    <td>
                      <Link to={`/users/${u.uid}`} className="text-accent hover:underline">
                        {u.email}
                      </Link>
                      {u.job_title && <div className="text-2xs text-faint">{u.job_title}</div>}
                    </td>
                    <td>
                      <Link
                        to={`/tenants/${u.tenant_id}`}
                        className="text-fg-dim hover:text-accent hover:underline"
                      >
                        {u.tenant_name}
                      </Link>
                    </td>
                    <td className="text-fg-dim">{u.role}</td>
                    <td>
                      <StatusPill status={u.status} />
                    </td>
                    <td className="text-faint">{ago(u.created_at)}</td>
                    <td className="text-faint">
                      {u.last_sign_in ? ago(u.last_sign_in) : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      {total > USERS_PAGE_SIZE && (
        <div className="mt-3 flex items-center justify-between text-sm text-fg-dim">
          <span>
            Showing {from}–{to} of {total} users
          </span>
          <div className="flex gap-2">
            <button
              onClick={() => setOffset((o) => Math.max(0, o - USERS_PAGE_SIZE))}
              disabled={offset === 0}
              className="rounded border border-line px-2.5 py-1 text-sm disabled:opacity-40"
            >
              Previous
            </button>
            <button
              onClick={() => setOffset((o) => o + USERS_PAGE_SIZE)}
              disabled={to >= total}
              className="rounded border border-line px-2.5 py-1 text-sm disabled:opacity-40"
            >
              Next
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

export function UserDetailSection() {
  const { uid } = useParams<{ uid: string }>();
  const { getToken, sendUserPasswordReset } = useAuth();
  const [resetState, setResetState] = useState<"idle" | "sending" | "sent" | "error">("idle");
  const [data, setData] = useState<PlatformUserDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    if (!uid) return;
    setLoading(true);
    api
      .userDetail(getToken, uid)
      .then((d) => {
        setData(d);
        setError(null);
      })
      .catch((e) => setError(e instanceof ApiError ? e.message : (e as Error).message))
      .finally(() => setLoading(false));
    // getToken is a stable module-level reference in every call site here.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [uid]);

  useEffect(load, [load]);

  const [statusTarget, setStatusTarget] = useState<"disable" | "enable" | null>(null);
  const [roleTarget, setRoleTarget] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  const applyStatus = async (reason: string) => {
    if (!uid || !statusTarget) return;
    setBusy(true);
    setActionError(null);
    try {
      await api.setUserStatus(getToken, uid, statusTarget === "disable", reason);
      setStatusTarget(null);
      load();
    } catch (e) {
      setActionError(e instanceof ApiError ? e.message : (e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const applyRole = async (reason: string) => {
    if (!uid || !roleTarget) return;
    setBusy(true);
    setActionError(null);
    try {
      await api.setUserRole(getToken, uid, roleTarget, reason);
      setRoleTarget(null);
      load();
    } catch (e) {
      setActionError(e instanceof ApiError ? e.message : (e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  if (loading && !data) return <Loading />;
  if (error) return <ErrorNote error={error} />;
  if (!data) return null;

  return (
    <div>
      <Head
        title={data.email}
        sub={`${data.tenant_name} · ${data.role}`}
        right={
          <Link to="/users" className="text-sm text-accent hover:underline">
            ← All users
          </Link>
        }
      />

      <div className="grid grid-cols-2 overflow-hidden rounded-xl border border-line bg-panel shadow-soft md:grid-cols-4">
        <div className="px-3 py-2.5">
          <div className="label">Status</div>
          <div className="mt-1">
            <StatusPill status={data.status} />
          </div>
        </div>
        <Metric label="Reviews assigned" value={data.reviews_assigned} />
        <Metric label="Reviews decided" value={data.reviews_decided} />
        <div className="px-3 py-2.5">
          <div className="label">Last login</div>
          <div className="mt-1 text-sm text-fg-dim">
            {data.last_sign_in ? ago(data.last_sign_in) : "Never"}
          </div>
        </div>
      </div>

      <div className="mt-3 grid gap-3 lg:grid-cols-2">
        <Panel title="Account">
          <div className="space-y-1.5 px-3 py-3 text-sm">
            <div>
              <span className="text-muted">Email </span>
              <span className="text-fg">{data.email}</span>
              {!data.email_verified && (
                <span className="ml-1.5 text-2xs text-warn">unverified</span>
              )}
            </div>
            <div>
              <span className="text-muted">UID </span>
              <Mono dim>{data.uid}</Mono>
            </div>
            <div>
              <span className="text-muted">Tenant </span>
              <Link to={`/tenants/${data.tenant_id}`} className="text-accent hover:underline">
                {data.tenant_name}
              </Link>
            </div>
            <div>
              <span className="text-muted">Job title </span>
              <span className="text-fg-dim">{data.job_title || "—"}</span>
            </div>
            <div>
              <span className="text-muted">Created </span>
              <span className="text-fg-dim">{ago(data.created_at)}</span>
            </div>
          </div>
        </Panel>

        <Panel title="Actions">
          <div className="space-y-3 px-3 py-3 text-sm">
            <div>
              <div className="mb-1 text-fg-dim">Account access</div>
              <button
                onClick={() => setStatusTarget(data.disabled ? "enable" : "disable")}
                className={cn(
                  "rounded-lg px-3 py-1.5 text-sm font-medium text-white shadow-soft transition-colors",
                  data.disabled ? "bg-ok hover:opacity-90" : "bg-crit hover:opacity-90",
                )}
              >
                {data.disabled ? "Enable user" : "Disable user"}
              </button>
            </div>
            <div>
              <div className="mb-1 text-fg-dim">Account support</div>
              <button
                onClick={async () => {
                  setResetState("sending");
                  try {
                    await sendUserPasswordReset(data.email);
                    setResetState("sent");
                  } catch {
                    setResetState("error");
                  }
                }}
                disabled={resetState === "sending"}
                className="rounded-lg border border-line px-3 py-1.5 text-sm text-fg-dim transition-colors hover:bg-raised disabled:opacity-50"
              >
                {resetState === "sending" ? "Sending…" : "Send password reset"}
              </button>
              {resetState === "sent" && (
                <p className="mt-1.5 text-2xs text-ok">Reset email sent to {data.email}.</p>
              )}
              {resetState === "error" && (
                <p className="mt-1.5 text-2xs text-crit">Could not send the reset email.</p>
              )}
            </div>
            <div>
              <div className="mb-1 text-fg-dim">Role</div>
              <select
                className="rounded border border-line bg-panel px-2 py-1 text-sm text-fg focus:border-accent focus:outline-none"
                value={data.role}
                onChange={(e) => setRoleTarget(e.target.value)}
              >
                <option value="owner">Owner</option>
                <option value="admin">Admin</option>
                <option value="reviewer">Reviewer</option>
              </select>
            </div>
          </div>
        </Panel>
      </div>

      <Panel className="mt-3" title={`Recent activity (${data.recent_activity.length})`}>
        {data.recent_activity.length === 0 ? (
          <Empty>No recorded activity for this user.</Empty>
        ) : (
          <table className="tbl">
            <thead>
              <tr>
                <th>Time</th>
                <th>Action</th>
                <th>Tenant</th>
              </tr>
            </thead>
            <tbody>
              {data.recent_activity.map((e, i) => (
                <tr key={`${e.created_at}-${i}`}>
                  <td className="text-faint">{e.created_at}</td>
                  <td>
                    <Mono>{e.action}</Mono>
                  </td>
                  <td>
                    <Mono dim>{e.tenant_id}</Mono>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Panel>

      <ConfirmAction
        open={statusTarget !== null}
        intent={statusTarget === "disable" ? "crit" : "ok"}
        title={statusTarget === "disable" ? `Disable ${data.email}` : `Enable ${data.email}`}
        confirmLabel={statusTarget === "disable" ? "Disable user" : "Enable user"}
        busy={busy}
        error={actionError}
        onCancel={() => setStatusTarget(null)}
        onConfirm={applyStatus}
        reasonLabel={
          statusTarget === "disable"
            ? "Why is this user being disabled?"
            : "Why is access being restored?"
        }
        reasonPlaceholder={
          statusTarget === "disable"
            ? "Reported suspicious activity on this account."
            : "Confirmed with the customer, safe to restore."
        }
        consequence={
          statusTarget === "disable" ? (
            <>This user will be signed out immediately and cannot sign back in until re-enabled.</>
          ) : (
            <>This user can sign in again immediately.</>
          )
        }
        preserved={
          statusTarget === "disable" ? (
            <>
              <strong className="text-fg">Nothing is deleted.</strong> Every document, check and
              comment this person is attached to is untouched.
            </>
          ) : undefined
        }
      />

      <ConfirmAction
        open={roleTarget !== null}
        intent="crit"
        title={`Change role to ${roleTarget ?? ""}`}
        confirmLabel="Change role"
        busy={busy}
        error={actionError}
        onCancel={() => setRoleTarget(null)}
        onConfirm={applyRole}
        reasonLabel="Why is this role changing?"
        reasonPlaceholder="Promoted to admin to manage the team's document review queue."
        consequence={
          <>
            This changes what {data.email} can do inside {data.tenant_name}. The new role takes
            effect on their next sign-in or token refresh, not their current session.
          </>
        }
      />
    </div>
  );
}

// ---------------------------------------------------------------- Settings

// ------------------------------------------------------------- Rulesets

/** Codes read as codes; a name is faster to scan than "us-ca". */
const JURISDICTION: Record<string, string> = {
  au: "Australia",
  in: "India",
  eu: "European Union",
  uk: "United Kingdom",
  "us-ca": "United States (CA)",
  ca: "Canada",
  sg: "Singapore",
  br: "Brazil",
  cn: "China",
  ae: "United Arab Emirates",
  za: "South Africa",
  generic: "Any jurisdiction",
};

const INDUSTRY: Record<string, string> = {
  healthcare_ndis: "NDIS / disability",
  aged_care: "Aged care",
  bookkeeping: "Bookkeeping & payroll",
  data_privacy: "Data privacy",
  contract_review: "Contract review",
  corporate_compliance: "Corporate compliance",
};

const label2 = (m: Record<string, string>, k: string) => m[k?.toLowerCase()] ?? k;

const SEVERITY_ORDER = ["critical", "high", "medium", "low"] as const;

/**
 * Regulations & rulesets — what the engine will actually apply, and to whom.
 *
 * Read from the same YAML the compliance agent evaluates against, through the
 * same loader, so this cannot drift from what runs. That matters more here
 * than anywhere else in this console: a control plane reporting a rule the
 * engine does not apply is worse than one reporting nothing.
 *
 * Read-only, like every other section. Publishing or editing rulesets from a
 * UI would put a cross-tenant write in front of the rules that judge every
 * customer document — that belongs in version control with review, not
 * behind a button.
 */
export function RulesetsSection() {
  const { data, error, loading } = useData<PlatformRuleset[]>(api.rulesets);
  const [selected, setSelected] = useState<string | null>(null);
  const [q, setQ] = useState("");

  const rows = data ?? [];
  const keyOf = (r: PlatformRuleset) => r.industry + "/" + r.jurisdiction;
  const active = rows.find((r) => keyOf(r) === selected) ?? rows[0];

  const totals = useMemo(() => {
    const jurisdictions = new Set(rows.map((r) => r.jurisdiction));
    const rules = rows.reduce((n, r) => n + r.rule_count, 0);
    const orphaned = rows.filter((r) => r.tenants_assigned === 0).length;
    const critical = rows.reduce((n, r) => n + (r.severity_counts.critical ?? 0), 0);
    return { jurisdictions: jurisdictions.size, rules, orphaned, critical };
  }, [rows]);

  const visibleRules = useMemo(() => {
    if (!active) return [];
    const needle = q.trim().toLowerCase();
    if (!needle) return active.rules;
    return active.rules.filter((r) =>
      [r.id, r.description, r.severity, r.check_type].some((v) =>
        String(v).toLowerCase().includes(needle),
      ),
    );
  }, [active, q]);

  if (loading) return <Loading />;
  if (error) return <ErrorNote error={error} />;
  if (!rows.length)
    return (
      <div>
        <Head title="Regulations & rulesets" />
        <Panel>
          <Empty>
            No ruleset loaded. The engine reads these from the rulesets directory shipped inside
            each container, so an empty list means the deployment is missing that directory — not
            that no rules are configured.
          </Empty>
        </Panel>
      </div>
    );

  return (
    <div>
      <Head
        title="Regulations & rulesets"
        sub="What the engine will apply, read from the files it evaluates against"
      />

      <div className="grid grid-cols-2 overflow-hidden rounded-xl border border-line bg-panel shadow-soft md:grid-cols-4">
        <Metric
          label="Rulesets"
          value={rows.length}
          hint={totals.jurisdictions + " jurisdictions"}
        />
        <Metric label="Rules" value={totals.rules} />
        <Metric
          label="Critical rules"
          value={totals.critical}
          tone={totals.critical ? "warn" : "neutral"}
        />
        <Metric
          label="Unassigned"
          value={totals.orphaned}
          tone={totals.orphaned ? "warn" : "ok"}
          hint="No workspace uses these"
        />
      </div>

      <div className="mt-3 grid gap-3 lg:grid-cols-[360px_minmax(0,1fr)]">
        <Panel title={"Rulesets \u00b7 " + rows.length}>
          <div className="max-h-[70vh] overflow-auto">
            <table className="tbl">
              <thead>
                <tr>
                  <th>Ruleset</th>
                  <th>Ver</th>
                  <th>Rules</th>
                  <th>Used by</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => {
                  const isActive = !!active && keyOf(r) === keyOf(active);
                  return (
                    <tr
                      key={keyOf(r)}
                      onClick={() => {
                        setSelected(keyOf(r));
                        setQ("");
                      }}
                      className={cn("cursor-pointer", isActive && "bg-raised")}
                    >
                      <td>
                        <div className={cn("text-fg", isActive && "text-accent")}>
                          {label2(INDUSTRY, r.industry)}
                        </div>
                        <div className="text-2xs text-faint">
                          {label2(JURISDICTION, r.jurisdiction)}
                        </div>
                      </td>
                      <td>
                        <Mono dim>{r.rule_set_version}</Mono>
                      </td>
                      <td className="num">{r.rule_count}</td>
                      <td className="num">
                        {r.tenants_assigned === 0 ? (
                          <span className="text-warn" title="No workspace is assigned to this ruleset">
                            0
                          </span>
                        ) : (
                          r.tenants_assigned
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </Panel>

        {active && (
          <div className="min-w-0">
            <Panel
              title={
                label2(INDUSTRY, active.industry) +
                " \u00b7 " +
                label2(JURISDICTION, active.jurisdiction)
              }
              right={<Filter value={q} onChange={setQ} placeholder="Filter rules..." />}
            >
              <div className="flex flex-wrap items-center gap-x-5 gap-y-2 border-b border-line px-3 py-2.5 text-sm">
                <span className="text-fg-dim">
                  v<Mono>{active.rule_set_version}</Mono>
                </span>
                <span className="text-fg-dim">
                  {active.tenants_assigned} workspace{active.tenants_assigned === 1 ? "" : "s"}
                </span>
                {SEVERITY_ORDER.filter((s) => active.severity_counts[s]).map((s) => (
                  <span
                    key={s}
                    className={cn(
                      s === "critical" && "text-crit",
                      s === "high" && "text-warn",
                      (s === "medium" || s === "low") && "text-muted",
                    )}
                  >
                    {active.severity_counts[s]} {s}
                  </span>
                ))}
              </div>

              <div className="max-h-[52vh] overflow-auto">
                {visibleRules.length === 0 ? (
                  <Empty>No rule in this ruleset matches that filter.</Empty>
                ) : (
                  <table className="tbl">
                    <thead>
                      <tr>
                        <th>Rule</th>
                        <th>Severity</th>
                        <th>Check</th>
                        <th>Evaluates</th>
                      </tr>
                    </thead>
                    <tbody>
                      {visibleRules.map((rule) => (
                        <tr key={rule.id}>
                          <td>
                            <Mono>{rule.id}</Mono>
                            <div className="mt-0.5 max-w-xl text-2xs leading-relaxed text-muted">
                              {rule.description}
                            </div>
                          </td>
                          <td className="whitespace-nowrap">
                            <span
                              className={cn(
                                rule.severity === "critical" && "text-crit",
                                rule.severity === "high" && "text-warn",
                                (rule.severity === "medium" || rule.severity === "low") &&
                                  "text-muted",
                              )}
                            >
                              {rule.severity}
                            </span>
                          </td>
                          <td className="whitespace-nowrap text-fg-dim">{rule.check_type}</td>
                          {/* Field NAMES, never values — values are tenant documents. */}
                          <td>
                            <Mono dim>{rule.params.join(", ") || "\u2014"}</Mono>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
            </Panel>

            <Panel className="mt-3" title="Fields the ingestion agent must extract">
              <div className="flex flex-wrap gap-1.5 px-3 py-3">
                {active.required_fields.length === 0 ? (
                  <span className="text-sm text-muted">
                    This ruleset declares no required fields — each rule reads what it needs
                    directly.
                  </span>
                ) : (
                  active.required_fields.map((f) => (
                    <span key={f} className="border border-line px-1.5 py-0.5 text-2xs">
                      <Mono dim>{f}</Mono>
                    </span>
                  ))
                )}
              </div>
              <p className="border-t border-line px-3 py-2 text-2xs text-faint">
                A rule whose field is absent from a document returns &ldquo;uncertain&rdquo;
                rather than a guess. That is why a document checked against the wrong ruleset
                produces uncertainty rather than a failure.
              </p>
            </Panel>
          </div>
        )}
      </div>

      <p className="mt-2 text-2xs text-faint">
        Read-only. Rulesets are versioned YAML in the repository, deployed with the services.
        Every count on this page is computed from the same files the engine loads, so it cannot
        report a rule that will not actually be applied.
      </p>
    </div>
  );
}

// -------------------------------------------------------------- Support

const TICKET_STATUSES = ["new", "open", "in_progress", "waiting_for_user", "resolved", "closed"];
const TICKET_PRIORITIES = ["low", "normal", "high", "urgent"];

/**
 * Support inbox.
 *
 * The one place in this console that shows internal notes, and the reason
 * they are visually distinct from customer messages: an operator glancing at
 * a thread must never mistake a triage note for something the customer has
 * already read. Customers cannot receive them at all — they are filtered
 * server-side — so this styling is about operator comprehension, not secrecy.
 *
 * Replying is gated on a separate permission from reading. An operator who
 * can read the inbox is not automatically allowed to speak to customers in
 * the company's name, so the composer is hidden rather than shown-and-failing.
 */
export function SupportSection() {
  const { getToken } = useAuth();
  const { data, error, loading, reload } = useData<SupportTicketRow[]>(api.support);
  const perms = useData<SupportPermissions>(api.supportPermissions);

  const [selected, setSelected] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [reply, setReply] = useState("");
  const [internal, setInternal] = useState(false);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  const tickets = data ?? [];
  const active = tickets.find((t) => t.ticket_id === selected) ?? tickets[0];
  const canReply = perms.data?.can_reply === true;

  const rows = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return tickets.filter((t) => {
      if (statusFilter && t.status !== statusFilter) return false;
      if (!needle) return true;
      return [t.reference, t.email, t.first_name, t.tenant_id, t.category]
        .concat(t.messages.map((m) => m.body))
        .some((v) => String(v).toLowerCase().includes(needle));
    });
  }, [tickets, q, statusFilter]);

  const counts = useMemo(() => {
    const open = tickets.filter((t) => !["resolved", "closed"].includes(t.status)).length;
    const waiting = tickets.filter((t) => t.status === "waiting_for_user").length;
    const urgent = tickets.filter((t) => ["high", "urgent"].includes(t.priority)).length;
    const unassigned = tickets.filter((t) => !t.assigned_to && !["resolved", "closed"].includes(t.status)).length;
    return { open, waiting, urgent, unassigned };
  }, [tickets]);

  const send = async () => {
    if (!active || !reply.trim()) return;
    setBusy(true);
    setActionError(null);
    try {
      await api.supportReply(getToken, active.ticket_id, reply.trim(), internal);
      setReply("");
      setInternal(false);
      reload();
    } catch (e) {
      setActionError(e instanceof ApiError ? e.message : (e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const patch = async (p: { status?: string; priority?: string; assigned_to?: string }) => {
    if (!active) return;
    setActionError(null);
    try {
      await api.supportUpdate(getToken, active.ticket_id, p);
      reload();
    } catch (e) {
      setActionError(e instanceof ApiError ? e.message : (e as Error).message);
    }
  };

  if (loading) return <Loading />;
  if (error) return <ErrorNote error={error} />;

  const field =
    "rounded border border-line bg-panel px-2 py-1 text-sm text-fg focus:border-accent focus:outline-none";

  return (
    <div>
      <Head title="Support inbox" sub="Customer requests across every workspace" />

      <div className="grid grid-cols-2 overflow-hidden rounded-xl border border-line bg-panel shadow-soft md:grid-cols-4">
        <Metric label="Open" value={counts.open} tone={counts.open ? "warn" : "ok"} />
        <Metric label="Awaiting customer" value={counts.waiting} />
        <Metric label="High / urgent" value={counts.urgent} tone={counts.urgent ? "crit" : "neutral"} />
        <Metric label="Unassigned" value={counts.unassigned} tone={counts.unassigned ? "warn" : "ok"} />
      </div>

      {perms.data && !perms.data.agents_configured && (
        <Panel className="mt-3" title="Replying is disabled">
          <p className="px-3 py-3 text-sm text-muted">
            No support agents are configured, so nobody can reply to a customer. Set
            CG_SUPPORT_AGENTS to a comma-separated list of operator emails. Closed by default is
            deliberate — being able to read this inbox is not the same as being able to write to
            customers as the company.
          </p>
        </Panel>
      )}

      {tickets.length === 0 ? (
        <Panel className="mt-3">
          <Empty>
            No support requests yet. They arrive here when a customer uses the contact form.
          </Empty>
        </Panel>
      ) : (
        <div className="mt-3 grid gap-3 lg:grid-cols-[380px_minmax(0,1fr)]">
          <Panel
            title={`Tickets \u00b7 ${rows.length}`}
            right={
              <div className="flex items-center gap-2">
                <select className={field} value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
                  <option value="">All statuses</option>
                  {TICKET_STATUSES.map((s) => (
                    <option key={s} value={s}>
                      {s.replace(/_/g, " ")}
                    </option>
                  ))}
                </select>
                <Filter value={q} onChange={setQ} placeholder="Search..." />
              </div>
            }
          >
            <div className="max-h-[70vh] overflow-auto">
              <table className="tbl">
                <thead>
                  <tr>
                    <th>Ticket</th>
                    <th>Status</th>
                    <th>Age</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((t) => (
                    <tr
                      key={t.ticket_id}
                      onClick={() => setSelected(t.ticket_id)}
                      className={cn("cursor-pointer", active?.ticket_id === t.ticket_id && "bg-raised")}
                    >
                      <td>
                        <Mono>{t.reference}</Mono>
                        <div className="text-2xs text-faint">
                          {t.first_name} \u00b7 {t.category}
                          {["high", "urgent"].includes(t.priority) && (
                            <span className="ml-1.5 text-crit">{t.priority}</span>
                          )}
                        </div>
                      </td>
                      <td className="whitespace-nowrap text-fg-dim">{t.status.replace(/_/g, " ")}</td>
                      <td className="whitespace-nowrap text-faint">{ago(t.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Panel>

          {active && (
            <div className="min-w-0">
              <Panel
                title={active.reference}
                right={
                  <div className="flex flex-wrap items-center gap-2">
                    <select
                      className={field}
                      value={active.status}
                      onChange={(e) => patch({ status: e.target.value })}
                    >
                      {TICKET_STATUSES.map((s) => (
                        <option key={s} value={s}>
                          {s.replace(/_/g, " ")}
                        </option>
                      ))}
                    </select>
                    <select
                      className={field}
                      value={active.priority}
                      onChange={(e) => patch({ priority: e.target.value })}
                    >
                      {TICKET_PRIORITIES.map((p) => (
                        <option key={p} value={p}>
                          {p}
                        </option>
                      ))}
                    </select>
                  </div>
                }
              >
                <div className="grid gap-x-6 gap-y-1 border-b border-line px-3 py-2.5 text-sm sm:grid-cols-2">
                  <div>
                    <span className="text-muted">From </span>
                    <span className="text-fg">{active.first_name}</span>{" "}
                    <Mono dim>{active.email}</Mono>
                  </div>
                  <div>
                    <span className="text-muted">Workspace </span>
                    <Link to={`/tenants/${active.tenant_id}`} className="text-accent hover:underline">
                      <Mono>{active.tenant_id}</Mono>
                    </Link>
                  </div>
                  {active.phone && (
                    <div>
                      <span className="text-muted">Phone </span>
                      <Mono dim>{active.phone}</Mono>
                    </div>
                  )}
                  <div>
                    <span className="text-muted">Assigned </span>
                    {active.assigned_to ? (
                      <span className="text-fg">{active.assigned_to}</span>
                    ) : (
                      <button
                        onClick={() => patch({ assigned_to: perms.data?.me ?? "" })}
                        className="text-accent hover:underline"
                      >
                        assign to me
                      </button>
                    )}
                  </div>
                </div>

                <div className="max-h-[46vh] space-y-2 overflow-auto px-3 py-3">
                  {active.messages.map((m) => (
                    <div
                      key={m.message_id}
                      className={cn(
                        "rounded-lg border p-2.5",
                        m.internal
                          ? "border-warn/40 bg-warn/5"
                          : m.sender === "support"
                            ? "border-accent/30 bg-accent/5"
                            : "border-line bg-raised",
                      )}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-2xs font-semibold uppercase tracking-wide">
                          {m.internal ? (
                            <span className="text-warn">Internal note \u00b7 not visible to customer</span>
                          ) : m.sender === "support" ? (
                            <span className="text-accent">Support \u00b7 {m.author_email}</span>
                          ) : (
                            <span className="text-fg-dim">Customer</span>
                          )}
                        </span>
                        <span className="text-2xs text-faint">{ago(m.created_at)}</span>
                      </div>
                      <p className="mt-1 whitespace-pre-wrap text-sm text-fg-dim">{m.body}</p>
                    </div>
                  ))}
                </div>

                {canReply ? (
                  <div className="border-t border-line px-3 py-3">
                    <textarea
                      rows={3}
                      value={reply}
                      onChange={(e) => setReply(e.target.value)}
                      placeholder={internal ? "Internal note, never sent to the customer..." : "Reply to the customer..."}
                      className="w-full rounded-lg border border-line bg-panel px-2.5 py-2 text-sm text-fg placeholder:text-faint focus:border-accent focus:outline-none"
                    />
                    <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
                      <label className="flex items-center gap-1.5 text-sm text-fg-dim">
                        <input
                          type="checkbox"
                          checked={internal}
                          onChange={(e) => setInternal(e.target.checked)}
                        />
                        Internal note
                      </label>
                      <button
                        onClick={send}
                        disabled={busy || !reply.trim()}
                        className={cn(
                          "rounded-lg px-3 py-1.5 text-sm font-medium text-white shadow-soft transition-colors disabled:opacity-40",
                          internal ? "bg-warn hover:opacity-90" : "bg-accent hover:bg-accent-dim",
                        )}
                      >
                        {busy ? "Sending..." : internal ? "Add note" : "Send reply"}
                      </button>
                    </div>
                    {actionError && <p className="mt-2 text-sm text-crit">{actionError}</p>}
                  </div>
                ) : (
                  <p className="border-t border-line px-3 py-3 text-sm text-muted">
                    You can read this inbox but not reply. Replying requires the support agent
                    permission.
                  </p>
                )}
              </Panel>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export function SettingsSection() {
  const { admin } = useAuth();
  const compliance = useData<ComplianceIntel>(api.compliance);

  return (
    <div>
      <Head title="Settings" sub="Platform configuration" />

      <Panel title="Signed in as">
        <div className="px-3 py-2.5 text-sm">
          <div className="text-fg-dim">{admin?.email}</div>
          <Mono dim>{admin?.uid}</Mono>
        </div>
      </Panel>

      <Panel className="mt-3" title="Active rulesets">
        {compliance.loading ? (
          <Loading />
        ) : (
          <table className="tbl">
            <thead>
              <tr>
                <th>Industry</th>
                <th>Jurisdiction</th>
                <th>Version</th>
                <th>Rules</th>
              </tr>
            </thead>
            <tbody>
              {(compliance.data?.rulesets ?? []).map((r) => (
                <tr key={`${r.industry}/${r.jurisdiction}`}>
                  <td className="text-fg-dim">{r.industry}</td>
                  <td className="text-fg-dim">{r.jurisdiction}</td>
                  <td>
                    <Mono>{r.version}</Mono>
                  </td>
                  <td className="num">{r.rules}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Panel>

      <Panel className="mt-3" title="Not editable from this console">
        <ul className="space-y-2 px-3 py-3 text-sm text-muted">
          <li>
            <span className="text-fg-dim">Risk escalation threshold</span> — set per deployment via
            RISK_ESCALATION_THRESHOLD. Changing it here would need a write path into Cloud Run
            configuration, which this console deliberately does not have.
          </li>
          <li>
            <span className="text-fg-dim">Ruleset contents</span> — versioned YAML in the
            repository, deployed with the services. Editing rules from a console would break the
            guarantee that every decision cites a reviewable, version-controlled rule.
          </li>
          <li>
            <span className="text-fg-dim">Platform admin allowlist</span> — an environment variable,
            so an attacker who reaches this console still cannot grant themselves or anyone else
            access.
          </li>
        </ul>
      </Panel>
      <p className="mt-2 text-xs text-faint">
        This console is read-only across tenants by design. Every request it makes is written to
        the audit trail before data is returned.
      </p>
    </div>
  );
}
