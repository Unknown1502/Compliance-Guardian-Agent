"""The report PDF as a document someone can file.

Reported: the downloaded report "is not proper, it must be in pdf form and
official form". Two separate faults sat behind that.

The download was HTML because no report had been generated since PDF
rendering shipped, so the endpoint's HTML fallback was always taken.

And the PDF, once produced, was not a document a compliance officer could
forward. It was headed with the internal tenant id rather than the business
name, named no regulatory framework, carried no page numbers, and stated no
limitations — so a reader could not tell who it concerned, what it was
assessed against, whether they had all of it, or what it did not establish.

These tests assert the properties that make it a record rather than a
printout, by extracting the text back out of the rendered PDF.
"""

from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO

import pytest
from pypdf import PdfReader

from reporting_agent.pdf_report import TenantProfile, render_report_pdf

STATS = {
    "total_checks": 42,
    "auto_approved": 30,
    "escalated": 8,
    "rejected": 4,
    "top_failing_rule_ids": ["participant_consent_documented", "worker_screening_current"],
    "citation_frequency": {"participant_consent_documented": 11, "worker_screening_current": 3},
}

GEMINI = {
    "executive_summary": "Consent records were the most frequent gap this period.",
    "top_3_risk_patterns": ["participant_consent_documented", "worker_screening_current"],
}

SUNRISE = TenantProfile(
    tenant_id="tenant-sunrise-care",
    name="Sunrise Community Care Pty Ltd",
    industry="healthcare_ndis",
    jurisdiction="au",
)


def render(tenant=SUNRISE, stats=None, gemini=None, **overrides) -> bytes:
    kwargs = dict(
        report_id="a1ae69b3-6f60-4ab0-9e9d-5bb7a4a60116",
        tenant=tenant,
        period_start=datetime(2026, 7, 1, tzinfo=timezone.utc),
        period_end=datetime(2026, 7, 31, tzinfo=timezone.utc),
        stats=stats or STATS,
        gemini_data=gemini or GEMINI,
        used_fixture=False,
        model_name="gemini-3.1-flash-lite",
        prompt_version="reporting_v1",
    )
    kwargs.update(overrides)
    return render_report_pdf(**kwargs)


def text_of(pdf: bytes) -> str:
    return "\n".join(p.extract_text() for p in PdfReader(BytesIO(pdf)).pages)


def pages_of(pdf: bytes) -> list[str]:
    return [p.extract_text() for p in PdfReader(BytesIO(pdf)).pages]


class TestItIsActuallyAPdf:
    def test_it_starts_with_the_pdf_magic_bytes(self):
        assert render().startswith(b"%PDF-")

    def test_it_is_finalised(self):
        """A truncated PDF opens in some viewers and not others."""
        assert b"%%EOF" in render()


class TestItSaysWhoItIsAbout:
    """An internal id on a filed document tells the reader nothing."""

    def test_the_business_name_appears(self):
        assert "Sunrise Community Care Pty Ltd" in text_of(render())

    def test_the_tenant_id_is_not_the_heading(self):
        body = text_of(render())
        assert not body.lstrip().startswith("tenant-")

    def test_an_unnamed_tenant_falls_back_to_its_id(self):
        """A report must still render for an incomplete tenant record."""
        pdf = render(tenant=TenantProfile(tenant_id="tenant-xyz"))
        assert "tenant-xyz" in text_of(pdf)


class TestItSaysWhatItWasAssessedAgainst:
    """"Compliant" means nothing without naming the standard."""

    def test_the_framework_is_named_in_words(self):
        body = text_of(render())
        assert "NDIS / disability services" in body
        assert "Australia" in body

    def test_a_raw_code_is_never_printed_when_a_label_exists(self):
        assert "healthcare_ndis" not in text_of(render())

    def test_jurisdiction_matching_is_case_insensitive(self):
        """Tenants created before the picker stored "AU", not "au"."""
        pdf = render(tenant=TenantProfile("t", "Acme", "aged_care", "AU"))
        assert "Australia" in text_of(pdf)

    def test_an_unknown_code_falls_back_to_itself(self):
        """Adding a ruleset must not block on updating the label map."""
        pdf = render(tenant=TenantProfile("t", "Acme", "aged_care", "nz"))
        assert "nz" in text_of(pdf)


