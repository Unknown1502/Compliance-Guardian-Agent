"""Reporting Agent core — aggregate Firestore data, generate report via Gemini.

Design decisions (Phase 4 Thinking Protocol):

  Data source: aggregate from Firestore `compliance_checks` (live state) rather
  than the BQ `audit_logs` table. The audit table's before/after JSON columns
  are not structured for aggregation, and the Firestore SDK lets us query by
  tenant_id + created_at range without needing a BQ query job — simpler and
  avoids the BQ query-job billing surface for small tenants.

  Empty period: produces a valid "no activity" report rather than failing.

  GCS before BQ: write the HTML artifact to GCS first. Only if that succeeds
  do we append the BQ `reports` row. This prevents orphaned BQ rows that point
  to a GCS path that doesn't exist.

  Fixture fallback: if GEMINI_API_KEY is absent (no key provided in Phase 4),
  a clearly-marked fixture executive summary is used so the report pipeline
  runs end-to-end and the BQ row + GCS artifact are still written. The fixture
  is labelled in the output so no human is misled.

  Two artifacts, one source: the report is rendered to BOTH PDF and HTML from
  the same stats/summary data, rather than converting HTML to PDF. Converting
  would mean shipping a browser engine (or cairo/pango) into a slim container
  to lay out a document that is really a dozen fields; building each renderer
  from the structured data keeps the image small and both outputs simple.

  Escaping: everything interpolated into the HTML is escaped. The executive
  summary is Gemini output, and Gemini's output is shaped by the document a
  customer uploaded — so an uploaded file carrying a prompt injection is an
  attacker-controlled path into markup that a reviewer's browser renders.
"""

from __future__ import annotations

import html
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from io import BytesIO

from analytics import aggregate_period
from audit_logger import AuditLogger
from gcp_clients import reports_bucket
from gcp_clients.firestore_repo import FirestoreRepo
from google.cloud import bigquery, firestore, storage
from schema_validators import ReportRow

from reporting_agent.prompts import (
    REPORTING_PROMPT_VERSION,
    REPORTING_SYSTEM_INSTRUCTION,
    build_reporting_user_prompt,
)

logger = logging.getLogger("cg.reporting")


@dataclass(frozen=True)
class ReportOutcome:
    report_id: str
    tenant_id: str
    period_start: datetime
    period_end: datetime
    content_ref: str
    stats: dict
    gemini_executive_summary: str
    prompt_version: str
    model_name: str
    model_version: str | None
    used_fixture: bool
    # gs:// path to the PDF rendering. Empty when PDF generation failed —
    # a missing PDF must not cost the tenant the report itself.
    pdf_ref: str = ""


