"""Content-sniffing validation for uploaded documents.

The upload endpoint's declared Content-Type header is client-supplied and
untrusted. This checks the *actual* bytes match what was declared, closing
the gap where an attacker labels arbitrary content as an allowed type. Files
are never executed by this system regardless of this check (see
upload_document's docstring in main.py) — this is a content-integrity gate,
not an RCE mitigation.
"""

from __future__ import annotations

# content_type -> magic-byte prefix, for the binary types in ALLOWED_UPLOAD_TYPES.
_BINARY_SIGNATURES: dict[str, bytes] = {
    "application/pdf": b"%PDF-",
    "image/png": b"\x89PNG\r\n\x1a\n",
    "image/jpeg": b"\xff\xd8\xff",
}

# No magic bytes exist for these — validated by decodability instead.
_TEXT_TYPES = frozenset({"text/plain", "text/csv", "application/json"})


class ContentMismatchError(ValueError):
    """Raised when a file's actual bytes don't match its declared type."""


def _looks_like_text(data: bytes) -> bool:
    if b"\x00" in data:
        return False
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


def sniff_content_type(data: bytes) -> str | None:
    """Return the content type the bytes actually look like, or None if they
    don't match any known signature (binary or text-decodable)."""
    for content_type, signature in _BINARY_SIGNATURES.items():
        if data.startswith(signature):
            return content_type
    if _looks_like_text(data):
        return "text/plain"  # stand-in for "some text-like type"
    return None


def validate_upload(data: bytes, declared_content_type: str) -> None:
    """Raise ContentMismatchError if `data` doesn't match `declared_content_type`.

    Declared types this module doesn't know how to sniff pass through
    untouched — ALLOWED_UPLOAD_TYPES upstream is the only gate for those.
    """
    sniffed = sniff_content_type(data)
    if declared_content_type in _BINARY_SIGNATURES:
        if sniffed != declared_content_type:
            raise ContentMismatchError(
                f"file content does not match declared type {declared_content_type!r}"
            )
        return
    if declared_content_type in _TEXT_TYPES:
        if sniffed != "text/plain":
            raise ContentMismatchError(
                f"file content is not valid text for declared type {declared_content_type!r}"
            )
        return