class TestItCanBeCheckedForCompleteness:
    def test_every_page_is_numbered_out_of_the_total(self):
        pages = pages_of(render())
        assert len(pages) >= 2, "sample should span pages for this to mean anything"
        for i, page in enumerate(pages, 1):
            assert f"Page {i} of {len(pages)}" in page

    def test_the_report_id_appears_on_every_page(self):
        """A page separated from the rest must still be traceable."""
        for page in pages_of(render()):
            assert "a1ae69b3" in page

    def test_every_page_carries_the_confidentiality_marking(self):
        for page in pages_of(render()):
            assert "Confidential" in page

    def test_it_marks_its_own_end(self):
        assert "End of report" in text_of(render())

    def test_no_section_heading_is_stranded_at_the_foot_of_a_page(self):
        """A heading whose content is overleaf reads as a printing error."""
        import re

        furniture = ("Confidential", "Page ", "Compliance Assessment Report")
        for number, page in enumerate(pages_of(render()), 1):
            content = [
                line
                for line in page.split("\n")
                if line.strip()
                and not line.startswith(furniture)
                and not re.fullmatch(r"[0-9a-f-]{36}", line.strip())
            ]
            if content:
                assert not re.match(r"^\d\.\s", content[-1]), (
                    f"page {number} ends on the heading {content[-1]!r}"
                )


class TestItStatesWhatItDoesNotEstablish:
    """An automated assessment presented without limits invites reliance it
    cannot carry."""

    @pytest.mark.parametrize(
        "phrase",
        ["not legal advice", "not a certification", "not an audit opinion"],
    )
    def test_the_disclaimer_is_present(self, phrase):
        assert phrase in text_of(render())

    def test_it_says_the_regulatory_text_governs(self):
        assert "regulatory text governs" in text_of(render())

    def test_it_places_responsibility_with_the_business(self):
        assert "rests with the business" in text_of(render())


class TestFixtureDataIsDeclared:
    def test_a_fixture_report_is_marked_as_draft(self):
        """Nobody should file a report whose summary was not really generated."""
        body = text_of(render(used_fixture=True))
        assert "Draft" in body
        assert "not a completed assessment" in body

    def test_a_real_report_carries_no_draft_marking(self):
        assert "not a completed assessment" not in text_of(render(used_fixture=False))


class TestEdgeCases:
    def test_a_period_with_no_activity_is_a_nil_return(self):
        """Silence and "nothing submitted" must not look the same."""
        empty = {
            "total_checks": 0, "auto_approved": 0, "escalated": 0, "rejected": 0,
            "top_failing_rule_ids": [],
        }
        body = text_of(render(stats=empty, gemini={"executive_summary": "No activity."}))
        assert "nil return" in body

    def test_one_document_is_not_described_as_documents(self):
        one = {
            "total_checks": 1, "auto_approved": 1, "escalated": 0, "rejected": 0,
            "top_failing_rule_ids": [],
        }
        body = text_of(render(stats=one, gemini={"executive_summary": "One."}))
        assert "1 document submitted" in body.replace("\n", " ")

    def test_hostile_summary_content_does_not_break_rendering(self):
        """Gemini output is shaped by customer-uploaded documents."""
        hostile = {"executive_summary": "</para><b>x", "top_3_risk_patterns": ["<b>unclosed"]}
        assert render(gemini=hostile).startswith(b"%PDF-")

    def test_a_very_long_business_name_still_renders(self):
        long_name = "The " + "Very " * 40 + "Long Care Services Pty Ltd"
        assert render(tenant=TenantProfile("t", long_name, "aged_care", "au")).startswith(b"%PDF-")
