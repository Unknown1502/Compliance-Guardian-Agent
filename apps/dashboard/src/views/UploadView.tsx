import { useCallback, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { AnimatePresence, motion } from "framer-motion";
import {
  UploadCloud,
  FileText,
  X,
  Loader2,
  CheckCircle2,
  ArrowUpRight,
  Circle,
  ShieldOff,
} from "lucide-react";
import { uploadDocument, triggerCheck, ApiError } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { useToast } from "../context/ToastContext";
import { Card, CardHeader, PageHeading } from "../components/ui/Card";
import { Button } from "../components/ui/Button";
import { cn } from "../lib/cn";

type Stage = "idle" | "uploading" | "dispatching" | "done" | "error";

const STEPS: { key: Stage; label: string }[] = [
  { key: "uploading", label: "Upload & extract" },
  { key: "dispatching", label: "Dispatch compliance check" },
  { key: "done", label: "Complete" },
];

function stepState(step: Stage, current: Stage): "done" | "active" | "pending" {
  const order: Stage[] = ["uploading", "dispatching", "done"];
  const si = order.indexOf(step);
  const ci = order.indexOf(current);
  if (current === "error") return si === 0 ? "active" : "pending";
  if (ci > si) return "done";
  if (ci === si) return "active";
  return "pending";
}

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

export function UploadView() {
  const { session } = useAuth();
  const toast = useToast();
  const [file, setFile] = useState<File | null>(null);
  const [dragActive, setDragActive] = useState(false);
  const [stage, setStage] = useState<Stage>("idle");
  const [log, setLog] = useState<{ id: number; text: string }[]>([]);
  const [error, setError] = useState<string | null>(null);
  const counter = useRef(0);
  const inputRef = useRef<HTMLInputElement>(null);

  const append = (text: string) =>
    setLog((l) => [{ id: ++counter.current, text }, ...l]);

  const busy = stage === "uploading" || stage === "dispatching";

  const handleUpload = async () => {
    if (!session || !file) return;
    setStage("uploading");
    setError(null);
    try {
      const up = await uploadDocument(session, file);
      append(`Uploaded ${file.name} → ${up.document_id} (ingestion ${up.status})`);
      setStage("dispatching");
      const task = await triggerCheck(session, up.document_id);
      append(`Compliance check dispatched for ${up.document_id} → task ${task.task_id} (${task.status})`);
      setStage("done");
      toast.push({
        kind: "success",
        title: "Document submitted",
        description: `${file.name} is now being scored for compliance risk.`,
      });
    } catch (err) {
      setStage("error");
      if (err instanceof ApiError && err.status === 503) {
        const msg =
          "Pipeline unavailable — the API gateway has no GEMINI_API_KEY configured. Set it and retry.";
        setError(msg);
        toast.push({ kind: "error", title: "Pipeline unavailable", description: msg });
      } else {
        const msg = (err as Error).message;
        setError(msg);
        toast.push({ kind: "error", title: "Upload failed", description: msg });
      }
    }
  };

  const onDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragActive(false);
    const f = e.dataTransfer.files?.[0];
    if (f) {
      setFile(f);
      setStage("idle");
      setError(null);
    }
  }, []);

  return (
    <div className="space-y-6">
      <PageHeading
        kind="Intake"
        title="Upload document"
        subtitle="PDF, text, CSV or image. Fields are extracted, then scored against your ruleset."
      />

      <Card>
        <div
          onDragOver={(e) => {
            e.preventDefault();
            setDragActive(true);
          }}
          onDragLeave={() => setDragActive(false)}
          onDrop={onDrop}
          onClick={() => inputRef.current?.click()}
          className={cn(
            "relative cursor-pointer rounded-xl border-2 border-dashed p-8 text-center transition-colors",
            dragActive
              ? "border-brand-500 bg-brand-50/60 dark:bg-brand-950/30"
              : "border-slate-200 hover:border-brand-300 hover:bg-slate-50 dark:border-slate-700 dark:hover:border-brand-800 dark:hover:bg-slate-800/40",
          )}
        >
          <input
            ref={inputRef}
            type="file"
            accept=".pdf,.txt,.csv,.json,.png,.jpg,.jpeg"
            onChange={(e) => {
              const f = e.target.files?.[0] ?? null;
              setFile(f);
              setStage("idle");
              setError(null);
            }}
            className="hidden"
          />
          <motion.div
            animate={{ scale: dragActive ? 1.08 : 1 }}
            transition={{ type: "spring", stiffness: 400, damping: 20 }}
            className="mx-auto mb-3 grid h-12 w-12 place-items-center rounded-full bg-brand-50 text-brand-600 dark:bg-brand-950/50 dark:text-brand-400"
          >
            <UploadCloud size={22} />
          </motion.div>
          <p className="text-sm font-medium text-slate-700 dark:text-slate-200">
            Drag & drop a file, or click to browse
          </p>
          <p className="mt-1 text-xs text-slate-400 dark:text-slate-500">
            PDF, TXT, CSV, JSON, PNG, JPG
          </p>
        </div>

        <AnimatePresence>
          {file && (
            <motion.div
              initial={{ opacity: 0, height: 0, marginTop: 0 }}
              animate={{ opacity: 1, height: "auto", marginTop: 16 }}
              exit={{ opacity: 0, height: 0, marginTop: 0 }}
              className="overflow-hidden"
            >
              <div className="flex items-center gap-3 rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 dark:border-slate-800 dark:bg-slate-800/50">
                <FileText size={18} className="shrink-0 text-brand-600 dark:text-brand-400" />
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium text-slate-700 dark:text-slate-200">
                    {file.name}
                  </p>
                  <p className="text-xs text-slate-400 dark:text-slate-500">
                    {formatBytes(file.size)}
                  </p>
                </div>
                {!busy && (
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      setFile(null);
                      setStage("idle");
                    }}
                    className="shrink-0 rounded-md p-1 text-slate-400 hover:bg-slate-200 hover:text-slate-600 dark:hover:bg-slate-700"
                    aria-label="Remove file"
                  >
                    <X size={15} />
                  </button>
                )}
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        <div className="mt-5 flex items-center gap-3">
          <Button onClick={handleUpload} disabled={!file || busy} loading={busy} size="lg">
            {busy ? "Processing…" : "Upload & analyze"}
          </Button>
          {stage === "done" && (
            <Link
              to="/"
              className="inline-flex items-center gap-1 text-sm font-medium text-brand-600 hover:text-brand-700 dark:text-brand-400"
            >
              View in task queue <ArrowUpRight size={13} />
            </Link>
          )}
        </div>

        <AnimatePresence>
          {stage !== "idle" && (
            <motion.div
              initial={{ opacity: 0, height: 0, marginTop: 0 }}
              animate={{ opacity: 1, height: "auto", marginTop: 20 }}
              exit={{ opacity: 0, height: 0, marginTop: 0 }}
              className="overflow-hidden"
            >
              <div className="flex items-center gap-2">
                {/* Honest placeholder: no virus scanning happens in this
                    pipeline today. Shown so the roadmap is visible, never
                    implying it ran — permanently dashed/grey, distinct from
                    the real animated steps to its right. */}
                <div className="flex flex-1 items-center gap-2">
                  <div className="flex flex-col items-center gap-1.5">
                    <div className="grid h-7 w-7 place-items-center rounded-full border-2 border-dashed border-slate-300 text-slate-300 dark:border-slate-700 dark:text-slate-600">
                      <ShieldOff size={12} />
                    </div>
                    <span className="hidden text-center text-[11px] font-medium text-slate-400 dark:text-slate-600 sm:block">
                      Virus scan
                      <span className="block text-[9.5px] font-normal uppercase tracking-wide">
                        Coming soon
                      </span>
                    </span>
                  </div>
                  <div className="h-0.5 flex-1 rounded-full bg-slate-100 dark:bg-slate-800" />
                </div>
                {STEPS.map((s, i) => {
                  const st = stepState(s.key, stage);
                  return (
                    <div key={s.key} className="flex flex-1 items-center gap-2">
                      <div className="flex flex-col items-center gap-1.5">
                        <motion.div
                          animate={{ scale: st === "active" ? 1.1 : 1 }}
                          className={cn(
                            "grid h-7 w-7 place-items-center rounded-full border-2 text-xs font-semibold",
                            st === "done" &&
                              "border-status-good bg-status-good text-white",
                            st === "active" &&
                              stage !== "error" &&
                              "border-brand-500 text-brand-600 dark:text-brand-400",
                            st === "active" &&
                              stage === "error" &&
                              "border-status-critical text-status-critical",
                            st === "pending" &&
                              "border-slate-200 text-slate-300 dark:border-slate-700 dark:text-slate-600",
                          )}
                        >
                          {st === "done" ? (
                            <CheckCircle2 size={15} />
                          ) : st === "active" && stage !== "error" ? (
                            <Loader2 size={13} className="animate-spin" />
                          ) : (
                            <Circle size={8} fill="currentColor" />
                          )}
                        </motion.div>
                        <span
                          className={cn(
                            "hidden text-center text-[11px] font-medium sm:block",
                            st === "pending"
                              ? "text-slate-400 dark:text-slate-600"
                              : "text-slate-600 dark:text-slate-300",
                          )}
                        >
                          {s.label}
                        </span>
                      </div>
                      {i < STEPS.length - 1 && (
                        <div className="h-0.5 flex-1 overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800">
                          <motion.div
                            initial={{ width: 0 }}
                            animate={{ width: st === "pending" ? "0%" : "100%" }}
                            transition={{ duration: 0.4 }}
                            className="h-full bg-status-good"
                          />
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        {error && (
          <motion.p
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            className="mt-4 text-sm text-status-critical"
          >
            {error}
          </motion.p>
        )}
      </Card>

      <AnimatePresence>
        {log.length > 0 && (
          <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
            <Card>
              <CardHeader title="Activity" />
              <ul className="space-y-1.5">
                <AnimatePresence initial={false}>
                  {log.map((l) => (
                    <motion.li
                      key={l.id}
                      layout
                      initial={{ opacity: 0, x: -8 }}
                      animate={{ opacity: 1, x: 0 }}
                      className="font-mono-num text-xs text-slate-600 dark:text-slate-400"
                    >
                      {l.text}
                    </motion.li>
                  ))}
                </AnimatePresence>
              </ul>
            </Card>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
