/**
 * Support — the customer side.
 *
 * One screen doing two jobs: raise a request, and follow the ones already
 * raised. Splitting them across two routes would mean a customer with a
 * question has to find the thread they opened yesterday somewhere else.
 *
 * Nothing here can see an internal operator note. They are filtered
 * server-side before the response is built, so this component never receives
 * them and cannot leak one by rendering the wrong field.
 */

import { useCallback, useEffect, useState } from "react";
import { LifeBuoy, MessageSquare, Send, CheckCircle2 } from "lucide-react";
import { useAuth } from "../auth/AuthContext";
import { useToast } from "../context/ToastContext";
import {
  createTicket,
  listTickets,
  replyToTicket,
  ApiError,
  type SupportTicketRow,
} from "../api/client";
import { Card, CardHeader, PageHeading } from "../components/ui/Card";
import { Button } from "../components/ui/Button";
import { LEGAL } from "../lib/legal";

const CATEGORIES = [
  { value: "account", label: "Account" },
  { value: "report", label: "Compliance report" },
  { value: "billing", label: "Billing" },
  { value: "subscription", label: "Subscription" },
  { value: "refund", label: "Refund" },
  { value: "technical", label: "Technical issue" },
  { value: "security", label: "Security" },
  { value: "privacy", label: "Privacy" },
  { value: "other", label: "Other" },
];

/** Customer-facing wording. Internal states are not exposed verbatim. */
const STATUS_LABEL: Record<string, string> = {
  new: "Submitted",
  open: "Under review",
  in_progress: "Being worked on",
  waiting_for_user: "Reply available",
  resolved: "Resolved",
  closed: "Closed",
};

const FIELD =
  "mt-1 w-full rounded-lg border border-line bg-surface px-3 py-2 text-[13.5px] text-ink placeholder:text-muted focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/15";
const LABEL = "text-[12.5px] font-medium text-ink-2";

