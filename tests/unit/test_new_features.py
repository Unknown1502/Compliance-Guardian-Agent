"""Unit tests: API keys, Slack notifications, and retention.

Hermetic — no network, no emulators. The security-relevant properties are
what these actually pin down: keys are never stored in plaintext, the
webhook validator is a real SSRF boundary, and retention refuses to delete
anything it hasn't been explicitly and safely configured to delete.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytest

from api_keys import (
    KEY_PREFIX,
    generate_api_key,
    hash_api_key,
    looks_like_api_key,
    verify_api_key,
)
from notifications import (
    InvalidWebhookUrlError,
    SlackNotifier,
    build_escalation_message,
    mask_webhook_url,
    validate_slack_webhook_url,
)
from retention import MIN_RETENTION_DAYS, sweep_tenant


# ---------------------------------------------------------------------------
# API keys
# ---------------------------------------------------------------------------


class TestApiKeys:
    def test_generated_key_shape(self):
        g = generate_api_key()
        assert g.plaintext.startswith(KEY_PREFIX)
        assert len(g.key_hash) == 64
        assert g.display_prefix == g.plaintext[:12]

    def test_plaintext_is_not_recoverable_from_hash(self):
        g = generate_api_key()
        # The stored artefacts must not contain the secret.
        assert g.plaintext not in g.key_hash
        assert g.plaintext not in g.display_prefix

    def test_keys_are_unique(self):
        keys = {generate_api_key().plaintext for _ in range(50)}
        assert len(keys) == 50

    def test_verify_accepts_only_the_right_key(self):
        g = generate_api_key()
        assert verify_api_key(g.plaintext, g.key_hash) is True
        assert verify_api_key(g.plaintext + "x", g.key_hash) is False
        assert verify_api_key(generate_api_key().plaintext, g.key_hash) is False

    def test_hash_is_stable(self):
        g = generate_api_key()
        assert hash_api_key(g.plaintext) == g.key_hash

    @pytest.mark.parametrize(
        "value,expected",
        [
            ("", False),
            ("not-a-key", False),
            ("cg_live_", False),  # prefix only, no entropy
            ("cg_live_short", False),
            (generate_api_key().plaintext, True),
        ],
    )
    def test_shape_check(self, value, expected):
        assert looks_like_api_key(value) is expected


# ---------------------------------------------------------------------------
# Slack webhook validation — this is an SSRF boundary, not a formatting nicety
# ---------------------------------------------------------------------------


class TestSlackWebhookValidation:
    def test_accepts_real_slack_webhook(self):
        url = "https://hooks.slack.com/services/T000/B000/XXXXXXXX"
        assert validate_slack_webhook_url(url) == url

    @pytest.mark.parametrize(
        "bad",
        [
            "",
            "   ",
            "http://hooks.slack.com/services/T/B/X",       # not https
            "https://evil.example.com/services/T/B/X",     # wrong host
            "https://hooks.slack.com.evil.com/services/x",  # suffix trick
            "https://hooks.slack.com/api/chat.postMessage",  # wrong path
            "http://169.254.169.254/latest/meta-data/",    # cloud metadata
            "http://localhost:8080/internal",              # loopback
            "file:///etc/passwd",
        ],
    )
    def test_rejects_everything_else(self, bad):
        with pytest.raises(InvalidWebhookUrlError):
            validate_slack_webhook_url(bad)

    def test_mask_hides_the_secret(self):
        url = "https://hooks.slack.com/services/T000/B000/SUPERSECRETTOKEN"
        masked = mask_webhook_url(url)
        assert "SUPERSECRETTOKEN" not in masked
        assert masked.startswith("https://hooks.slack.com/services/")

    def test_mask_of_empty_is_empty(self):
        assert mask_webhook_url("") == ""

    def test_message_contains_the_essentials(self):
        msg = build_escalation_message(
            tenant_name="Sunrise Care",
            check_id="chk-1",
            document_id="doc-1",
            risk_score=95,
            review_url="https://example.com/checks/chk-1",
        )
        blob = str(msg)
        assert "95" in blob and "doc-1" in blob and "Sunrise Care" in blob

    def test_message_omits_button_without_url(self):
        msg = build_escalation_message(
            tenant_name="T", check_id="c", document_id="d", risk_score=10, review_url=""
        )
        assert all(b.get("type") != "actions" for b in msg["blocks"])


# ---------------------------------------------------------------------------
# SlackNotifier behaviour
# ---------------------------------------------------------------------------


@dataclass
class _FakeTenant:
    tenant_id: str = "tenant-a"
    name: str = "Sunrise Care"
    slack_webhook_url: str = ""
    retention_days: int = 0


class _FakeInner:
    def __init__(self):
        self.calls = []
        self._auditor = _FakeAuditor()

    def notify_escalation(self, **kw):
        self.calls.append(kw)


class _FakeAuditor:
    def __init__(self):
        self.events = []

    def log(self, **kw):
        self.events.append(kw)


class _FakeRepo:
    def __init__(self, tenant):
        self._tenant = tenant

    def get_tenant(self, tenant_id):
        return self._tenant


class TestSlackNotifier:
    def _notify(self, notifier):
        notifier.notify_escalation(
            tenant_id="tenant-a", check_id="chk-1", document_id="doc-1", risk_score=95
        )

    def test_inner_always_runs_even_without_slack(self):
        inner = _FakeInner()
        n = SlackNotifier(inner, _FakeRepo(_FakeTenant()))
        self._notify(n)
        assert len(inner.calls) == 1  # audit record written regardless

    def test_no_slack_call_when_unconfigured(self, monkeypatch):
        posted = []
        monkeypatch.setattr(
            "notifications.post_to_slack", lambda u, p: posted.append((u, p))
        )
        n = SlackNotifier(_FakeInner(), _FakeRepo(_FakeTenant()))
        self._notify(n)
        assert posted == []

    def test_posts_when_configured(self, monkeypatch):
        posted = []
        monkeypatch.setattr(
            "notifications.post_to_slack", lambda u, p: posted.append((u, p))
        )
        tenant = _FakeTenant(slack_webhook_url="https://hooks.slack.com/services/T/B/X")
        inner = _FakeInner()
        n = SlackNotifier(inner, _FakeRepo(tenant), dashboard_base_url="https://app.example.com")
        self._notify(n)
        assert len(posted) == 1
        assert "chk-1" in str(posted[0][1])
        assert any(e["action"] == "notification.slack_sent" for e in inner._auditor.events)

    def test_slack_failure_never_breaks_the_check(self, monkeypatch):
        def boom(url, payload):
            raise OSError("slack is down")

        monkeypatch.setattr("notifications.post_to_slack", boom)
        tenant = _FakeTenant(slack_webhook_url="https://hooks.slack.com/services/T/B/X")
        inner = _FakeInner()
        n = SlackNotifier(inner, _FakeRepo(tenant))
        self._notify(n)  # must not raise
        assert len(inner.calls) == 1
        assert any(e["action"] == "notification.slack_failed" for e in inner._auditor.events)

    def test_tenant_lookup_failure_never_breaks_the_check(self):
        class Broken:
            def get_tenant(self, tenant_id):
                raise RuntimeError("firestore down")

        inner = _FakeInner()
        n = SlackNotifier(inner, Broken())
        self._notify(n)  # must not raise
        assert len(inner.calls) == 1


# ---------------------------------------------------------------------------
# Retention — the only code that deletes customer data
# ---------------------------------------------------------------------------


@dataclass
class _FakeDoc:
    document_id: str
    tenant_id: str
    storage_ref: str
    created_at: datetime


class _RetentionRepo:
    def __init__(self, docs):
        self._docs = docs
        self.deleted = []

    def list_documents_created_before(self, tenant_id, cutoff, limit=500):
        return [
            d for d in self._docs if d.tenant_id == tenant_id and d.created_at < cutoff
        ][:limit]

    def delete_document(self, document_id, tenant_id):
        self.deleted.append(document_id)


class _FakeStorage:
    def __init__(self):
        self.deleted_blobs = []

    def bucket(self, name):
        return self

    def blob(self, path):
        outer = self

        class _B:
            def exists(self_inner):
                return True

            def delete(self_inner):
                outer.deleted_blobs.append(path)

        return _B()


def _docs(now):
    return [
        _FakeDoc("doc-old", "tenant-a", "gs://b/tenant-a/doc-old/f.txt", now - timedelta(days=400)),
        _FakeDoc("doc-new", "tenant-a", "gs://b/tenant-a/doc-new/f.txt", now - timedelta(days=5)),
        _FakeDoc("doc-other", "tenant-b", "gs://b/tenant-b/doc-x/f.txt", now - timedelta(days=400)),
    ]


class TestRetention:
    def test_disabled_by_default_deletes_nothing(self):
        now = datetime.now(timezone.utc)
        repo = _RetentionRepo(_docs(now))
        res = sweep_tenant(
            tenant=_FakeTenant(retention_days=0),
            repo=repo,
            storage_client=_FakeStorage(),
            auditor=_FakeAuditor(),
            now=now,
        )
        assert repo.deleted == []
        assert "keep forever" in res.skipped_reason

    def test_refuses_retention_below_floor(self):
        now = datetime.now(timezone.utc)
        repo = _RetentionRepo(_docs(now))
        res = sweep_tenant(
            tenant=_FakeTenant(retention_days=1),  # dangerously short
            repo=repo,
            storage_client=_FakeStorage(),
            auditor=_FakeAuditor(),
            now=now,
        )
        assert repo.deleted == []
        assert "below floor" in res.skipped_reason

    def test_deletes_only_documents_past_the_cutoff(self):
        now = datetime.now(timezone.utc)
        repo = _RetentionRepo(_docs(now))
        storage = _FakeStorage()
        auditor = _FakeAuditor()
        sweep_tenant(
            tenant=_FakeTenant(retention_days=365),
            repo=repo,
            storage_client=storage,
            auditor=auditor,
            now=now,
        )
        assert repo.deleted == ["doc-old"]  # not doc-new
        assert len(storage.deleted_blobs) == 1

    def test_never_touches_another_tenant(self):
        now = datetime.now(timezone.utc)
        repo = _RetentionRepo(_docs(now))
        sweep_tenant(
            tenant=_FakeTenant(tenant_id="tenant-a", retention_days=365),
            repo=repo,
            storage_client=_FakeStorage(),
            auditor=_FakeAuditor(),
            now=now,
        )
        assert "doc-other" not in repo.deleted

    def test_deletion_is_recorded_in_the_audit_trail(self):
        now = datetime.now(timezone.utc)
        auditor = _FakeAuditor()
        sweep_tenant(
            tenant=_FakeTenant(retention_days=365),
            repo=_RetentionRepo(_docs(now)),
            storage_client=_FakeStorage(),
            auditor=auditor,
            now=now,
        )
        events = [e for e in auditor.events if e["action"] == "document.retention_deleted"]
        assert len(events) == 1
        # The record of what was deleted must survive the deletion.
        assert events[0]["before_state"]["document_id"] == "doc-old"

    def test_dry_run_reports_without_deleting(self):
        now = datetime.now(timezone.utc)
        repo = _RetentionRepo(_docs(now))
        storage = _FakeStorage()
        auditor = _FakeAuditor()
        res = sweep_tenant(
            tenant=_FakeTenant(retention_days=365),
            repo=repo,
            storage_client=storage,
            auditor=auditor,
            now=now,
            dry_run=True,
        )
        assert res.deleted == ["doc-old"]  # would delete
        assert repo.deleted == []           # but didn't
        assert storage.deleted_blobs == []
        assert auditor.events == []

    def test_one_bad_document_does_not_stop_the_sweep(self):
        now = datetime.now(timezone.utc)
        docs = [
            _FakeDoc("doc-bad", "tenant-a", "gs://b/a/bad/f.txt", now - timedelta(days=400)),
            _FakeDoc("doc-ok", "tenant-a", "gs://b/a/ok/f.txt", now - timedelta(days=400)),
        ]

        class FlakyRepo(_RetentionRepo):
            def delete_document(self, document_id, tenant_id):
                if document_id == "doc-bad":
                    raise RuntimeError("permission denied")
                super().delete_document(document_id, tenant_id)

        repo = FlakyRepo(docs)
        res = sweep_tenant(
            tenant=_FakeTenant(retention_days=365),
            repo=repo,
            storage_client=_FakeStorage(),
            auditor=_FakeAuditor(),
            now=now,
        )
        assert repo.deleted == ["doc-ok"]
        assert len(res.errors) == 1

    def test_floor_constant_is_meaningfully_large(self):
        # Guards against someone "helpfully" lowering this to 1.
        assert MIN_RETENTION_DAYS >= 30
