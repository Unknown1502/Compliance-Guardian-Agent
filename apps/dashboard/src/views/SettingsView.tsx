import { Link } from "react-router-dom";
import { ArrowUpRight, Clock } from "lucide-react";
import { useAuth } from "../auth/AuthContext";
import { PageHeading } from "../components/ui/Card";
import { Button } from "../components/ui/Button";

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex flex-wrap items-baseline justify-between gap-3 border-b border-line py-3 last:border-0">
      <dt className="text-[13px] text-ink-2">{label}</dt>
      <dd className="font-mono-num text-[13px] text-ink">{value}</dd>
    </div>
  );
}

function Panel({
  title,
  description,
  children,
}: {
  title: string;
  description?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="rounded-xl border border-line bg-surface p-5">
      <h2 className="text-[15px] font-semibold text-ink">{title}</h2>
      {description && <p className="mt-1 text-[13px] text-ink-2">{description}</p>}
      <div className="mt-4">{children}</div>
    </section>
  );
}

export function SettingsView() {
  const { session, signOut } = useAuth();
  if (!session) return null;

  return (
    <div>
      <PageHeading title="Settings" subtitle="Your account and workspace." />

      <div className="grid gap-5 lg:grid-cols-2">
        <Panel title="Account">
          <dl>
            <Row label="Email" value={session.email ?? "—"} />
            <Row label="User ID" value={session.uid} />
            <Row label="Role" value={<span className="capitalize">{session.role}</span>} />
          </dl>
          <Button variant="outline" size="md" className="mt-4" onClick={() => signOut()}>
            Sign out
          </Button>
        </Panel>

        <Panel
          title="Workspace"
          description="Every document, check, and audit event is scoped to this tenant."
        >
          <dl>
            <Row label="Tenant ID" value={session.tenantId} />
            <Row
              label="Active ruleset"
              value={
                <Link
                  to="/rulesets"
                  className="inline-flex items-center gap-0.5 text-brand-600 hover:text-brand-700"
                >
                  View rules <ArrowUpRight size={12} />
                </Link>
              }
            />
            <Row
              label="Billing"
              value={
                <Link
                  to="/billing"
                  className="inline-flex items-center gap-0.5 text-brand-600 hover:text-brand-700"
                >
                  Manage plan <ArrowUpRight size={12} />
                </Link>
              }
            />
          </dl>
        </Panel>

        <Panel
          title="Data & retention"
          description="How your documents and decisions are stored today."
        >
          <ul className="space-y-2.5 text-[13px] leading-relaxed text-ink-2">
            <li>
              Uploaded files are stored in Cloud Storage under this tenant, encrypted at rest.
            </li>
            <li>
              Compliance decisions are written to an append-only BigQuery table. Update and
              delete are blocked at the IAM layer, so history cannot be rewritten — including
              by us.
            </li>
            <li>
              Every AI decision records the prompt version and model version that produced it.
            </li>
          </ul>
        </Panel>

        {/* Stated honestly rather than shown as dead controls — these are real
            roadmap items, not shipped features. */}
        <Panel
          title="Not built yet"
          description="Listed so you know what this workspace does not do today."
        >
          <ul className="space-y-2.5">
            {[
              ["Team members & roles", "Invite reviewers and admins from the dashboard."],
              ["API keys & webhooks", "Programmatic access to checks and audit events."],
              ["Notification preferences", "Email or Slack alerts when a check escalates."],
              ["Configurable retention", "Set how long documents are kept before deletion."],
            ].map(([title, body]) => (
              <li key={title} className="flex items-start gap-2.5">
                <Clock size={14} className="mt-0.5 shrink-0 text-muted" />
                <div>
                  <div className="text-[13px] font-medium text-ink">{title}</div>
                  <div className="text-[12.5px] text-ink-2">{body}</div>
                </div>
              </li>
            ))}
          </ul>
        </Panel>
      </div>
    </div>
  );
}
