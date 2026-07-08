import { useState } from "react";
import { uploadDocument, triggerCheck, ApiError } from "../api/client";
import { useAuth } from "../auth/AuthContext";

export function UploadView() {
  const { session } = useAuth();
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [log, setLog] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);

  const append = (line: string) => setLog((l) => [line, ...l]);

  const handleUpload = async () => {
    if (!session || !file) return;
    setBusy(true);
    setError(null);
    try {
      const up = await uploadDocument(session, file);
      append(`Uploaded ${file.name} → ${up.document_id} (ingestion ${up.status})`);
      // Auto-trigger a compliance check once ingested.
      const task = await triggerCheck(session, up.document_id);
      append(
        `Compliance check dispatched for ${up.document_id} → task ${task.task_id} (${task.status})`,
      );
    } catch (err) {
      if (err instanceof ApiError && err.status === 503) {
        setError(
          "Pipeline unavailable — the API gateway has no GEMINI_API_KEY configured. Set it and retry.",
        );
      } else {
        setError((err as Error).message);
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-lg font-semibold text-slate-800">Upload document</h2>
        <p className="text-sm text-slate-500">
          PDF, text, CSV or image. Ingestion extracts fields with Gemini, then a
          compliance check scores risk against your ruleset.
        </p>
      </div>

      <div className="bg-white rounded-xl border border-slate-200 p-6 space-y-4">
        <input
          type="file"
          accept=".pdf,.txt,.csv,.json,.png,.jpg,.jpeg"
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          className="block w-full text-sm text-slate-600 file:mr-4 file:py-2 file:px-4 file:rounded-lg file:border-0 file:bg-brand-50 file:text-brand-700 hover:file:bg-brand-100"
        />
        <button
          onClick={handleUpload}
          disabled={!file || busy}
          className="bg-brand-600 hover:bg-brand-700 disabled:opacity-50 text-white rounded-lg px-4 py-2 text-sm font-medium"
        >
          {busy ? "Processing…" : "Upload & analyze"}
        </button>
        {error && <p className="text-sm text-red-600">{error}</p>}
      </div>

      {log.length > 0 && (
        <div className="bg-white rounded-xl border border-slate-200 p-4">
          <h3 className="text-sm font-medium text-slate-700 mb-2">Activity</h3>
          <ul className="space-y-1 text-sm text-slate-600 font-mono">
            {log.map((l, i) => (
              <li key={i}>{l}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
