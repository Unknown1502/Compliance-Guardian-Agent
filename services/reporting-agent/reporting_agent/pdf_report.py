"""The compliance report as a document a customer can actually file.

The previous rendering was a readable summary but not a filed document: it was
headed with the internal tenant id rather than the business name, named no
regulatory framework, carried no page numbers, and stated no limitations. A
compliance officer forwarding that to a board or a regulator would have to
explain what it was.

What an official assessment document needs, and why each part is here:

  Identity      The business's registered name, not `tenant-6e918867e99a`.
                A document that cannot say who it is about is not evidence.
  Reference     A report id and generated timestamp on every page, so a page
                separated from the rest can still be traced back.
  Framework     Which rules were applied. "Compliant" is meaningless without
                naming the standard it was assessed against.
  Method        How the conclusion was reached, including that it was
                automated and where a human decided instead.
  Limitations   What this document does NOT establish. An automated
                assessment presented without limits invites reliance it
                cannot carry, which is the failure mode that actually hurts
                a customer — and us.
  Pagination    "Page 2 of 5" is how a reader knows they have all of it.

reportlab stays the renderer: pure Python, so the container needs no browser
engine or cairo/pango layer to build, patch and carry.

Escaping is not optional here. Paragraph parses a small markup dialect, and
the executive summary is Gemini output shaped by a customer-uploaded document
— so an uploaded file carrying markup is an attacker-controlled path into
this parser. Every interpolated value goes through esc().
"""

from __future__ import annotations

import html
from dataclasses import dataclass
from datetime import datetime, timezone
from io import BytesIO

# Mirrors apps/dashboard/src/lib/rulesetLabels.ts. Duplicated deliberately:
# the dashboard cannot import Python and the report must not print a raw code
# like "us-ca" on a filed document. Anything unknown falls back to the code
# itself, so adding a ruleset never blocks on updating this.
JURISDICTION_LABEL: dict[str, str] = {
    "au": "Australia",
    "in": "India",
    "eu": "European Union",
    "uk": "United Kingdom",
    "us-ca": "United States (California)",
    "ca": "Canada",
    "sg": "Singapore",
    "br": "Brazil",
    "cn": "China",
    "ae": "United Arab Emirates",
    "za": "South Africa",
    "generic": "Any jurisdiction",
}

INDUSTRY_LABEL: dict[str, str] = {
    "healthcare_ndis": "NDIS / disability services",
    "aged_care": "Aged care",
    "bookkeeping": "Bookkeeping & payroll",
    "data_privacy": "Data privacy & protection",
    "contract_review": "Contract review",
    "corporate_compliance": "Corporate compliance",
}

INK = "#111827"
MUTED = "#6B7280"
FAINT = "#9CA3AF"
RULE = "#D1D5DB"
BRAND = "#1E3A8A"  # restrained navy; a filed document should not look like an ad
PANEL = "#F9FAFB"


@dataclass(frozen=True)
class TenantProfile:
    """Who the report is about. Falls back to the id when a field is unset,
    because a report must still render for an incomplete tenant record."""

    tenant_id: str
    name: str = ""
    industry: str = ""
    jurisdiction: str = ""

    @property
    def display_name(self) -> str:
        return self.name.strip() or self.tenant_id

    @property
    def framework(self) -> str:
        """The standard assessed against, in words."""
        industry = INDUSTRY_LABEL.get(self.industry.lower(), self.industry)
        # Case-insensitive: tenants created before the picker stored "AU".
        place = JURISDICTION_LABEL.get(self.jurisdiction.lower(), self.jurisdiction)
        if industry and place:
            return f"{industry} — {place}"
        return industry or place or "Not specified"


def esc(value) -> str:
    return html.escape(str(value))


def _fmt_period(start: datetime, end: datetime) -> str:
    return f"{start:%d %B %Y} to {end:%d %B %Y}"


def _numbered_canvas(business: str, report_id: str):
    """Canvas that stamps 'Page X of Y' once the total is known.

    reportlab lays out pages one at a time and cannot know the total until
    the document is finished, so pages are held and the furniture is drawn at
    save() time. Without this the footer can only say "Page 3", which does not
    tell a reader whether anything is missing.
    """
    from reportlab.lib.colors import HexColor
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas as _canvas

    class NumberedCanvas(_canvas.Canvas):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._saved = []

        def showPage(self):
            self._saved.append(dict(self.__dict__))
            self._startPage()

        def save(self):
            total = len(self._saved)
            for state in self._saved:
                self.__dict__.update(state)
                self._draw_furniture(total)
                super().showPage()
            super().save()

        def _draw_furniture(self, total: int):
            width, _ = A4
            page = self._pageNumber

            # Running header from page 2 on: page 1 already carries the
            # letterhead, and repeating it there would just push the title down.
            if page > 1:
                self.setFont("Helvetica", 7.5)
                self.setFillColor(HexColor(MUTED))
                self.drawString(20 * mm, 285 * mm, f"Compliance Assessment Report — {business}")
                self.drawRightString(190 * mm, 285 * mm, report_id)
                self.setStrokeColor(HexColor(RULE))
                self.setLineWidth(0.4)
                self.line(20 * mm, 283 * mm, 190 * mm, 283 * mm)

            self.setStrokeColor(HexColor(RULE))
            self.setLineWidth(0.4)
            self.line(20 * mm, 14 * mm, 190 * mm, 14 * mm)
            self.setFont("Helvetica", 7)
            self.setFillColor(HexColor(FAINT))
            self.drawString(20 * mm, 10 * mm, f"Confidential — prepared for {business}")
            self.drawRightString(190 * mm, 10 * mm, f"Page {page} of {total}")

    return NumberedCanvas


