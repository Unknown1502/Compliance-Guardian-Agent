"""A rolling deploy must not 500 on records the other revision wrote.

Strict-on-write, tolerant-on-read. Rejecting unknown fields when constructing
a record catches typos and stale call sites; applying the same rule when
reading one back turns every schema addition into an outage, because during a
deploy both revisions are live and the new one writes fields the old one has
never heard of.

This project has already paid for that lesson twice: a seeder wrote one extra
field and every affected read 500'd, and the same 500 was the cross-tenant
existence oracle.
"""

from __future__ import annotations

import logging

import pytest

from schema_validators import Document, DocumentStatus, ScanStatus, Tenant, validate_stored

OLD_RECORD = {
    "document_id": "doc-1",
    "tenant_id": "tenant-a",
    "source": "upload",
    "storage_ref": "gs://bucket/tenant-a/doc-1/x.pdf",
}


class TestForwardCompatibility:
    """An old revision reading a record a new revision wrote."""

    def test_an_unknown_field_does_not_break_the_read(self):
        raw = dict(OLD_RECORD, field_from_a_newer_revision="whatever")
        doc = validate_stored(Document, raw)
        assert doc.document_id == "doc-1"

    def test_several_unknown_fields_are_tolerated(self):
        raw = dict(OLD_RECORD, alpha=1, beta=[1, 2], gamma={"nested": True})
        assert validate_stored(Document, raw).tenant_id == "tenant-a"

    def test_the_unknown_value_is_dropped_not_kept(self):
        """A stale writer must not smuggle a value past validation."""
        doc = validate_stored(Document, dict(OLD_RECORD, scan_status_v2="clean"))
        assert not hasattr(doc, "scan_status_v2")

    def test_known_fields_still_validate_strictly(self):
        """Tolerance is about *unknown* fields, not about bad values."""
        with pytest.raises(Exception):
            validate_stored(Document, dict(OLD_RECORD, size_bytes=-5))

    def test_drift_is_logged_so_it_stays_visible(self, caplog):
        with caplog.at_level(logging.WARNING, logger="cg.schema"):
            validate_stored(Document, dict(OLD_RECORD, surprise=1))
        assert "surprise" in caplog.text

    def test_a_clean_record_logs_nothing(self, caplog):
        with caplog.at_level(logging.WARNING, logger="cg.schema"):
            validate_stored(Document, OLD_RECORD)
        assert caplog.text == ""


class TestBackwardCompatibility:
    """A new revision reading a record an old revision wrote."""

    def test_missing_new_fields_fall_back_to_defaults(self):
        doc = validate_stored(Document, OLD_RECORD)
        assert doc.scan_status is ScanStatus.UNSCANNED
        assert doc.content_hash == ""

    def test_a_pre_scanning_document_is_not_treated_as_clean(self):
        """The default has to fail closed, not inherit trust."""
        assert validate_stored(Document, OLD_RECORD).scan_status is not ScanStatus.CLEAN

    def test_status_defaults_are_preserved(self):
        assert validate_stored(Document, OLD_RECORD).status is DocumentStatus.PENDING


class TestWritesStayStrict:
    """The safety that catches typos must not have been traded away."""

    def test_constructing_a_model_still_rejects_unknown_fields(self):
        with pytest.raises(Exception):
            Document(**dict(OLD_RECORD, typoed_field=True))

    def test_the_demo_seeded_regression_would_still_be_caught_on_write(self):
        """The field that caused the original outage — rejected at the point
        it would be written, tolerated at the point it is read."""
        with pytest.raises(Exception):
            Document(**dict(OLD_RECORD, demo_seeded=True))
        assert validate_stored(Document, dict(OLD_RECORD, demo_seeded=True)).document_id == "doc-1"


class TestAppliesAcrossModels:
    @pytest.mark.parametrize(
        "model,raw",
        [
            (Document, OLD_RECORD),
            (Tenant, {"tenant_id": "t", "name": "N", "industry": "healthcare_ndis",
                      "jurisdiction": "AU", "plan_tier": "starter"}),
        ],
        ids=["Document", "Tenant"],
    )
    def test_unknown_fields_tolerated(self, model, raw):
        assert validate_stored(model, dict(raw, some_future_field="x")) is not None
