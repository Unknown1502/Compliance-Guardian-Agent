# Upload Safety, PDF Reports & Analytics Trends Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the three real gaps found in the 2026-08-07 audit: uploads trust a client-supplied Content-Type with no byte-level verification, compliance reports are HTML-only despite the PRD/README promising PDF, and there is no cross-tenant view of risk trends over time.

**Architecture:** Three independent slices on the existing FastAPI/Firestore/GCS stack — no new services, no new GCP resources except one new system-dependency layer in the reporting-agent's Dockerfile. Upload validation is a local api-gateway module (single consumer). Analytics aggregation moves into `shared/` because both reporting-agent and api-gateway need the same numbers. PDF rendering wraps the reporting-agent's existing HTML template rather than replacing it.

**Tech Stack:** FastAPI + Pydantic v2 (gateway), google-cloud-firestore/storage/bigquery, pytest with hand-written hermetic fakes (no emulators, no network — matches every existing test file in `tests/unit/`), React 18 + TypeScript + Vite + Tailwind + Framer Motion + lucide-react (dashboard, no new frontend dependency), WeasyPrint (new — PDF rendering).

## Global Constraints

- Files are never executed as code anywhere in this system (verified: bytes are only hashed, stored, or passed to Gemini as inert data) — upload validation is a content-integrity gate, not an RCE mitigation, and must not be framed as one.
- `MAX_UPLOAD_BYTES` stays at its existing default (10 MiB via env var) — not being changed, only enforced earlier (bounded read).
- Analytics aggregation must stay Firestore-only — no new BigQuery query-job billing surface (explicit cost-consciousness precedent already set in `reporter.py`'s design notes).
- No new frontend npm dependency for charting — `apps/dashboard/package.json` has zero chart library today; the existing `DecisionBreakdown.tsx` component already hand-rolls an SVG bar with a fixed status palette (`#0ca30c`/`#fab219`/`#d03b3b` for approved/escalated/rejected) — the new trend chart follows that exact precedent and palette.
- The reporting-agent Dockerfile change (system libs for WeasyPrint) is a real change to a live, billed Cloud Run service (`cg-guardian-9856`) — do not `terraform apply` / redeploy without the user's explicit go-ahead; this plan only prepares the code and image definition.
- `shared/pyproject.toml`'s `[tool.setuptools.packages.find] include` list must be updated for any new top-level `shared/` package, or it silently won't ship in the built container image — this exact bug already happened once with `task_dispatch` (see `docs/superpowers/specs/2026-08-07-upload-safety-pdf-reports-analytics-design.md`). Task 3 below adds `analytics*` to that list — do not skip it.
- All hermetic unit tests must keep passing with **no** emulators, **no** network, and **no** requirement that WeasyPrint's system libraries (Cairo/Pango) be installed on the dev machine — the PDF task is designed so tests monkeypatch the rendering seam directly (see Task 7).

---

## File Structure

```
apps/api-gateway/api_gateway/
  upload_validation.py          [NEW]  magic-byte / content sniffing
  main.py                       [MODIFY]  upload endpoint wiring, /api/reports/{id}, new /api/analytics/trends

shared/
  analytics/__init__.py         [NEW]  aggregate_period, weekly_trend, all_time_top_violations
  pyproject.toml                [MODIFY]  add "analytics*" to packages.find include

services/reporting-agent/
  reporting_agent/reporter.py   [MODIFY]  use shared analytics; add PDF rendering
  requirements.txt              [MODIFY]  add weasyprint
  Dockerfile                    [MODIFY]  add system libs for weasyprint

apps/dashboard/src/
  api/client.ts                 [MODIFY]  getTrends() + types
  views/AnalyticsView.tsx       [NEW]  trend chart + top-violations list
  views/ReportsView.tsx         [MODIFY]  PDF-aware download
  App.tsx                       [MODIFY]  /trends route
  components/Layout.tsx         [MODIFY]  nav entry

tests/unit/
  test_upload_validation.py     [NEW]
  test_upload_endpoint.py       [NEW]
  test_analytics.py             [NEW]
  test_analytics_endpoint.py    [NEW]
  test_reports_endpoint.py      [NEW]
  test_reporting_agent.py       [MODIFY]  add PDF-path tests
```

---

### Task 1: Upload content-sniffing validator

**Files:**
- Create: `apps/api-gateway/api_gateway/upload_validation.py`
- Test: `tests/unit/test_upload_validation.py`

**Interfaces:**
- Produces: `ContentMismatchError(ValueError)`, `sniff_content_type(data: bytes) -> str | None`, `validate_upload(data: bytes, declared_content_type: str) -> None` (raises `ContentMismatchError` on mismatch, returns `None` on match or on a declared type it doesn't know how to sniff).

Note on scope: this only distinguishes binary-vs-declared-type mismatches (e.g. an executable labelled `application/pdf`). It does not detect HTML/script content mislabelled as `text/plain` — that's an accepted limitation because the one place file content reaches a browser (`GET /api/documents/:id/content`) already returns it inside a JSON field that React renders as text, never as raw HTML, so there is no rendering vector for that case today.

- [ ] **Step 1: Write the failing tests**

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd compliance-agent && python -m pytest tests/unit/test_upload_validation.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'api_gateway.upload_validation'`

- [ ] **Step 3: Write the implementation**

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd compliance-agent && python -m pytest tests/unit/test_upload_validation.py -v`
Expected: PASS (13 tests)

- [ ] **Step 5: Commit**

```bash
git add apps/api-gateway/api_gateway/upload_validation.py tests/unit/test_upload_validation.py
git commit -m "Add magic-byte content validation for uploads"
```

---

### Task 2: Wire the validator into the upload endpoint

**Files:**
- Modify: `apps/api-gateway/api_gateway/main.py:394-463` (the `upload_document` handler), and its import block around line 38.
- Test: `tests/unit/test_upload_endpoint.py`

**Interfaces:**
- Consumes: `ContentMismatchError`, `validate_upload` from Task 1's `api_gateway.upload_validation`.
- Consumes: `MAX_UPLOAD_BYTES`, `ALLOWED_UPLOAD_TYPES` (module-level in `main.py`, unchanged).

- [ ] **Step 1: Write the failing tests**

```python
"""Unit tests: POST /api/documents — content validation + bounded read (hermetic)."""

from __future__ import annotations

import base64
import io
import json

import pytest
from fastapi.testclient import TestClient


def _dev_token(uid: str, tenant_id: str, role: str) -> str:
    claims = {"uid": uid, "tenant_id": tenant_id, "role": role}
    raw = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return f"dev:{raw}"


class FakeBlob:
    def __init__(self):
        self.content = b""
        self.content_type = None

    def upload_from_string(self, data, content_type=None):
        self.content = data
        self.content_type = content_type


class FakeBucket:
    def __init__(self):
        self.blobs: dict[str, FakeBlob] = {}

    def blob(self, path):
        if path not in self.blobs:
            self.blobs[path] = FakeBlob()
        return self.blobs[path]


class FakeStorage:
    def __init__(self):
        self.buckets: dict[str, FakeBucket] = {}

    def bucket(self, name):
        if name not in self.buckets:
            self.buckets[name] = FakeBucket()
        return self.buckets[name]


class FakeRepo:
    def __init__(self):
        self.documents = {}

    def upsert_document(self, document):
        self.documents[document.document_id] = document


class FakeAuditor:
    def __init__(self):
        self.events = []

    def log(self, **kwargs):
        self.events.append(kwargs)
        return kwargs


class FakeGateway:
    def __init__(self):
        self.repo = FakeRepo()
        self.auditor = FakeAuditor()
        self.storage = FakeStorage()
        self.raw_bucket = "test-raw-bucket"


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("CG_AUTH_DEV_MODE", "1")
    import api_gateway.main as main
    import auth_middleware
    from api_gateway.rate_limit import TokenBucketRateLimiter

    monkeypatch.setattr(auth_middleware, "_ensure_firebase_app", lambda: None)
    fake = FakeGateway()
    monkeypatch.setattr(main, "_gateway", fake)
    monkeypatch.setattr(main, "gw", lambda: fake)
    # Fresh rate-limit bucket per test — the real one is module-level state.
    monkeypatch.setattr(
        main, "_upload_limiter", TokenBucketRateLimiter(capacity=20, refill_per_second=0.5)
    )
    return TestClient(main.app), fake


AUTH_HEADER = {"Authorization": f"Bearer {_dev_token('u1', 'tenant-a', 'owner')}"}


class TestUploadValidation:
    def test_valid_pdf_accepted(self, client):
        c, fake = client
        pdf_bytes = b"%PDF-1.4\n" + b"x" * 100
        r = c.post(
            "/api/documents",
            headers=AUTH_HEADER,
            files={"file": ("doc.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
        )
        assert r.status_code == 200
        assert len(fake.repo.documents) == 1

    def test_valid_text_file_accepted(self, client):
        c, fake = client
        r = c.post(
            "/api/documents",
            headers=AUTH_HEADER,
            files={"file": ("doc.txt", io.BytesIO(b"plain text content"), "text/plain")},
        )
        assert r.status_code == 200
        assert len(fake.repo.documents) == 1

    def test_exe_disguised_as_pdf_rejected(self, client):
        c, fake = client
        exe_bytes = b"MZ\x90\x00\x03\x00\x00\x00\x04\x00\x00\x00" + b"x" * 100
        r = c.post(
            "/api/documents",
            headers=AUTH_HEADER,
            files={"file": ("doc.pdf", io.BytesIO(exe_bytes), "application/pdf")},
        )
        assert r.status_code == 415
        assert len(fake.repo.documents) == 0
        assert any(e["action"] == "document.upload_rejected" for e in fake.auditor.events)

    def test_oversized_upload_rejected(self, client, monkeypatch):
        c, _ = client
        import api_gateway.main as main

        monkeypatch.setattr(main, "MAX_UPLOAD_BYTES", 1024)
        big = b"%PDF-1.4\n" + b"x" * 2048
        r = c.post(
            "/api/documents",
            headers=AUTH_HEADER,
            files={"file": ("big.pdf", io.BytesIO(big), "application/pdf")},
        )
        assert r.status_code == 413
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd compliance-agent && python -m pytest tests/unit/test_upload_endpoint.py -v`
Expected: FAIL — `test_exe_disguised_as_pdf_rejected` gets 200 instead of 415 (validator not wired yet); others may already pass coincidentally, confirm at least that one fails.

- [ ] **Step 3: Write the implementation**

In `apps/api-gateway/api_gateway/main.py`, add to the import block (near line 38, alongside the other `api_gateway.*` imports):

```python
from api_gateway.upload_validation import ContentMismatchError, validate_upload
```

Replace the body of `upload_document` from the rate-limit check through the `len(data) > MAX_UPLOAD_BYTES` check (currently lines ~400-418) with:

```python
    # Rate-limit uploads per tenant.
    if not _upload_limiter.allow(auth.tenant_id):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="upload rate limit exceeded; try again shortly",
        )
    if file.content_type not in ALLOWED_UPLOAD_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"unsupported content type: {file.content_type}",
        )

    # Bounded read: stop as soon as the limit is exceeded instead of
    # buffering an unbounded body into memory first.
    buf = bytearray()
    while True:
        chunk = await file.read(64 * 1024)
        if not chunk:
            break
        buf.extend(chunk)
        if len(buf) > MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"file exceeds {MAX_UPLOAD_BYTES} bytes",
            )
    data = bytes(buf)
    if len(data) == 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="empty file")

    g = gw()
    try:
        validate_upload(data, file.content_type)
    except ContentMismatchError:
        g.auditor.log(
            tenant_id=auth.tenant_id,
            actor=auth.uid,
            action="document.upload_rejected",
            dedup_key=f"{auth.tenant_id}:{datetime.now(timezone.utc).isoformat()}",
            before_state=None,
            after_state={
                "declared_content_type": file.content_type,
                "size_bytes": len(data),
                "reason": "content_type_mismatch",
            },
        )
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="file content does not match its declared type",
        )
```

Then delete the now-duplicate `g = gw()` line that used to follow (the original line directly after the old size check) — `g` is already bound above.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd compliance-agent && python -m pytest tests/unit/test_upload_endpoint.py tests/unit/test_api_gateway.py -v`
Expected: PASS (all tests in both files — the second file guards against regressions in the rest of the gateway's document routes)

- [ ] **Step 5: Commit**

```bash
git add apps/api-gateway/api_gateway/main.py tests/unit/test_upload_endpoint.py
git commit -m "Enforce content validation and bounded reads on document upload"
```

---

### Task 3: Extract shared analytics aggregation

**Files:**
- Create: `shared/analytics/__init__.py`
- Modify: `shared/pyproject.toml:23`
- Modify: `services/reporting-agent/reporting_agent/reporter.py:63-103, 220` (remove `_aggregate_checks`, use the shared version)
- Test: `tests/unit/test_analytics.py`

**Interfaces:**
- Produces: `aggregate_period(db, *, tenant_id: str, period_start: datetime, period_end: datetime) -> dict` with keys `total_checks, auto_approved, escalated, rejected, top_failing_rule_ids, citation_frequency, period_start, period_end` — identical shape to today's private `_aggregate_checks`, so `reporter.py`'s consumers (`_render_html`, `generate_report`) need no changes beyond the call site.

- [ ] **Step 1: Write the failing tests**

```python
"""Unit tests: shared analytics aggregation (hermetic)."""

from __future__ import annotations

from datetime import datetime, timezone

from analytics import aggregate_period


class _Snap:
    def __init__(self, data):
        self._data = data

    def to_dict(self):
        return self._data


class FakeFirestore:
    def __init__(self, checks: list[dict]):
        self._checks = checks

    def collection(self, name):
        return self

    def where(self, *args, **kwargs):
        return self

    def stream(self):
        return iter(_Snap(c) for c in self._checks)


def _check(decision: str, citations: list[str]) -> dict:
    return {
        "tenant_id": "tenant-a",
        "decision": decision,
        "citations": citations,
        "created_at": datetime(2026, 6, 15, tzinfo=timezone.utc).isoformat(),
    }


class TestAggregatePeriod:
    def test_empty_period(self):
        stats = aggregate_period(
            FakeFirestore([]),
            tenant_id="tenant-a",
            period_start=datetime(2026, 6, 1, tzinfo=timezone.utc),
            period_end=datetime(2026, 7, 1, tzinfo=timezone.utc),
        )
        assert stats["total_checks"] == 0
        assert stats["top_failing_rule_ids"] == []

    def test_counts_by_decision(self):
        checks = [
            _check("auto_approved", []),
            _check("auto_approved", []),
            _check("escalated", ["consent_documentation"]),
            _check("rejected", ["consent_documentation"]),
        ]
        stats = aggregate_period(
            FakeFirestore(checks),
            tenant_id="tenant-a",
            period_start=datetime(2026, 6, 1, tzinfo=timezone.utc),
            period_end=datetime(2026, 7, 1, tzinfo=timezone.utc),
        )
        assert stats["total_checks"] == 4
        assert stats["auto_approved"] == 2
        assert stats["escalated"] == 1
        assert stats["rejected"] == 1

    def test_top_failing_rules_ranked_by_frequency(self):
        checks = [
            _check("escalated", ["rule_a"]),
            _check("escalated", ["rule_a"]),
            _check("escalated", ["rule_b"]),
        ]
        stats = aggregate_period(
            FakeFirestore(checks),
            tenant_id="tenant-a",
            period_start=datetime(2026, 6, 1, tzinfo=timezone.utc),
            period_end=datetime(2026, 7, 1, tzinfo=timezone.utc),
        )
        assert stats["top_failing_rule_ids"][0] == "rule_a"
        assert stats["citation_frequency"]["rule_a"] == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd compliance-agent && python -m pytest tests/unit/test_analytics.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'analytics'`

- [ ] **Step 3: Write the implementation**

Create `shared/analytics/__init__.py`:

```python
"""Cross-service compliance-check aggregation.

Used by both the Reporting Agent (single-period report stats) and the API
Gateway (multi-week trend analytics) so the two never compute "top failing
rules" or decision-mix counts differently. Firestore-only, matching the
reporting-agent's existing cost-conscious choice to avoid a BigQuery query
job for aggregation a Firestore range query already answers.
"""

from __future__ import annotations

from datetime import datetime

from google.cloud import firestore

COLLECTION_CHECKS = "compliance_checks"


def _count_citations(checks: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for data in checks:
        for cit in data.get("citations", []) or []:
            counts[cit] = counts.get(cit, 0) + 1
    return counts


def aggregate_period(
    db: firestore.Client, *, tenant_id: str, period_start: datetime, period_end: datetime
) -> dict:
    """Aggregate compliance_checks for one tenant over [period_start, period_end)."""
    checks = (
        db.collection(COLLECTION_CHECKS)
        .where("tenant_id", "==", tenant_id)
        .where("created_at", ">=", period_start.isoformat())
        .where("created_at", "<", period_end.isoformat())
        .stream()
    )
    total = 0
    auto_approved = 0
    escalated = 0
    rejected = 0
    all_data: list[dict] = []

    for snap in checks:
        data = snap.to_dict()
        all_data.append(data)
        total += 1
        decision = data.get("decision", "")
        if decision == "auto_approved":
            auto_approved += 1
        elif decision == "escalated":
            escalated += 1
        elif decision == "rejected":
            rejected += 1

    citation_counts = _count_citations(all_data)
    top_3 = sorted(citation_counts, key=lambda k: citation_counts[k], reverse=True)[:3]
    return {
        "total_checks": total,
        "auto_approved": auto_approved,
        "escalated": escalated,
        "rejected": rejected,
        "top_failing_rule_ids": top_3,
        "citation_frequency": {k: citation_counts[k] for k in top_3},
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
    }
```

In `shared/pyproject.toml`, change line 23 from:

```toml
include = ["auth_middleware*", "audit_logger*", "schema_validators*", "gcp_clients*", "gemini_client*", "task_dispatch*", "billing*", "notifications*", "api_keys*", "retention*"]
```

to:

```toml
include = ["auth_middleware*", "audit_logger*", "schema_validators*", "gcp_clients*", "gemini_client*", "task_dispatch*", "billing*", "notifications*", "api_keys*", "retention*", "analytics*"]
```

In `services/reporting-agent/reporting_agent/reporter.py`: delete the `_aggregate_checks` function (lines 63-103) entirely, add `from analytics import aggregate_period` to the imports near the top, and in `generate_report()` change:

```python
    stats = _aggregate_checks(db, tenant_id=tenant_id, period_start=period_start, period_end=period_end)
```

to:

```python
    stats = aggregate_period(db, tenant_id=tenant_id, period_start=period_start, period_end=period_end)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd compliance-agent && python -m pytest tests/unit/test_analytics.py tests/unit/test_reporting_agent.py -v`
Expected: PASS — `test_analytics.py` is new coverage; `test_reporting_agent.py` must still pass unchanged, proving the refactor didn't alter reporter.py's behavior.

- [ ] **Step 5: Commit**

```bash
git add shared/analytics/__init__.py shared/pyproject.toml services/reporting-agent/reporting_agent/reporter.py tests/unit/test_analytics.py
git commit -m "Extract compliance-check aggregation into shared/analytics"
```

---

### Task 4: Add weekly trend + all-time top-violations queries

**Files:**
- Modify: `shared/analytics/__init__.py` (append)
- Test: `tests/unit/test_analytics.py` (append)

**Interfaces:**
- Consumes: `aggregate_period`, `_count_citations`, `COLLECTION_CHECKS` from Task 3.
- Produces: `weekly_trend(db, *, tenant_id: str, weeks: int = 12, now: datetime | None = None) -> list[dict]` — each dict is an `aggregate_period` result plus `week_start`/`week_end` ISO strings, oldest week first. `all_time_top_violations(db, *, tenant_id: str, limit: int = 10) -> list[dict]` — each dict is `{"rule_id": str, "count": int}`, ranked descending.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_analytics.py` (add `all_time_top_violations, weekly_trend` to the existing `from analytics import ...` line):

```python
from analytics import aggregate_period, all_time_top_violations, weekly_trend


class TestWeeklyTrend:
    def test_returns_requested_number_of_weeks(self):
        buckets = weekly_trend(
            FakeFirestore([]),
            tenant_id="tenant-a",
            weeks=4,
            now=datetime(2026, 8, 7, tzinfo=timezone.utc),
        )
        assert len(buckets) == 4

    def test_buckets_ordered_oldest_first(self):
        buckets = weekly_trend(
            FakeFirestore([]),
            tenant_id="tenant-a",
            weeks=3,
            now=datetime(2026, 8, 7, tzinfo=timezone.utc),
        )
        starts = [b["week_start"] for b in buckets]
        assert starts == sorted(starts)

    def test_empty_tenant_returns_all_zero_buckets(self):
        buckets = weekly_trend(
            FakeFirestore([]),
            tenant_id="tenant-a",
            weeks=2,
            now=datetime(2026, 8, 7, tzinfo=timezone.utc),
        )
        assert all(b["total_checks"] == 0 for b in buckets)


class TestAllTimeTopViolations:
    def test_ranks_by_frequency_and_respects_limit(self):
        checks = [
            _check("escalated", ["rule_a"]),
            _check("escalated", ["rule_a"]),
            _check("escalated", ["rule_b"]),
            _check("escalated", ["rule_c"]),
        ]
        top = all_time_top_violations(FakeFirestore(checks), tenant_id="tenant-a", limit=2)
        assert len(top) == 2
        assert top[0] == {"rule_id": "rule_a", "count": 2}

    def test_empty_tenant_returns_empty_list(self):
        assert all_time_top_violations(FakeFirestore([]), tenant_id="tenant-a") == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd compliance-agent && python -m pytest tests/unit/test_analytics.py -v`
Expected: FAIL with `ImportError: cannot import name 'weekly_trend'`

- [ ] **Step 3: Write the implementation**

Append to `shared/analytics/__init__.py` (add `timedelta` to the existing `from datetime import datetime` line, making it `from datetime import datetime, timedelta, timezone`):

```python
def weekly_trend(
    db: firestore.Client, *, tenant_id: str, weeks: int = 12, now: datetime | None = None
) -> list[dict]:
    """One bucket per 7-day window for the last `weeks` weeks, oldest first."""
    reference = now or datetime.now(timezone.utc)
    buckets = []
    for i in range(weeks):
        period_end = reference - timedelta(days=7 * i)
        period_start = period_end - timedelta(days=7)
        stats = aggregate_period(
            db, tenant_id=tenant_id, period_start=period_start, period_end=period_end
        )
        buckets.append(
            {**stats, "week_start": period_start.isoformat(), "week_end": period_end.isoformat()}
        )
    return list(reversed(buckets))


def all_time_top_violations(
    db: firestore.Client, *, tenant_id: str, limit: int = 10
) -> list[dict]:
    """Rank rule citations across every check the tenant has ever had."""
    checks = db.collection(COLLECTION_CHECKS).where("tenant_id", "==", tenant_id).stream()
    counts = _count_citations([snap.to_dict() for snap in checks])
    ranked = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:limit]
    return [{"rule_id": rule_id, "count": count} for rule_id, count in ranked]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd compliance-agent && python -m pytest tests/unit/test_analytics.py -v`
Expected: PASS (all tests in the file)

- [ ] **Step 5: Commit**

```bash
git add shared/analytics/__init__.py tests/unit/test_analytics.py
git commit -m "Add weekly trend and all-time top-violations analytics queries"
```

---

### Task 5: `GET /api/analytics/trends` endpoint

**Files:**
- Modify: `apps/api-gateway/api_gateway/main.py` — add response models near the other `*Response` models (around line 230, after `ReportResponse`), and a new route section after `get_report` (after line 865, before the Billing section comment).
- Test: `tests/unit/test_analytics_endpoint.py`

**Interfaces:**
- Consumes: `weekly_trend`, `all_time_top_violations` from Task 4's `shared.analytics` (imported as `from analytics import ...`, same pattern reporter.py uses).
- Produces: `GET /api/analytics/trends?weeks=<1-52, default 12>` → `TrendsResponse { tenant_id, weeks: TrendWeekResponse[], top_violations: TopViolation[] }`.

- [ ] **Step 1: Write the failing tests**

```python
"""Unit tests: GET /api/analytics/trends (hermetic)."""

from __future__ import annotations

import base64
import json

import pytest
from fastapi.testclient import TestClient


def _dev_token(uid: str, tenant_id: str, role: str) -> str:
    claims = {"uid": uid, "tenant_id": tenant_id, "role": role}
    raw = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return f"dev:{raw}"


class _Snap:
    def __init__(self, data):
        self._data = data

    def to_dict(self):
        return self._data


class FakeFirestore:
    def __init__(self, checks):
        self._checks = checks

    def collection(self, name):
        return self

    def where(self, *args, **kwargs):
        return self

    def stream(self):
        return iter(_Snap(c) for c in self._checks)


class FakeGateway:
    def __init__(self, checks=None):
        self.db = FakeFirestore(checks or [])


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("CG_AUTH_DEV_MODE", "1")
    import api_gateway.main as main
    import auth_middleware

    monkeypatch.setattr(auth_middleware, "_ensure_firebase_app", lambda: None)
    fake = FakeGateway()
    monkeypatch.setattr(main, "_gateway", fake)
    monkeypatch.setattr(main, "gw", lambda: fake)
    return TestClient(main.app), fake


AUTH_HEADER = {"Authorization": f"Bearer {_dev_token('u1', 'tenant-a', 'owner')}"}


class TestTrendsEndpoint:
    def test_requires_auth(self, client):
        c, _ = client
        assert c.get("/api/analytics/trends").status_code == 401

    def test_default_returns_12_weeks(self, client):
        c, _ = client
        r = c.get("/api/analytics/trends", headers=AUTH_HEADER)
        assert r.status_code == 200
        body = r.json()
        assert len(body["weeks"]) == 12
        assert body["tenant_id"] == "tenant-a"

    def test_weeks_param_respected(self, client):
        c, _ = client
        r = c.get("/api/analytics/trends?weeks=4", headers=AUTH_HEADER)
        assert len(r.json()["weeks"]) == 4

    def test_out_of_range_weeks_rejected(self, client):
        c, _ = client
        r = c.get("/api/analytics/trends?weeks=999", headers=AUTH_HEADER)
        assert r.status_code == 400

    def test_empty_tenant_all_zero(self, client):
        c, _ = client
        r = c.get("/api/analytics/trends", headers=AUTH_HEADER)
        body = r.json()
        assert all(w["total_checks"] == 0 for w in body["weeks"])
        assert body["top_violations"] == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd compliance-agent && python -m pytest tests/unit/test_analytics_endpoint.py -v`
Expected: FAIL with 404 (route doesn't exist yet)

- [ ] **Step 3: Write the implementation**

In `apps/api-gateway/api_gateway/main.py`, add after the `ReportResponse` model (after line 229):

```python
class TrendWeekResponse(BaseModel):
    week_start: str
    week_end: str
    total_checks: int
    auto_approved: int
    escalated: int
    rejected: int
    top_failing_rule_ids: list[str]


class TopViolation(BaseModel):
    rule_id: str
    count: int


class TrendsResponse(BaseModel):
    tenant_id: str
    weeks: list[TrendWeekResponse]
    top_violations: list[TopViolation]
```

Add a new section after `get_report` (after line 865, before the `# Billing` comment block):

```python
# ---------------------------------------------------------------------------
# Analytics — cross-tenant trend view over shared/analytics aggregation
# ---------------------------------------------------------------------------


@app.get("/api/analytics/trends", response_model=TrendsResponse)
def get_trends(
    weeks: int = 12, auth: AuthContext = Depends(require_auth)
) -> TrendsResponse:
    from analytics import all_time_top_violations, weekly_trend

    if not (1 <= weeks <= 52):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="weeks must be between 1 and 52",
        )
    g = gw()
    buckets = weekly_trend(g.db, tenant_id=auth.tenant_id, weeks=weeks)
    top = all_time_top_violations(g.db, tenant_id=auth.tenant_id, limit=10)
    return TrendsResponse(
        tenant_id=auth.tenant_id,
        weeks=[
            TrendWeekResponse(
                week_start=b["week_start"],
                week_end=b["week_end"],
                total_checks=b["total_checks"],
                auto_approved=b["auto_approved"],
                escalated=b["escalated"],
                rejected=b["rejected"],
                top_failing_rule_ids=b["top_failing_rule_ids"],
            )
            for b in buckets
        ],
        top_violations=[TopViolation(rule_id=v["rule_id"], count=v["count"]) for v in top],
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd compliance-agent && python -m pytest tests/unit/test_analytics_endpoint.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add apps/api-gateway/api_gateway/main.py tests/unit/test_analytics_endpoint.py
git commit -m "Add GET /api/analytics/trends endpoint"
```

---

### Task 6: Dashboard Trends view

**Files:**
- Modify: `apps/dashboard/src/api/client.ts` (append)
- Create: `apps/dashboard/src/views/AnalyticsView.tsx`
- Modify: `apps/dashboard/src/App.tsx` (add route)
- Modify: `apps/dashboard/src/components/Layout.tsx` (add nav entry)

**Interfaces:**
- Consumes: `GET /api/analytics/trends` from Task 5, response shape `{ tenant_id, weeks: {week_start, week_end, total_checks, auto_approved, escalated, rejected, top_failing_rule_ids}[], top_violations: {rule_id, count}[] }`.

This repo has no frontend test runner (`package.json`'s `"lint"` script is `tsc --noEmit`, no `test` script exists) — verification for this task is `tsc --noEmit` passing plus a manual check in the running dashboard, consistent with how the rest of this codebase is verified.

- [ ] **Step 1: Add the API client function**

Append to `apps/dashboard/src/api/client.ts`:

```typescript
// -- analytics ---------------------------------------------------------------

export interface TrendWeek {
  week_start: string;
  week_end: string;
  total_checks: number;
  auto_approved: number;
  escalated: number;
  rejected: number;
  top_failing_rule_ids: string[];
}

export interface TopViolation {
  rule_id: string;
  count: number;
}

export interface Trends {
  tenant_id: string;
  weeks: TrendWeek[];
  top_violations: TopViolation[];
}

export async function getTrends(session: Session, weeks = 12): Promise<Trends> {
  return jsonOrThrow(await authedFetch(session, `/api/analytics/trends?weeks=${weeks}`));
}
```

- [ ] **Step 2: Create the view**

Create `apps/dashboard/src/views/AnalyticsView.tsx`:

```tsx
import { useEffect, useState } from "react";
import { TrendingUp, AlertTriangle } from "lucide-react";
import { useAuth } from "../auth/AuthContext";
import { useToast } from "../context/ToastContext";
import { getTrends, type Trends } from "../api/client";
import { Card, CardHeader, PageHeading } from "../components/ui/Card";

// Same status palette as DecisionBreakdown.tsx — identity never rides on
// color alone elsewhere in this app, and this chart follows that precedent.
const COLORS = {
  approved: "#0ca30c",
  escalated: "#fab219",
  rejected: "#d03b3b",
};

function TrendChart({ weeks }: { weeks: Trends["weeks"] }) {
  const width = 720;
  const height = 220;
  const padding = 32;
  const barGap = 6;
  const maxTotal = Math.max(1, ...weeks.map((w) => w.total_checks));
  const barWidth = (width - padding * 2) / weeks.length - barGap;
  const scaleY = (n: number) => (n / maxTotal) * (height - padding * 2);

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      role="img"
      aria-label="Weekly compliance check volume, split by decision"
      className="w-full"
    >
      {weeks.map((w, i) => {
        const x = padding + i * (barWidth + barGap);
        const segments = [
          { key: "Approved", value: w.auto_approved, color: COLORS.approved },
          { key: "Escalated", value: w.escalated, color: COLORS.escalated },
          { key: "Rejected", value: w.rejected, color: COLORS.rejected },
        ];
        let yCursor = height - padding;

        return (
          <g key={w.week_start}>
            {segments.map((seg) => {
              const h = scaleY(seg.value);
              yCursor -= h;
              if (h <= 0) return null;
              return (
                <rect
                  key={seg.key}
                  x={x}
                  y={yCursor}
                  width={Math.max(1, barWidth)}
                  height={h}
                  fill={seg.color}
                  rx={1.5}
                >
                  <title>{`${w.week_start.split("T")[0]} — ${seg.key}: ${seg.value}`}</title>
                </rect>
              );
            })}
          </g>
        );
      })}
      <line
        x1={padding}
        y1={height - padding}
        x2={width - padding}
        y2={height - padding}
        stroke="currentColor"
        className="text-slate-200 dark:text-slate-700"
      />
    </svg>
  );
}

export function AnalyticsView() {
  const { session } = useAuth();
  const toast = useToast();
  const [trends, setTrends] = useState<Trends | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!session) return;
    let cancelled = false;
    (async () => {
      try {
        const t = await getTrends(session);
        if (!cancelled) setTrends(t);
      } catch (err) {
        if (!cancelled) {
          toast.push({
            kind: "error",
            title: "Could not load trends",
            description: (err as Error).message,
          });
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [session, toast]);

  return (
    <div className="space-y-6">
      <PageHeading
        kind="Insights"
        title="Trends"
        subtitle="Compliance decision mix over the last 12 weeks, and your most recurring violations."
      />

      {loading && <p className="text-sm text-slate-500 dark:text-slate-400">Loading…</p>}

      {trends && (
        <>
          <Card>
            <CardHeader
              title="Weekly volume by decision"
              subtitle={
                <span className="inline-flex items-center gap-1">
                  <TrendingUp size={13} /> Last {trends.weeks.length} weeks
                </span>
              }
            />
            {trends.weeks.every((w) => w.total_checks === 0) ? (
              <p className="text-sm text-slate-500 dark:text-slate-400">
                No compliance checks in this window yet.
              </p>
            ) : (
              <TrendChart weeks={trends.weeks} />
            )}
          </Card>

          <Card>
            <CardHeader
              title="Most recurring violations"
              subtitle="Rule citations ranked across every check on record"
            />
            {trends.top_violations.length === 0 ? (
              <p className="text-sm text-slate-500 dark:text-slate-400">
                No rule citations recorded yet.
              </p>
            ) : (
              <ul className="divide-y divide-slate-100 dark:divide-slate-800">
                {trends.top_violations.map((v, i) => (
                  <li
                    key={v.rule_id}
                    className="flex items-center justify-between py-2.5 text-sm"
                  >
                    <span className="flex items-center gap-2 text-slate-700 dark:text-slate-300">
                      <AlertTriangle size={13} className="text-status-warning" />
                      <span className="font-mono-num text-slate-400">{i + 1}.</span>
                      {v.rule_id}
                    </span>
                    <span className="font-mono-num font-semibold text-slate-900 dark:text-slate-50">
                      {v.count}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </>
      )}
    </div>
  );
}
```

- [ ] **Step 3: Wire up routing and navigation**

In `apps/dashboard/src/App.tsx`, add the import alongside the other view imports:

```typescript
import { AnalyticsView } from "./views/AnalyticsView";
```

And add the route inside the authenticated `<Routes>` block, next to the reports route:

```tsx
<Route path="trends" element={<AnalyticsView />} />
```

In `apps/dashboard/src/components/Layout.tsx`, add `TrendingUp` to the `lucide-react` import list, and add a nav entry to the `"Records"` group, after Reports:

```typescript
{ to: "/trends", label: "Trends", icon: TrendingUp },
```

- [ ] **Step 4: Verify**

Run: `cd compliance-agent/apps/dashboard && npm run build`
Expected: `tsc --noEmit` and the Vite build both succeed with no type errors.

Manual check: `npm run dev`, log in with a dev-mode tenant, navigate to `/trends`, confirm the page loads (either real data if the local gateway has checks, or the two empty-state messages if not).

- [ ] **Step 5: Commit**

```bash
git add apps/dashboard/src/api/client.ts apps/dashboard/src/views/AnalyticsView.tsx apps/dashboard/src/App.tsx apps/dashboard/src/components/Layout.tsx
git commit -m "Add Trends dashboard view for cross-tenant analytics"
```

---

### Task 7: PDF rendering in the reporting agent

**Files:**
- Modify: `services/reporting-agent/requirements.txt` (add `weasyprint`)
- Modify: `services/reporting-agent/Dockerfile` (add system libs)
- Modify: `services/reporting-agent/reporting_agent/reporter.py` (add `_render_pdf`, dual-write in `generate_report`)
- Modify: `tests/unit/test_reporting_agent.py` (append PDF-path tests)

**Interfaces:**
- Produces: `_render_pdf(html: str) -> bytes | None` — a monkeypatchable seam. Returns `None` (never raises) if WeasyPrint or its system libraries aren't available, or if rendering itself fails. This is the design choice that keeps unit tests hermetic: they monkeypatch `_render_pdf` directly and never need WeasyPrint's system dependencies (Cairo/Pango) installed on the dev machine — relevant since local dev here is Windows, where those are notoriously painful to install outside a container.

- [ ] **Step 1: Write the failing tests**

Add these two methods inside the existing `TestReportGeneration` class in `tests/unit/test_reporting_agent.py` (they use the class's existing `self._run()` helper):

```python
    def test_pdf_success_sets_content_ref_to_pdf(self, monkeypatch):
        from reporting_agent import reporter

        monkeypatch.setattr(reporter, "_render_pdf", lambda html: b"%PDF-1.4 fake pdf bytes")
        outcome, storage, _, auditor = self._run()
        assert outcome.content_ref.endswith(".pdf")
        bucket = storage.buckets["cg-local-cg-reports"]
        pdf_blob = bucket.blobs[f"tenant-a/{outcome.report_id}/report.pdf"]
        assert pdf_blob.content == b"%PDF-1.4 fake pdf bytes"
        assert any(e["action"] == "report.pdf_rendered" for e in auditor.events)

    def test_pdf_failure_falls_back_to_html_content_ref(self, monkeypatch):
        from reporting_agent import reporter

        monkeypatch.setattr(reporter, "_render_pdf", lambda html: None)
        outcome, _, _, auditor = self._run()
        assert outcome.content_ref.endswith(".html")
        assert any(e["action"] == "report.pdf_render_failed" for e in auditor.events)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd compliance-agent && python -m pytest tests/unit/test_reporting_agent.py -v`
Expected: FAIL — `AttributeError: <module 'reporting_agent.reporter'> does not have the attribute '_render_pdf'`

- [ ] **Step 3: Write the implementation**

In `services/reporting-agent/requirements.txt`, add:

```
weasyprint>=62,<64
```

In `services/reporting-agent/Dockerfile`, insert before the `COPY shared/` line:

```dockerfile
# WeasyPrint (PDF rendering) needs these system libraries — pip install
# alone is not sufficient, unlike every other dependency in this image.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libcairo2 \
    libgdk-pixbuf2.0-0 \
    libffi-dev \
    shared-mime-info \
    && rm -rf /var/lib/apt/lists/*

```

In `services/reporting-agent/reporting_agent/reporter.py`, add this function after `_fixture_gemini_data` and before `generate_report`:

```python
def _render_pdf(html: str) -> bytes | None:
    """Render HTML to PDF bytes. Returns None (never raises) if WeasyPrint or
    its system dependencies aren't available, or if rendering itself fails —
    report generation must never fail because PDF rendering did."""
    try:
        from weasyprint import HTML  # local import: optional at runtime

        return HTML(string=html).write_pdf()
    except Exception:
        logger.warning("PDF rendering unavailable or failed", exc_info=True)
        return None
```

In `generate_report()`, replace the current GCS-write block:

```python
    bucket_name = reports_bucket()
    blob_path = f"{tenant_id}/{report_id}/report.html"
    bucket = storage_client.bucket(bucket_name)
    bucket.blob(blob_path).upload_from_string(html.encode("utf-8"), content_type="text/html")
    content_ref = f"gs://{bucket_name}/{blob_path}"
    logger.info("report HTML written to %s", content_ref)
```

with:

```python
    bucket_name = reports_bucket()
    bucket = storage_client.bucket(bucket_name)

    html_blob_path = f"{tenant_id}/{report_id}/report.html"
    bucket.blob(html_blob_path).upload_from_string(html.encode("utf-8"), content_type="text/html")

    pdf_bytes = _render_pdf(html)
    if pdf_bytes is not None:
        pdf_blob_path = f"{tenant_id}/{report_id}/report.pdf"
        bucket.blob(pdf_blob_path).upload_from_string(pdf_bytes, content_type="application/pdf")
        content_ref = f"gs://{bucket_name}/{pdf_blob_path}"
        auditor.log(
            tenant_id=tenant_id,
            actor=generated_by,
            action="report.pdf_rendered",
            dedup_key=f"{report_id}:pdf",
            before_state=None,
            after_state={"report_id": report_id},
        )
    else:
        content_ref = f"gs://{bucket_name}/{html_blob_path}"
        auditor.log(
            tenant_id=tenant_id,
            actor=generated_by,
            action="report.pdf_render_failed",
            dedup_key=f"{report_id}:pdf_failed",
            before_state=None,
            after_state={"report_id": report_id},
        )
    logger.info("report artifacts written; content_ref=%s", content_ref)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd compliance-agent && python -m pytest tests/unit/test_reporting_agent.py -v`
Expected: PASS (all tests, including the two new ones — the pre-existing tests pass regardless of whether WeasyPrint's system libraries are actually installed locally, since they never monkeypatch `_render_pdf` and rely on its built-in graceful fallback to `None`)

- [ ] **Step 5: Commit**

```bash
git add services/reporting-agent/requirements.txt services/reporting-agent/Dockerfile services/reporting-agent/reporting_agent/reporter.py tests/unit/test_reporting_agent.py
git commit -m "Render compliance reports to PDF, with graceful HTML fallback"
```

---

### Task 8: Serve PDF (with HTML fallback) from `/api/reports/{id}`

**Files:**
- Modify: `apps/api-gateway/api_gateway/main.py:853-865` (`get_report` handler), and the `fastapi` import line (~38).
- Test: `tests/unit/test_reports_endpoint.py`

**Interfaces:**
- Consumes: the `report.pdf` / `report.html` blob-naming convention Task 7 writes.
- Produces: `GET /api/reports/{report_id}` now returns `application/pdf` (with `Content-Disposition: inline`) when a PDF blob exists, falls back to the existing `text/html` response when it doesn't, and 404s only when neither exists.

- [ ] **Step 1: Write the failing tests**

```python
"""Unit tests: GET /api/reports/{id} — PDF-first with HTML fallback (hermetic)."""

from __future__ import annotations

import base64
import json

import pytest
from fastapi.testclient import TestClient


def _dev_token(uid: str, tenant_id: str, role: str) -> str:
    claims = {"uid": uid, "tenant_id": tenant_id, "role": role}
    raw = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return f"dev:{raw}"


class FakeBlob:
    def __init__(self, data: bytes | None):
        self._data = data

    def exists(self):
        return self._data is not None

    def download_as_bytes(self):
        return self._data

    def download_as_text(self):
        return self._data.decode("utf-8")


class FakeBucket:
    def __init__(self, blobs: dict[str, bytes]):
        self._blobs = blobs

    def blob(self, path):
        return FakeBlob(self._blobs.get(path))


class FakeStorage:
    def __init__(self, blobs: dict[str, bytes]):
        self._bucket = FakeBucket(blobs)

    def bucket(self, _name):
        return self._bucket


class FakeGateway:
    def __init__(self, blobs: dict[str, bytes]):
        self.storage = FakeStorage(blobs)


def _make_client(monkeypatch, blobs: dict[str, bytes]):
    monkeypatch.setenv("CG_AUTH_DEV_MODE", "1")
    import api_gateway.main as main
    import auth_middleware

    monkeypatch.setattr(auth_middleware, "_ensure_firebase_app", lambda: None)
    fake = FakeGateway(blobs)
    monkeypatch.setattr(main, "_gateway", fake)
    monkeypatch.setattr(main, "gw", lambda: fake)
    return TestClient(main.app)


AUTH_HEADER = {"Authorization": f"Bearer {_dev_token('u1', 'tenant-a', 'owner')}"}


class TestGetReport:
    def test_serves_pdf_when_present(self, monkeypatch):
        c = _make_client(monkeypatch, {"tenant-a/report-1/report.pdf": b"%PDF-1.4 fake"})
        r = c.get("/api/reports/report-1", headers=AUTH_HEADER)
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("application/pdf")
        assert r.content == b"%PDF-1.4 fake"

    def test_falls_back_to_html_when_no_pdf(self, monkeypatch):
        c = _make_client(monkeypatch, {"tenant-a/report-1/report.html": b"<html>report</html>"})
        r = c.get("/api/reports/report-1", headers=AUTH_HEADER)
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/html")
        assert "report" in r.text

    def test_404_when_neither_exists(self, monkeypatch):
        c = _make_client(monkeypatch, {})
        r = c.get("/api/reports/report-1", headers=AUTH_HEADER)
        assert r.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd compliance-agent && python -m pytest tests/unit/test_reports_endpoint.py -v`
Expected: FAIL — `test_serves_pdf_when_present` gets HTML/404 behavior since the handler only ever looks for `report.html` today.

- [ ] **Step 3: Write the implementation**

In `apps/api-gateway/api_gateway/main.py`, add `Response` to the existing `fastapi` import line (~38):

```python
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile, status
```

Replace the `get_report` handler (lines 853-865):

```python
@app.get("/api/reports/{report_id}", response_class=HTMLResponse)
def get_report(
    report_id: str, auth: AuthContext = Depends(require_auth)
) -> HTMLResponse:
    from gcp_clients import reports_bucket

    g = gw()
    blob_path = f"{auth.tenant_id}/{report_id}/report.html"
    bucket = g.storage.bucket(reports_bucket())
    blob = bucket.blob(blob_path)
    if not blob.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="report not found")
    return HTMLResponse(content=blob.download_as_text())
```

with:

```python
@app.get("/api/reports/{report_id}")
def get_report(report_id: str, auth: AuthContext = Depends(require_auth)) -> Response:
    from gcp_clients import reports_bucket

    g = gw()
    bucket = g.storage.bucket(reports_bucket())

    pdf_blob = bucket.blob(f"{auth.tenant_id}/{report_id}/report.pdf")
    if pdf_blob.exists():
        return Response(
            content=pdf_blob.download_as_bytes(),
            media_type="application/pdf",
            headers={"Content-Disposition": f'inline; filename="report-{report_id}.pdf"'},
        )

    html_blob = bucket.blob(f"{auth.tenant_id}/{report_id}/report.html")
    if html_blob.exists():
        return HTMLResponse(content=html_blob.download_as_text())

    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="report not found")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd compliance-agent && python -m pytest tests/unit/test_reports_endpoint.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add apps/api-gateway/api_gateway/main.py tests/unit/test_reports_endpoint.py
git commit -m "Serve rendered PDF reports, falling back to HTML"
```

---

### Task 9: Dashboard — PDF-aware report download

**Files:**
- Modify: `apps/dashboard/src/views/ReportsView.tsx:75-99` (`openReport`), and the "View full HTML" button label (~line 187).

**Interfaces:**
- Consumes: `GET /api/reports/{id}` from Task 8, which now returns either `application/pdf` or `text/html` depending on what's stored.

- [ ] **Step 1: Update `openReport`**

Replace the body of `openReport` in `apps/dashboard/src/views/ReportsView.tsx`:

```tsx
  const openReport = async (reportId: string) => {
    if (!session) return;
    setOpeningId(reportId);
    try {
      const token = await session.getToken();
      const res = await fetch(`${API_BASE_URL}/api/reports/${reportId}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new ApiError(res.status, body.detail ?? res.statusText);
      }
      const url = URL.createObjectURL(
        new Blob([await res.text()], { type: "text/html" }),
      );
      window.open(url, "_blank", "noopener,noreferrer");
      window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch (err) {
      const msg = (err as Error).message;
      toast.push({ kind: "error", title: "Could not open report", description: msg });
    } finally {
      setOpeningId(null);
    }
  };
```

with:

```tsx
  const openReport = async (reportId: string) => {
    if (!session) return;
    setOpeningId(reportId);
    try {
      const token = await session.getToken();
      const res = await fetch(`${API_BASE_URL}/api/reports/${reportId}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new ApiError(res.status, body.detail ?? res.statusText);
      }
      // The backend serves PDF when available, HTML otherwise — read the
      // actual bytes and trust the response's own Content-Type rather than
      // assuming HTML (a PDF read via .text() would corrupt the binary).
      const contentType = (res.headers.get("content-type") ?? "text/html").split(";")[0];
      const blob = await res.blob();
      const url = URL.createObjectURL(new Blob([blob], { type: contentType }));
      window.open(url, "_blank", "noopener,noreferrer");
      window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch (err) {
      const msg = (err as Error).message;
      toast.push({ kind: "error", title: "Could not open report", description: msg });
    } finally {
      setOpeningId(null);
    }
  };
```

Update the button label (currently `{openingId === report.report_id ? "Opening…" : "View full HTML"}`) to:

```tsx
{openingId === report.report_id ? "Opening…" : "View report"}
```

- [ ] **Step 2: Verify**

Run: `cd compliance-agent/apps/dashboard && npm run build`
Expected: `tsc --noEmit` and Vite build succeed.

Manual check: with the local gateway running, generate a report and click "View report" — it should open in a new tab. Note: on a machine without WeasyPrint's system libraries available to the reporting-agent process (true for a bare `uvicorn` run on Windows without the updated Docker image), this will exercise the HTML fallback path, not PDF — the PDF path is only fully exercised by a container built from the updated Dockerfile (Task 7) or the deployed Cloud Run service after that image is redeployed.

- [ ] **Step 3: Commit**

```bash
git add apps/dashboard/src/views/ReportsView.tsx
git commit -m "Open reports as PDF when available, falling back to HTML"
```

---

## After execution

Tasks 1-6 (upload validation + analytics) are pure application-code changes — safe to deploy the normal way. Task 7's Dockerfile change is real infrastructure surface on a live, billed Cloud Run service; do not build/push/redeploy the reporting-agent image without confirming with the user first, per this plan's Global Constraints.