def _render_html(
    *,
    report_id: str,
    tenant_id: str,
    period_start: datetime,
    period_end: datetime,
    stats: dict,
    gemini_data: dict,
    used_fixture: bool,
    model_name: str,
    prompt_version: str,
) -> str:
    fixture_banner = (
        '<div style="background:#fff3cd;border:1px solid #ffc107;padding:8px;'
        'margin-bottom:12px;border-radius:4px;font-size:12px;">'
        "⚠ Executive summary generated with a FIXTURE (no GEMINI_API_KEY configured). "
        "Set the key and regenerate for a real Gemini-authored summary."
        "</div>"
        if used_fixture
        else ""
    )
    top_patterns = gemini_data.get("top_3_risk_patterns") or stats.get("top_failing_rule_ids", [])
    patterns_html = (
        "".join(f"<li>{html.escape(str(p))}</li>" for p in top_patterns)
        if top_patterns
        else "<li>None</li>"
    )
    safe_tenant = html.escape(str(tenant_id))
    safe_summary = html.escape(str(gemini_data.get("executive_summary", "No summary available.")))
    safe_model = html.escape(str(model_name))
    safe_prompt_version = html.escape(str(prompt_version))
    safe_report_id = html.escape(str(report_id))
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>Compliance Report — {safe_tenant} — {period_start.date()} to {period_end.date()}</title>
<style>
  body{{font-family:sans-serif;max-width:820px;margin:40px auto;color:#1a1a2e;line-height:1.6}}
  h1{{color:#1d4ed8}} h2{{color:#374151;border-bottom:1px solid #e5e7eb;padding-bottom:4px}}
  .stat{{display:inline-block;margin:8px;padding:16px 24px;border-radius:8px;
    background:#f3f4f6;text-align:center}}
  .stat .n{{font-size:2rem;font-weight:700;color:#1d4ed8}}
  .stat .l{{font-size:.85rem;color:#6b7280}}
  .summary{{background:#eff6ff;border-left:4px solid #2563eb;padding:16px;border-radius:4px}}
  .meta{{font-size:.8rem;color:#9ca3af;margin-top:32px}}
</style>
</head>
<body>
{fixture_banner}
<h1>Compliance Report</h1>
<p><strong>Tenant:</strong> {safe_tenant}</p>
<p><strong>Period:</strong> {period_start.date()} – {period_end.date()}</p>

<h2>Summary statistics</h2>
<div class="stat"><div class="n">{stats['total_checks']}</div><div class="l">Documents reviewed</div></div>
<div class="stat"><div class="n">{stats['auto_approved']}</div><div class="l">Auto-approved</div></div>
<div class="stat"><div class="n">{stats['escalated']}</div><div class="l">Escalated</div></div>
<div class="stat"><div class="n">{stats['rejected']}</div><div class="l">Rejected</div></div>

<h2>Top 3 recurring risk patterns</h2>
<ul>{patterns_html}</ul>

<h2>Executive summary</h2>
<div class="summary">{safe_summary}</div>

<div class="meta">
  Report ID: {safe_report_id}<br/>
  Generated by: reporting-agent@{safe_prompt_version}<br/>
  AI model: {safe_model}<br/>
  Generated at: {datetime.now(timezone.utc).isoformat()}
</div>
</body>
</html>"""


def _render_pdf(
    *,
    report_id: str,
    tenant_id: str,
    period_start: datetime,
    period_end: datetime,
    stats: dict,
    gemini_data: dict,
    used_fixture: bool,
    model_name: str,
    prompt_version: str,
) -> bytes:
    """Render the report as a PDF, built from the data rather than from HTML.

    reportlab is pure Python, so the container stays on python:3.11-slim with
    no cairo/pango/browser layer to install, patch and carry.

    Everything interpolated is escaped: reportlab's Paragraph takes a small
    markup dialect, so an unescaped '<' in a Gemini summary is a rendering
    failure at best and injected markup at worst — the same exposure the HTML
    renderer has, through a different parser.
    """
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        HRFlowable,
        ListFlowable,
        ListItem,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    def esc(value) -> str:
        return html.escape(str(value))

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=f"Compliance Report — {tenant_id}",
        author="ComplianceGuardian",
        subject=f"{period_start.date()} to {period_end.date()}",
    )

    base = getSampleStyleSheet()
    h1 = ParagraphStyle(
        "cgH1", parent=base["Heading1"], fontSize=20, spaceAfter=2, textColor=colors.HexColor("#1D4ED8")
    )
    h2 = ParagraphStyle(
        "cgH2", parent=base["Heading2"], fontSize=12, spaceBefore=14, spaceAfter=6,
        textColor=colors.HexColor("#374151"),
    )
    body = ParagraphStyle(
        "cgBody", parent=base["BodyText"], fontSize=9.5, leading=14, alignment=TA_LEFT
    )
    meta = ParagraphStyle(
        "cgMeta", parent=base["BodyText"], fontSize=7.5, leading=11,
        textColor=colors.HexColor("#9CA3AF"),
    )

    story: list = [
        Paragraph("Compliance Report", h1),
        Paragraph(
            f"{esc(tenant_id)} &nbsp;·&nbsp; {period_start.date()} to {period_end.date()}", meta
        ),
        Spacer(1, 4),
        HRFlowable(width="100%", thickness=0.7, color=colors.HexColor("#E5E7EB")),
    ]

    if used_fixture:
        story += [
            Spacer(1, 8),
            Paragraph(
                "<b>Note:</b> the executive summary below was generated with a fixture, "
                "not a live AI model, because no API key was configured. Regenerate once "
                "a key is set for a real Gemini-authored summary.",
                ParagraphStyle(
                    "cgWarn", parent=body, fontSize=8.5,
                    textColor=colors.HexColor("#92400E"),
                    backColor=colors.HexColor("#FEF3C7"),
                    borderPadding=6, leading=12,
                ),
            ),
        ]

    story += [Paragraph("Summary statistics", h2)]
    table = Table(
        [
            ["Documents reviewed", "Auto-approved", "Escalated", "Rejected"],
            [
                str(stats["total_checks"]),
                str(stats["auto_approved"]),
                str(stats["escalated"]),
                str(stats["rejected"]),
            ],
        ],
        colWidths=[42 * mm] * 4,
    )
    table.setStyle(
        TableStyle(
            [
                ("FONTSIZE", (0, 0), (-1, 0), 8),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#6B7280")),
                ("FONTNAME", (0, 1), (-1, 1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 1), (-1, 1), 17),
                ("TEXTCOLOR", (0, 1), (-1, 1), colors.HexColor("#111827")),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, 0), 8),
                ("BOTTOMPADDING", (0, 1), (-1, 1), 10),
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F9FAFB")),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#E5E7EB")),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E5E7EB")),
            ]
        )
    )
    story += [table]

    top_patterns = gemini_data.get("top_3_risk_patterns") or stats.get("top_failing_rule_ids", [])
    story += [Paragraph("Top recurring risk patterns", h2)]
    if top_patterns:
        story += [
            ListFlowable(
                [ListItem(Paragraph(esc(p), body), leftIndent=12) for p in top_patterns],
                bulletType="bullet",
                start="•",
            )
        ]
    else:
        story += [Paragraph("None identified in this period.", body)]

    story += [
        Paragraph("Executive summary", h2),
        Paragraph(esc(gemini_data.get("executive_summary", "No summary available.")), body),
        Spacer(1, 18),
        HRFlowable(width="100%", thickness=0.7, color=colors.HexColor("#E5E7EB")),
        Spacer(1, 6),
        Paragraph(
            f"Report ID: {esc(report_id)}<br/>"
            f"Generated by: reporting-agent@{esc(prompt_version)}<br/>"
            f"AI model: {esc(model_name)}<br/>"
            f"Generated at: {datetime.now(timezone.utc).isoformat()}",
            meta,
        ),
    ]

    doc.build(story)
    return buf.getvalue()


def _fixture_gemini_data(stats: dict) -> dict:
    top = stats.get("top_failing_rule_ids", [])
    summary = (
        f"During this period, {stats['total_checks']} compliance checks were completed for "
        f"your business. {stats['auto_approved']} documents were automatically approved as "
        f"fully compliant, while {stats['escalated'] + stats['rejected']} required human "
        f"review or were rejected. "
    )
    if top:
        summary += (
            f"The most frequently flagged compliance requirement was '{top[0]}'. "
            "We recommend reviewing your document templates to ensure this requirement is "
            "consistently met before submission."
        )
    else:
        summary += "No recurring risk patterns were identified — good standing overall."
    return {
        "total_documents_processed": stats["total_checks"],
        "pass_count": stats["auto_approved"],
        "fail_count": stats["rejected"],
        "escalated_count": stats["escalated"],
        "top_3_risk_patterns": top,
        "executive_summary": summary + " [FIXTURE — no GEMINI_API_KEY configured]",
    }


def generate_report(
    *,
    tenant_id: str,
    period_start: datetime,
    period_end: datetime,
    db: firestore.Client,
    bq_client: bigquery.Client,
    storage_client: storage.Client,
    auditor: AuditLogger,
    gemini,  # GeminiClient | None
    bq_dataset: str,
    bq_reports_table: str,
    bq_project: str,
    generated_by: str = "reporting-agent",
) -> ReportOutcome:
    """Generate one compliance report for a tenant. Writes HTML to GCS + row to BigQuery."""
    report_id = str(uuid.uuid4())
    used_fixture = False
    model_name = "fixture"
    model_version = None

    stats = aggregate_period(db, tenant_id=tenant_id, period_start=period_start, period_end=period_end)

    try:
        if gemini is None:
            raise RuntimeError("no Gemini client available")
        user_prompt = build_reporting_user_prompt(
            period_start=period_start, period_end=period_end, stats=stats
        )
        result = gemini.generate_json(
            prompt_version=REPORTING_PROMPT_VERSION,
            system_instruction=REPORTING_SYSTEM_INSTRUCTION,
            user_content=user_prompt,
        )
        gemini_data = result.data
        model_name = result.model_name
        model_version = result.model_version
        prompt_version = result.prompt_version
    except Exception as exc:
        logger.warning("Gemini unavailable for reporting (%s) — using fixture", exc)
        gemini_data = _fixture_gemini_data(stats)
        used_fixture = True
        prompt_version = f"{REPORTING_PROMPT_VERSION}_fixture"

    render_kwargs = dict(
        report_id=report_id,
        tenant_id=tenant_id,
        period_start=period_start,
        period_end=period_end,
        stats=stats,
        gemini_data=gemini_data,
        used_fixture=used_fixture,
        model_name=model_name,
        prompt_version=prompt_version,
    )
    # Named html_doc, not html: a local called `html` shadows the stdlib module
    # this file escapes with, and the next person to move a line would find out
    # the hard way.
    html_doc = _render_html(**render_kwargs)

    bucket_name = reports_bucket()
    blob_path = f"{tenant_id}/{report_id}/report.html"
    bucket = storage_client.bucket(bucket_name)
    bucket.blob(blob_path).upload_from_string(html_doc.encode("utf-8"), content_type="text/html")
    content_ref = f"gs://{bucket_name}/{blob_path}"
    logger.info("report HTML written to %s", content_ref)

    # PDF is the deliverable customers actually file, but it is rendered after
    # the HTML and never allowed to fail the report: a PDF library problem
    # would otherwise cost the tenant a report they can still read in a
    # browser. pdf_ref stays empty and the caller falls back to HTML.
    pdf_ref = ""
    try:
        pdf_bytes = _render_pdf(**render_kwargs)
        pdf_path = f"{tenant_id}/{report_id}/report.pdf"
        bucket.blob(pdf_path).upload_from_string(pdf_bytes, content_type="application/pdf")
        pdf_ref = f"gs://{bucket_name}/{pdf_path}"
        logger.info("report PDF written to %s", pdf_ref)
    except Exception:
        logger.exception("PDF rendering failed for report %s — HTML still available", report_id)

    row = ReportRow(
        report_id=report_id,
        tenant_id=tenant_id,
        period_start=period_start,
        period_end=period_end,
        generated_by=f"{generated_by}@{prompt_version}",
        content_ref=content_ref,
    )
    table_ref = f"{bq_project}.{bq_dataset}.{bq_reports_table}"
    payload = {
        "report_id": row.report_id,
        "tenant_id": row.tenant_id,
        "period_start": row.period_start.isoformat(),
        "period_end": row.period_end.isoformat(),
        "generated_by": row.generated_by,
        "content_ref": row.content_ref,
        "created_at": row.created_at.isoformat(),
    }
    errors = bq_client.insert_rows_json(table_ref, [payload], row_ids=[report_id])
    if errors:
        logger.error("BQ report row insert errors: %s", errors)

    auditor.log(
        tenant_id=tenant_id,
        actor=generated_by,
        action="report.generated",
        dedup_key=report_id,
        before_state=None,
        after_state={
            "report_id": report_id,
            "content_ref": content_ref,
            "pdf_ref": pdf_ref,
            "total_checks": stats["total_checks"],
            "model_name": model_name,
            "used_fixture": used_fixture,
        },
    )

    return ReportOutcome(
        report_id=report_id,
        tenant_id=tenant_id,
        period_start=period_start,
        period_end=period_end,
        content_ref=content_ref,
        stats=stats,
        gemini_executive_summary=str(gemini_data.get("executive_summary", "")),
        prompt_version=prompt_version,
        model_name=model_name,
        model_version=model_version,
        used_fixture=used_fixture,
        pdf_ref=pdf_ref,
    )
