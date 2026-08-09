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

      <div className="grid grid-cols-2 border border-line bg-panel md:grid-cols-4">
        <Metric label="Tenants" value={data.tenants_total} hint={`${data.members_total} members`} />
        <Metric label="Documents" value={data.documents_total} />
        <Metric label="Checks" value={data.checks_total} />
        <Metric
          label="Open escalations"
          value={data.open_escalations_total}
          tone={data.open_escalations_total > 0 ? "warn" : "neutral"}
        />
      </div>

      <div className="mt-3 grid grid-cols-2 border border-line bg-panel md:grid-cols-4">
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

export function TenantsSection() {
  const { data, error, loading } = useData<Overview>(api.overview);
  const [q, setQ] = useState("");
  const [sort, setSort] = useState<keyof Overview["tenants"][number]>("created_at");

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
                  <td className="text-fg-dim">{t.plan_tier}</td>
                  <td className="num">{t.members}</td>
                  <td className="num">{t.documents}</td>
                  <td className="num">{t.checks}</td>
                  <td className={cn("num", t.open_escalations > 0 && "text-warn")}>
                    {t.open_escalations}
                  </td>
                  <td className="text-faint">{ago(t.created_at)}</td>
                </tr>
              ))}
              {rows.length === 0 && (
                <tr>
                  <td colSpan={9}>
                    <Empty>No tenants match.</Empty>
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
      <div className="grid grid-cols-2 border border-line bg-panel md:grid-cols-4">
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
      <div className="grid grid-cols-2 border border-line bg-panel md:grid-cols-4">
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
      <div className="grid grid-cols-2 border border-line bg-panel md:grid-cols-4">
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

      <div className="grid grid-cols-2 border border-line bg-panel md:grid-cols-4">
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
