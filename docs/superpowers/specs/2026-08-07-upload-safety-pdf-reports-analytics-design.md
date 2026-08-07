# Design: upload content validation, PDF reports, cross-tenant analytics

Date: 2026-08-07
Status: approved (pending spec review)

## Context

Audit of the current codebase turned up three real gaps against the original
PRD/README promises. A fourth candidate — escalation notifications — turned
out to already be fully implemented (`shared/notifications/__init__.py`'s
`SlackNotifier`, wired into `composition.py`, with a Settings UI and test-send
endpoint) and is out of scope here.

This spec covers the three remaining items. They are independent of each
other and are implemented/reviewed as separate units.

## 1. Upload content validation

### Problem

`POST /api/documents` ([api_gateway/main.py:394](../../../apps/api-gateway/api_gateway/main.py#L394))
validates uploads by size (`MAX_UPLOAD_BYTES`) and by the client-supplied
`Content-Type` header against an allowlist. It never checks that the actual
bytes match the declared type — a file can be labelled `application/pdf` and
contain anything. Separately, `data = await file.read()` buffers the entire
body into memory before the size check runs, so the size limit doesn't bound
memory usage.

Files are never executed as code today (storage is GCS, downstream consumers
either hash the bytes, pass them to Gemini as inert `Part` data, or
UTF-8-decode them into a JSON `text` field that React renders as text, never
HTML) — so this is a content-integrity/defense-in-depth gap, not an RCE path.

### Design

Add `shared/upload_validation/__init__.py`:

- `sniff_content_type(data: bytes) -> str | None` — checks magic bytes against
  a small signature table for the six allowed types:
  - `application/pdf` → starts with `%PDF-`
  - `image/png` → starts with `\x89PNG\r\n\x1a\n`
  - `image/jpeg` → starts with `\xff\xd8\xff`
  - `text/plain`, `text/csv`, `application/json` — no magic bytes exist for
    these; instead verify the payload decodes as UTF-8 and contains no NUL
    bytes (rules out binaries mislabelled as text)
  - Returns `None` if the bytes don't match any known signature.
- `validate_upload(data: bytes, declared_content_type: str) -> None` — raises
  `ContentMismatchError` if `sniff_content_type(data)` disagrees with
  `declared_content_type`.

Wire into `upload_document`:

1. Keep the existing declared-type allowlist check (cheap, fails fast on
   obviously wrong requests).
2. Cap the read itself — read in chunks up to `MAX_UPLOAD_BYTES + 1` and abort
   as soon as that's exceeded, instead of reading an unbounded body first.
3. After reading, call `validate_upload`; a `ContentMismatchError` maps to
   `415 Unsupported Media Type` with a message that doesn't leak which byte
   pattern was expected (avoid giving an attacker a signature oracle).
4. On rejection, audit-log `document.upload_rejected` (tenant_id, declared
   type, sniffed type or null, size) — rejected uploads are still a security
   signal worth keeping.

### Testing

Unit tests in `tests/unit/test_upload_validation.py`: each allowed type with
correct bytes (accepted), each type with mismatched/wrong-signature bytes
(rejected), a text file containing a NUL byte (rejected), an empty file
(existing behavior unchanged), a file at exactly `MAX_UPLOAD_BYTES` (accepted)
and one byte over (rejected without full buffering — assert via a large
fake stream that the handler stops reading early).

## 2. PDF reports

### Problem

`reporting_agent/reporter.py`'s `generate_report()` renders an HTML string
and uploads it to GCS as `report.html`. The PRD and README both describe
"download PDF." There is no PDF rendering anywhere in the codebase.

### Design

Add WeasyPrint (`weasyprint` on PyPI) to `services/reporting-agent`'s
dependencies. WeasyPrint renders the *same* HTML template already produced by
`_render_html()` — no template rewrite, just render-to-PDF instead of
(or in addition to) writing raw HTML.

Changes to `reporter.py`:

- After building `html`, call `HTML(string=html).write_pdf()` to get PDF
  bytes.
- Upload path becomes `{tenant_id}/{report_id}/report.pdf`,
  `content_type="application/pdf"`.
- Keep writing the HTML too, at `report.html` alongside it — cheap, and
  useful for debugging/rendering-diff without opening a PDF viewer. Only the
  PDF path goes into `ReportRow.content_ref` (what `/api/reports/:id` hands
  back to the dashboard's download button).
- If `write_pdf()` raises (WeasyPrint has real failure modes — missing system
  fonts, malformed CSS), fall back to uploading HTML only and record
  `content_ref` pointing at the `.html` object, same as today. A report must
  never fail to generate because PDF rendering failed; log the failure to the
  audit trail (`report.pdf_render_failed`) so it's visible, not silent.

Infra: WeasyPrint requires system libraries (Cairo, Pango, GDK-Pixbuf) that
aren't in the current `reporting-agent` container image. This is a real
Dockerfile change and redeploy of a live Cloud Run service — flagged
explicitly since this project is billed and running in production
(`cg-guardian-9856`).

Dashboard: the existing "download report" action already just follows
`content_ref`; no dashboard code change needed beyond confirming the download
button sets the right filename extension.

### Testing

Extend `tests/unit` reporting tests: `generate_report()` produces a
`content_ref` ending in `.pdf`; the WeasyPrint-failure path is exercised with
a monkeypatched `write_pdf` that raises, asserting `content_ref` falls back to
`.html` and the audit log records the failure. PDF byte validity itself
(starts with `%PDF-`) is asserted on the uploaded blob in the one existing
integration-style test that hits real GCS.

## 3. Cross-tenant analytics ("Trends" view)

### Problem

`reporter.py`'s `_aggregate_checks()` computes exactly the right shape of
data — decision counts, top-3 rule-citation frequency — but only for one
report's period, computed fresh each time a report is generated. There's no
view of how risk/compliance is trending over time, and no way to see it
without generating a report.

### Design

Extract the aggregation into a shared, reusable function in
`shared/schema_validators` or a new small `shared/analytics/__init__.py`
(mirrors the existing `shared/*` module pattern):

- `aggregate_period(db, *, tenant_id, period_start, period_end) -> PeriodStats`
  — same logic as today's `_aggregate_checks`, promoted out of
  `reporting_agent` so both reporting and analytics call the same function.
  `reporter.py` is updated to call this instead of its private copy.
- `weekly_trend(db, *, tenant_id, weeks: int = 12) -> list[PeriodStats]` —
  calls `aggregate_period` once per ISO week going back `weeks` weeks from
  now. Firestore-only (same data source reporting already uses — no new BQ
  query-job billing surface, consistent with the existing "GCS/Firestore
  before BQ" cost-conscious design note in `reporter.py`).

New endpoint in `api_gateway/main.py`:

```
GET /api/analytics/trends?weeks=12
```

Tenant-scoped like everything else (from JWT claims). Returns weekly buckets
of `{week_start, total_checks, auto_approved, escalated, rejected,
top_failing_rule_ids}` plus an all-time "top violations" leaderboard (same
citation-counting logic, unbounded window instead of one report's period).

Dashboard: new `AnalyticsView.tsx` — a line/area chart of the decision mix
over the last 12 weeks, and a ranked list of the most-cited rules
tenant-wide. Chart implementation follows the `dataviz` skill's guidance at
build time (color, form, accessibility) rather than ad hoc styling.

### Error handling

A tenant with zero checks in the window returns all-zero buckets, not an
error — same "valid empty-state" precedent `reporter.py` already sets for a
report with no activity in its period.

### Testing

Unit tests for `aggregate_period` (moved logic, same test cases the reporting
tests already cover) and `weekly_trend` (12 buckets returned regardless of
data, correct week boundaries, all-zero buckets for an empty tenant). A
dashboard component test or manual check that `AnalyticsView` renders for
both a populated and an empty tenant.

## Out of scope

- Email as a second notification transport (Slack already covers the
  escalation-alert need; can be added later behind the existing `Notifier`
  interface without touching this work).
- Malware/AV scanning of uploaded files — noted as a future defense-in-depth
  item, not required given files are never executed and the primary
  remaining risk (content/type mismatch) is what this spec's upload
  validation closes.
- Historical backfill of trend data older than what's already in Firestore's
  live `compliance_checks` collection (no BigQuery audit-log-based trend
  query — out of scope, see cost-consciousness note above).