function Thread({
  ticket,
  onReplied,
}: {
  ticket: SupportTicketRow;
  onReplied: (t: SupportTicketRow) => void;
}) {
  const { session } = useAuth();
  const toast = useToast();
  const [body, setBody] = useState("");
  const [busy, setBusy] = useState(false);

  const send = async () => {
    if (!session || !body.trim()) return;
    setBusy(true);
    try {
      onReplied(await replyToTicket(session, ticket.ticket_id, body.trim()));
      setBody("");
    } catch (err) {
      toast.push({
        kind: "error",
        title: "Could not send",
        description: (err as Error).message,
      });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mt-3 space-y-3">
      {ticket.messages.map((m) => (
        <div
          key={m.message_id}
          className={
            m.sender === "support"
              ? "rounded-lg border border-brand-200 bg-brand-50/50 p-3"
              : "rounded-lg border border-line bg-surface-2 p-3"
          }
        >
          <div className="flex items-center justify-between gap-2">
            <span className="text-[12px] font-semibold text-ink">
              {m.sender === "support" ? "ComplianceGuardian Support" : "You"}
            </span>
            <span className="text-[11.5px] text-muted">
              {new Date(m.created_at).toLocaleString()}
            </span>
          </div>
          <p className="mt-1 whitespace-pre-wrap text-[13px] leading-relaxed text-ink-2">
            {m.body}
          </p>
        </div>
      ))}

      {ticket.status !== "closed" && (
        <div className="flex items-end gap-2">
          <textarea
            rows={2}
            value={body}
            onChange={(e) => setBody(e.target.value)}
            placeholder="Add to this request…"
            className={`${FIELD} flex-1 resize-y`}
          />
          <Button onClick={send} loading={busy} disabled={!body.trim()} icon={<Send size={14} />}>
            Send
          </Button>
        </div>
      )}
    </div>
  );
}

export function SupportView() {
  const { session } = useAuth();
  const toast = useToast();

  const [firstName, setFirstName] = useState("");
  const [email, setEmail] = useState(session?.email ?? "");
  const [phone, setPhone] = useState("");
  const [category, setCategory] = useState("other");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [submitted, setSubmitted] = useState<SupportTicketRow | null>(null);

  const [tickets, setTickets] = useState<SupportTicketRow[]>([]);
  const [openId, setOpenId] = useState<string | null>(null);

  const load = useCallback(() => {
    if (!session) return;
    listTickets(session)
      .then(setTickets)
      .catch(() => setTickets([]));
  }, [session]);
  useEffect(load, [load]);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!session) return;
    setBusy(true);
    try {
      const t = await createTicket(session, {
        first_name: firstName.trim(),
        email: email.trim(),
        phone: phone.trim(),
        message: message.trim(),
        category,
      });
      setSubmitted(t);
      setMessage("");
      setPhone("");
      load();
      toast.push({
        kind: "success",
        title: "Request received",
        description: `Your reference is ${t.reference}.`,
      });
    } catch (err) {
      const msg =
        err instanceof ApiError && err.status === 422
          ? "Please add a little more detail — a sentence or two is enough."
          : (err as Error).message;
      toast.push({ kind: "error", title: "Could not send", description: msg });
    } finally {
      setBusy(false);
    }
  };

  const ready = firstName.trim() && email.trim() && message.trim().length >= 10;

  return (
    <div>
      <PageHeading
        kind="Support"
        title="Contact ComplianceGuardian"
        subtitle="Have a question about ComplianceGuardian? Send us your query and our team will get back to you."
      />

      {submitted && (
        <div className="mb-6 flex flex-wrap items-center gap-2 rounded-xl border border-green-200 bg-green-50 px-4 py-3 text-[13.5px] text-status-good dark:border-green-900/60 dark:bg-green-950/25">
          <CheckCircle2 size={16} strokeWidth={2.25} />
          Your query has been received. Our team will review it and respond as soon as possible.
          <span className="font-mono-num font-semibold">Reference: {submitted.reference}</span>
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_320px]">
        <Card>
          <CardHeader title="Send us a question" />
          <form onSubmit={submit} className="space-y-4">
            <div className="grid gap-4 sm:grid-cols-2">
              <label className="block">
                <span className={LABEL}>First Name *</span>
                <input
                  required
                  value={firstName}
                  onChange={(e) => setFirstName(e.target.value)}
                  placeholder="First Name..."
                  className={FIELD}
                />
              </label>
              <label className="block">
                <span className={LABEL}>Email Address *</span>
                <input
                  required
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="Email Address..."
                  className={FIELD}
                />
              </label>
            </div>

            <div className="grid gap-4 sm:grid-cols-2">
              <label className="block">
                <span className={LABEL}>Phone Number</span>
                <input
                  value={phone}
                  onChange={(e) => setPhone(e.target.value)}
                  placeholder="Phone Number..."
                  className={FIELD}
                />
                <span className="mt-1 block text-[11.5px] text-muted">
                  Optional — we answer by email.
                </span>
              </label>
              <label className="block">
                <span className={LABEL}>Topic</span>
                <select
                  value={category}
                  onChange={(e) => setCategory(e.target.value)}
                  className={FIELD}
                >
                  {CATEGORIES.map((c) => (
                    <option key={c.value} value={c.value}>
                      {c.label}
                    </option>
                  ))}
                </select>
              </label>
            </div>

            <label className="block">
              <span className={LABEL}>Your Question / Query *</span>
              <textarea
                required
                rows={5}
                value={message}
                onChange={(e) => setMessage(e.target.value)}
                placeholder="Describe your question or query..."
                className={`${FIELD} resize-y`}
              />
              <span className="mt-1 block text-[11.5px] text-muted">
                If it is about a specific result, include the check reference from your audit log
                — it lets us answer without asking you to email documents.
              </span>
            </label>

            <Button type="submit" loading={busy} disabled={!ready} size="lg">
              Send question
            </Button>
          </form>
        </Card>

        <div className="space-y-4">
          <Card>
            <CardHeader title="What to expect" />
            <ul className="space-y-2.5 text-[13px] text-ink-2">
              <li>
                We aim to reply within <strong className="text-ink">{LEGAL.supportTarget}</strong>.
                That is a target, not a contractual service level.
              </li>
              <li>Refund requests: {LEGAL.refundTarget}.</li>
              <li>Data access, correction or deletion: {LEGAL.dataRequestTarget}.</li>
              <li>
                Replies appear here, and we email you to say one is waiting — we do not put the
                reply itself in the email.
              </li>
            </ul>
          </Card>

          <Card>
            <CardHeader title="Security or privacy" />
            <p className="text-[13px] leading-relaxed text-ink-2">
              Choose the matching topic and it is prioritised automatically. For a suspected
              vulnerability, please give us a reasonable chance to fix it before disclosing, and
              do not test against other customers&rsquo; workspaces.
            </p>
          </Card>
        </div>
      </div>

      {tickets.length > 0 && (
        <Card className="mt-6">
          <CardHeader title={`Your requests (${tickets.length})`} />
          <ul className="divide-y divide-line">
            {tickets.map((t) => {
              const open = openId === t.ticket_id;
              const waiting = t.status === "waiting_for_user";
              return (
                <li key={t.ticket_id} className="py-3">
                  <button
                    onClick={() => setOpenId(open ? null : t.ticket_id)}
                    className="flex w-full flex-wrap items-center gap-x-3 gap-y-1 text-left"
                  >
                    <LifeBuoy size={14} className="shrink-0 text-muted" />
                    <span className="font-mono-num text-[12.5px] font-semibold text-ink">
                      {t.reference}
                    </span>
                    <span
                      className={`text-[12.5px] ${waiting ? "font-medium text-brand-600" : "text-ink-2"}`}
                    >
                      {STATUS_LABEL[t.status] ?? t.status}
                    </span>
                    <span className="ml-auto inline-flex items-center gap-1 text-[12px] text-muted">
                      <MessageSquare size={12} />
                      {t.messages.length}
                    </span>
                  </button>
                  {open && <Thread ticket={t} onReplied={(u) => setTickets((ts) => ts.map((x) => (x.ticket_id === u.ticket_id ? u : x)))} />}
                </li>
              );
            })}
          </ul>
        </Card>
      )}
    </div>
  );
}
