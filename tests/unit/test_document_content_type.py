"""Working out what a stored document actually is.

Reported from production: opening a document on the review screen showed
"This is a application/octet-stream file, which can't be shown inline" for a
file that was plain text all along.

19 of 27 production records predate the content_type field. Those returned no
type, the endpoint defaulted to application/octet-stream, and the dashboard —
correctly, given what it was told — offered an opaque download instead of
showing the text. The reviewer could not read the document they were being
asked to make a compliance decision about.

The bytes are already fetched to compute the integrity hash, so sniffing them
costs nothing and needs no data migration.

The security property to preserve: a filename can never promote content to a
binary type. Extensions only ever refine text into a narrower *text* type,
and only after the bytes have been confirmed text-decodable.
"""

from __future__ import annotations

import pytest

from api_gateway.main import _resolve_content_type

PDF = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 8
TEXT = b"Resident: Ilse Novak\nService date: 2026-06-18\n"


class Doc:
    """Stand-in for a Firestore document record."""

    def __init__(self, content_type=None):
        if content_type is not None:
            self.content_type = content_type


class Legacy:
    """A record written before the field existed — the attribute is absent."""


class TestTheStoredTypeWins:
    def test_a_declared_type_is_used_as_is(self):
        """It was validated against the bytes at upload; don't second-guess."""
        assert _resolve_content_type(Doc("application/pdf"), PDF, "a.pdf") == "application/pdf"

    def test_a_declared_type_is_trusted_over_the_extension(self):
        assert _resolve_content_type(Doc("text/csv"), TEXT, "a.txt") == "text/csv"


class TestLegacyRecordsAreRecovered:
    """The actual bug: these all used to come back as octet-stream."""

    @pytest.mark.parametrize("doc", [Legacy(), Doc(""), Doc(None)])
    def test_text_is_recognised_however_the_field_is_missing(self, doc):
        assert _resolve_content_type(doc, TEXT, "ndis_agreement.txt") == "text/plain"

    def test_a_pdf_is_recognised_by_its_magic_bytes(self):
        assert _resolve_content_type(Legacy(), PDF, "policy.pdf") == "application/pdf"

    def test_a_png_is_recognised_by_its_magic_bytes(self):
        assert _resolve_content_type(Legacy(), PNG, "scan.png") == "image/png"

    def test_csv_is_refined_from_text_by_extension(self):
        assert _resolve_content_type(Legacy(), TEXT, "roster.csv") == "text/csv"

    def test_json_is_refined_from_text_by_extension(self):
        assert _resolve_content_type(Legacy(), b'{"a": 1}', "payload.json") == "application/json"

    def test_text_with_no_extension_still_displays(self):
        assert _resolve_content_type(Legacy(), TEXT, "README") == "text/plain"

    def test_genuinely_binary_content_stays_a_download(self):
        """The fallback must remain for content we cannot identify."""
        assert _resolve_content_type(Legacy(), b"\x00\x01\x02\xff\xfe", "x.bin") == (
            "application/octet-stream"
        )


class TestAnExtensionCannotPromoteContent:
    """A filename is attacker-influenced; the bytes are not."""

    def test_text_named_pdf_is_not_served_as_pdf(self):
        assert _resolve_content_type(Legacy(), TEXT, "not_really.pdf") == "text/plain"

    def test_binary_named_csv_is_not_served_as_text(self):
        assert _resolve_content_type(Legacy(), b"\x00\xff\x00\xff", "evil.csv") == (
            "application/octet-stream"
        )

    def test_a_pdf_named_csv_follows_its_magic_bytes(self):
        assert _resolve_content_type(Legacy(), PDF, "disguised.csv") == "application/pdf"
