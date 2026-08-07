"""Unit tests: upload content-sniffing validation (hermetic)."""

from __future__ import annotations

import pytest

from api_gateway.upload_validation import (
    ContentMismatchError,
    sniff_content_type,
    validate_upload,
)

PDF_BYTES = b"%PDF-1.4\n" + b"\x00" * 10
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 10
JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"\x00" * 10
TEXT_BYTES = b"hello, this is plain text content"
JSON_BYTES = b'{"key": "value"}'
EXE_BYTES = b"MZ\x90\x00\x03\x00\x00\x00\x04\x00\x00\x00"


class TestSniffContentType:
    def test_pdf_signature(self):
        assert sniff_content_type(PDF_BYTES) == "application/pdf"

    def test_png_signature(self):
        assert sniff_content_type(PNG_BYTES) == "image/png"

    def test_jpeg_signature(self):
        assert sniff_content_type(JPEG_BYTES) == "image/jpeg"

    def test_plain_text(self):
        assert sniff_content_type(TEXT_BYTES) == "text/plain"

    def test_unknown_binary_returns_none(self):
        assert sniff_content_type(b"\x01\x02\x03garbage\xff\xfe") is None

    def test_exe_header_is_not_sniffed_as_text(self):
        assert sniff_content_type(EXE_BYTES) is None


class TestValidateUpload:
    def test_matching_pdf_passes(self):
        validate_upload(PDF_BYTES, "application/pdf")  # no raise

    def test_matching_text_passes(self):
        validate_upload(TEXT_BYTES, "text/plain")

    def test_matching_json_passes(self):
        validate_upload(JSON_BYTES, "application/json")

    def test_exe_labelled_as_pdf_rejected(self):
        with pytest.raises(ContentMismatchError):
            validate_upload(EXE_BYTES, "application/pdf")

    def test_binary_labelled_as_csv_rejected(self):
        with pytest.raises(ContentMismatchError):
            validate_upload(PNG_BYTES, "text/csv")

    def test_png_labelled_as_jpeg_rejected(self):
        with pytest.raises(ContentMismatchError):
            validate_upload(PNG_BYTES, "image/jpeg")

    def test_unknown_declared_type_is_not_validated_here(self):
        # Gated by ALLOWED_UPLOAD_TYPES upstream, not this module — must not raise.
        validate_upload(b"whatever", "application/octet-stream")
