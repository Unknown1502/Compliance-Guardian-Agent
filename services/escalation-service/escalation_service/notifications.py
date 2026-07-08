"""Escalation notification — record that a check needs human review.

A pluggable Notifier keeps the transport (email, Slack, webhook) out of the
core flow. The default AuditNotifier records the notification as an immutable
audit event AND writes a lightweight notification record to Firestore so the
dashboard can surface a reviewer inbox. In production a real transport (e.g.
SendGrid / Slack) is added behind the same interface without touching callers.
"""

from __future__ import annotations

import logging
from typing import Protocol

from audit_logger import AuditLogger
from google.cloud import firestore

logger = logging.getLogger("cg.escalation.notify")

COLLECTION_NOTIFICATIONS = "notifications"


class Notifier(Protocol):
    def notify_escalation(
        self, *, tenant_id: str, check_id: str, document_id: str, risk_score: int
    ) -> None:
        ...


class AuditNotifier:
    """Records escalation notifications to Firestore + the audit trail."""

    def __init__(self, db: firestore.Client, auditor: AuditLogger) -> None:
        self._db = db
        self._auditor = auditor

    def notify_escalation(
        self, *, tenant_id: str, check_id: str, document_id: str, risk_score: int
    ) -> None:
        # Idempotent notification doc id: one notification per check.
        notif_id = f"escalation-{check_id}"
        self._db.collection(COLLECTION_NOTIFICATIONS).document(notif_id).set(
            {
                "notification_id": notif_id,
                "tenant_id": tenant_id,
                "check_id": check_id,
                "document_id": document_id,
                "risk_score": risk_score,
                "kind": "escalation",
                "status": "pending",
            }
        )
        self._auditor.log(
            tenant_id=tenant_id,
            actor="escalation-service",
            action="check.escalation_notified",
            dedup_key=f"{check_id}:notified",
            before_state=None,
            after_state={"check_id": check_id, "risk_score": risk_score},
        )
        logger.info("escalation notification recorded for check %s", check_id)