def render_report_pdf(
    *,
    report_id: str,
    tenant: TenantProfile,
    period_start: datetime,
    period_end: datetime,
    stats: dict,
    gemini_data: dict,
    used_fixture: bool,
    model_name: str,
    prompt_version: str,
    generated_at: datetime | None = None,
) -> bytes:
    """Render the compliance report as a filed document."""
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

    generated = generated_at or datetime.now(timezone.utc)
    business = tenant.display_name

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=20 * mm,
        bottomMargin=22 * mm,
        title=f"Compliance Assessment Report — {business}",
        author="ComplianceGuardian",
        subject=f"{tenant.framework}; {_fmt_period(period_start, period_end)}",
        creator="ComplianceGuardian",
    )

    base = getSampleStyleSheet()
    wordmark = ParagraphStyle(
        "cgWordmark", parent=base["BodyText"], fontName="Helvetica-Bold",
        fontSize=9, textColor=colors.HexColor(BRAND), spaceAfter=0,
    )
    title = ParagraphStyle(
        "cgTitle", parent=base["Heading1"], fontName="Helvetica-Bold",
        fontSize=19, leading=23, textColor=colors.HexColor(INK), spaceBefore=6, spaceAfter=2,
    )
    subtitle = ParagraphStyle(
        "cgSubtitle", parent=base["BodyText"], fontSize=11, leading=15,
        textColor=colors.HexColor(MUTED), spaceAfter=2,
    )
    h2 = ParagraphStyle(
        "cgH2", parent=base["Heading2"], fontName="Helvetica-Bold", fontSize=10.5,
        leading=14, spaceBefore=16, spaceAfter=6, textColor=colors.HexColor(BRAND),
        # A section heading stranded at the foot of a page with its content
        # overleaf reads as a printing error in a document meant to be filed.
        keepWithNext=1,
    )
    body = ParagraphStyle(
        "cgBody", parent=base["BodyText"], fontSize=9.5, leading=14.5,
        alignment=TA_LEFT, textColor=colors.HexColor(INK),
    )
    small = ParagraphStyle(
        "cgSmall", parent=body, fontSize=8.5, leading=12.5, textColor=colors.HexColor(MUTED)
    )

    story: list = [
        Paragraph("COMPLIANCEGUARDIAN", wordmark),
        HRFlowable(width="100%", thickness=1.1, color=colors.HexColor(BRAND), spaceBefore=3),
        Paragraph("Compliance Assessment Report", title),
        Paragraph(esc(business), subtitle),
        Paragraph(
            f"Reporting period: {_fmt_period(period_start, period_end)}", small
        ),
        Spacer(1, 14),
    ]

    # -- Document control ---------------------------------------------------
    control_rows = [
        ("Report reference", report_id),
        ("Business", business),
        ("Regulatory framework", tenant.framework),
        ("Reporting period", _fmt_period(period_start, period_end)),
        ("Prepared by", "ComplianceGuardian — automated assessment"),
        ("Analysis model", model_name),
        ("Ruleset revision", prompt_version),
        ("Generated (UTC)", generated.strftime("%Y-%m-%d %H:%M:%S")),
        ("Classification", "Confidential — for internal and regulatory use"),
    ]
    control = Table(
        [[Paragraph(f"<b>{esc(k)}</b>", small), Paragraph(esc(v), small)] for k, v in control_rows],
        colWidths=[45 * mm, 125 * mm],
        hAlign="LEFT",
    )
    control.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(PANEL)),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor(RULE)),
                ("INNERGRID", (0, 0), (-1, -1), 0.4, colors.HexColor(RULE)),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
            ]
        )
    )
    story += [control]

    if used_fixture:
        story += [
            Spacer(1, 10),
            Paragraph(
                "<b>Draft — not a completed assessment.</b> The executive summary in this "
                "document was produced from a fixture rather than a live analysis model, "
                "because no model credential was configured when it was generated. "
                "Regenerate this report before filing or relying on it.",
                ParagraphStyle(
                    "cgWarn", parent=body, fontSize=8.5, leading=12.5,
                    textColor=colors.HexColor("#92400E"),
                    backColor=colors.HexColor("#FEF3C7"),
                    borderColor=colors.HexColor("#F59E0B"),
                    borderWidth=0.6, borderPadding=7,
                ),
            ),
        ]

    # -- Scope and method ---------------------------------------------------
    reviewed = stats["total_checks"]
    story += [
        Paragraph("1. Scope and method", h2),
        Paragraph(
            f"This report covers the {reviewed} document"
            f"{'' if reviewed == 1 else 's'} submitted by {esc(business)} for compliance "
            f"assessment between {_fmt_period(period_start, period_end)}. Each document was "
            f"assessed against the {esc(tenant.framework)} ruleset in force at the time of "
            "submission.",
            body,
        ),
        Spacer(1, 5),
        Paragraph(
            "Assessment is automated. Documents meeting every applicable requirement are "
            "recorded as approved without human involvement. Documents failing a requirement, "
            "or matching a pattern the ruleset marks as high risk, are escalated to a named "
            "reviewer in the business, and the reviewer's decision — not the model's — is what "
            "this report records. Every decision, automated or human, is written to an "
            "append-only audit log retained independently of this document.",
            body,
        ),
    ]

    # -- Assessment summary -------------------------------------------------
    story += [Paragraph("2. Assessment summary", h2)]
    table = Table(
        [
            ["Documents assessed", "Approved", "Escalated for review", "Rejected"],
            [
                str(stats["total_checks"]),
                str(stats["auto_approved"]),
                str(stats["escalated"]),
                str(stats["rejected"]),
            ],
        ],
        colWidths=[42.5 * mm] * 4,
        hAlign="LEFT",
    )
    table.setStyle(
        TableStyle(
            [
                ("FONTSIZE", (0, 0), (-1, 0), 7.5),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica"),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor(MUTED)),
                ("FONTNAME", (0, 1), (-1, 1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 1), (-1, 1), 16),
                ("TEXTCOLOR", (0, 1), (-1, 1), colors.HexColor(INK)),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, 0), 7),
                ("BOTTOMPADDING", (0, 1), (-1, 1), 9),
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(PANEL)),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor(RULE)),
                ("INNERGRID", (0, 0), (-1, -1), 0.4, colors.HexColor(RULE)),
            ]
        )
    )
    story += [table]

    if reviewed == 0:
        story += [
            Spacer(1, 6),
            Paragraph(
                "No documents were submitted in this period. This is a nil return: it records "
                "the absence of activity, not an absence of obligation.",
                small,
            ),
        ]

    # -- Risk patterns ------------------------------------------------------
    top_patterns = gemini_data.get("top_3_risk_patterns") or stats.get("top_failing_rule_ids", [])
    frequency = stats.get("citation_frequency") or {}
    story += [Paragraph("3. Recurring findings", h2)]
    if top_patterns:
        story += [
            Paragraph(
                "The requirements cited most often across assessed documents in this period, "
                "most frequent first:",
                body,
            ),
            Spacer(1, 4),
            ListFlowable(
                [
                    ListItem(
                        Paragraph(
                            esc(p) + (f" — cited {frequency[p]} times" if p in frequency else ""),
                            body,
                        ),
                        leftIndent=12,
                    )
                    for p in top_patterns
                ],
                bulletType="bullet",
                start="•",
            ),
        ]
    else:
        story += [
            Paragraph(
                "No requirement was cited more than once in this period.", body
            )
        ]

    # -- Executive summary --------------------------------------------------
    story += [
        Paragraph("4. Executive summary", h2),
        Paragraph(esc(gemini_data.get("executive_summary", "No summary available.")), body),
    ]

    # -- Basis and limitations ----------------------------------------------
    story += [
        Paragraph("5. Basis and limitations", h2),
        Paragraph(
            "This document reports the outcome of an automated assessment against the ruleset "
            "named above. It is a record of what was assessed and what was decided. It is not "
            "legal advice, not a certification, and not an audit opinion, and it does not "
            "establish compliance with any law or standard.",
            body,
        ),
        Spacer(1, 5),
        Paragraph(
            "The assessment covers only documents submitted to ComplianceGuardian during the "
            "reporting period. Obligations arising from records held elsewhere, or from conduct "
            "not evidenced in a submitted document, are outside its scope. Rulesets are derived "
            "from published guidance and are maintained on a best-effort basis; where a ruleset "
            "and the current regulatory text differ, the regulatory text governs.",
            body,
        ),
        Spacer(1, 5),
        Paragraph(
            "Escalated items reflect a decision recorded by a named reviewer within the "
            "business. Responsibility for those decisions, and for acting on the findings in "
            "this report, rests with the business.",
            body,
        ),
        Spacer(1, 14),
        HRFlowable(width="100%", thickness=0.5, color=colors.HexColor(RULE)),
        Spacer(1, 5),
        Paragraph(
            f"End of report &nbsp;·&nbsp; {esc(report_id)} &nbsp;·&nbsp; "
            f"generated {generated.strftime('%Y-%m-%d %H:%M:%S')} UTC by ComplianceGuardian "
            f"({esc(model_name)})",
            ParagraphStyle("cgEnd", parent=small, fontSize=7.5, textColor=colors.HexColor(FAINT)),
        ),
    ]

    doc.build(story, canvasmaker=_numbered_canvas(business, report_id))
    return buf.getvalue()
