"""Unit tests: audit logger — deterministic IDs, retry path, failure loudness.

BigQuery client is faked at the insert_rows_json boundary (documented client
method) — no invented SDK surface, no network.
"""

from __future__ import annotations

import json

import pytest

from audit_logger import AuditLogger, AuditWriteError, deterministic_event_id


class FakeBQClient:
    """Fakes google.cloud.bigquery.Client.insert_rows_json only."""

    project = "cg-local"

    def __init__(self, fail_times: int = 0, row_errors_times: int = 0):
        self.fail_times = fail_times
        self.row_errors_times = row_errors_times
        self.calls: list[dict] = []

    def insert_rows_json(self, table, rows, row_ids=None):
        self.calls.append({"table": table, "rows": rows, "row_ids": row_ids})
        if self.fail_times > 0:
            self.fail_times -= 1
            raise ConnectionError("simulated transient network failure")
        if self.row_errors_times > 0:
            self.row_errors_times -= 1
            return [{"index": 0, "errors": [{"reason": "backendError"}]}]
        return []


class TestDeterministicEventId:
    def test_same_inputs_same_id(self):
        a = deterministic_event_id("t1", "ingestion-agent", "document.ingested", "doc-1")
        b = deterministic_event_id("t1", "ingestion-agent", "document.ingested", "doc-1")
        assert a == b

    def test_different_dedup_key_different_id(self):
        a = deterministic_event_id("t1", "agent", "action", "doc-1")
        b = deterministic_event_id("t1", "agent", "action", "doc-2")
        assert a != b


class TestAuditLogger:
    def _log(self, client) -> tuple:
        auditor = AuditLogger(client, "compliance_audit", "audit_logs")
        row = auditor.log(
            tenant_id="t1",
            actor="ingestion-agent",
            action="document.ingested",
            dedup_key="doc-1",
            before_state=None,
            after_state={"status": "processed"},
        )
        return auditor, row

    def test_success_writes_one_row_with_insert_id(self):
        client = FakeBQClient()
        _, row = self._log(client)
        assert len(client.calls) == 1
        call = client.calls[0]
        assert call["table"] == "cg-local.compliance_audit.audit_logs"
        assert call["row_ids"] == [row.event_id]  # insertId == event_id → dedup
        payload = call["rows"][0]
        assert payload["tenant_id"] == "t1"
        assert json.loads(payload["after_state"]) == {"status": "processed"}
        assert payload["before_state"] is None

    def test_replay_produces_identical_event_id(self):
        client = FakeBQClient()
        _, row1 = self._log(client)
        _, row2 = self._log(client)
        assert row1.event_id == row2.event_id  # Cloud Task redelivery → same insertId

    def test_retries_transient_exception_then_succeeds(self):
        client = FakeBQClient(fail_times=2)
        _, row = self._log(client)
        assert len(client.calls) == 3
        assert row.event_id

    def test_retries_row_errors_then_succeeds(self):
        client = FakeBQClient(row_errors_times=1)
        self._log(client)
        assert len(client.calls) == 2

    def test_exhausted_retries_raise_loudly(self):
        client = FakeBQClient(fail_times=99)
        with pytest.raises(AuditWriteError):
            self._log(client)
        assert len(client.calls) == 3  # max_attempts default
