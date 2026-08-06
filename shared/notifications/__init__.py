"""Slack escalation notifications.

Wraps an existing Notifier rather than replacing it, so the audit record is
always written first and a Slack outage can never cost us the compliance
record. Slack delivery is explicitly best-effort: every failure is caught,
logged to the audit trail, and swallowed. A notification transport must
never be able to fail a compliance check.

SSRF note: the webhook URL is tenant-supplied and fetched by our server, so
it is validated against the Slack host allowlist both on write (API) and
again here at send time. Validating only at write time would leave any
row written before the check — or by a future code path — exploitable.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request

logger = logging.getLogger("cg.notifications.slack")

# Slack incoming webhooks are always on this host. Anything else is either a
# mistake or an attempt to point our server at somewhere it shouldn't go.
_ALLOWED_HOSTS = frozenset({"hooks.slack.com"})
_TIMEOUT_SECONDS = 5


class InvalidWebhookUrlError(ValueError):
    """Raised when a webhook URL is not an acceptable Slack webhook."""


def validate_slack_webhook_url(url: str) -> str:
    """Return the URL if it is a plausible Slack incoming webhook, else raise.

    Deliberately strict: https only, exact host match, and the /services/
    path Slack uses. This is the SSRF boundary — a permissive check here
    turns the gateway into a request proxy for internal addresses.
    """
    candidate = (url or "").strip()
    if not candidate:
        raise InvalidWebhookUrlError("webhook URL is empty")
    parsed = urllib.parse.urlparse(candidate)
    if parsed.scheme != "https":
        raise InvalidWebhookUrlError("webhook URL must use https")
    if parsed.hostname not in _ALLOWED_HOSTS:
        raise InvalidWebhookUrlError(
            f"webhook host must be one of {sorted(_ALLOWED_HOSTS)}; got {parsed.hostname!r}"
        )
    if not parsed.path.startswith("/services/"):
        raise InvalidWebhookUrlError("webhook URL must be a Slack /services/ webhook")
    return candidate


def mask_webhook_url(url: str) -> str:
    """Mask a stored webhook for display — it is a bearer secret."""
    if not url:
        return ""
    parsed = urllib.parse.urlparse(url)
    tail = parsed.path.rsplit("/", 1)[-1]
    keep = tail[:4]
    return f"https://{parsed.hostname}/services/.../{keep}{'...' if len(tail) > 4 else ''}"


def post_to_slack(webhook_url: str, payload: dict) -> None:
    """POST a JSON payload to a Slack webhook. Raises on failure."""
    validate_slack_webhook_url(webhook_url)  # re-validate at send time
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        webhook_url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=_TIMEOUT_SECONDS) as resp:
        if resp.status >= 300:
            raise RuntimeError(f"slack returned HTTP {resp.status}")


def build_escalation_message(
    *, tenant_name: str, check_id: str, document_id: str, risk_score: int, review_url: str
) -> dict:
    """Compose the Slack message for one escalated compliance check."""
    return {
        "text": f"Compliance check escalated — risk {risk_score}/100 ({document_id})",
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"*Compliance check escalated*\n"
                        f"*{tenant_name}* · risk *{risk_score}/100*\n"
                        f"Document `{document_id}` needs a human decision."
                    ),
                },
            },
            {
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": f"check `{check_id}`"}],
            },
        ]
        + (
            [
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "Review"},
                            "url": review_url,
                        }
                    ],
                }
            ]
            if review_url
            else []
        ),
    }


class SlackNotifier:
    """Decorates a Notifier with Slack delivery.

    The wrapped notifier runs first and unconditionally: the immutable audit
    record is the product's actual guarantee, Slack is a convenience on top.
    """

    def __init__(self, inner, repo, dashboard_base_url: str = "") -> None:
        self._inner = inner
        self._repo = repo
        self._base_url = dashboard_base_url.rstrip("/")

    def notify_escalation(
        self, *, tenant_id: str, check_id: str, document_id: str, risk_score: int
    ) -> None:
        # Audit first. If this raises, the caller should know — the record
        # matters more than the alert.
        self._inner.notify_escalation(
            tenant_id=tenant_id,
            check_id=check_id,
            document_id=document_id,
            risk_score=risk_score,
        )

        try:
            tenant = self._repo.get_tenant(tenant_id)
        except Exception:
            logger.exception("could not load tenant %s for Slack notify", tenant_id)
            return

        webhook = getattr(tenant, "slack_webhook_url", "") or ""
        if not webhook:
            return  # notifications not configured for this tenant

        review_url = f"{self._base_url}/checks/{check_id}" if self._base_url else ""
        message = build_escalation_message(
            tenant_name=tenant.name,
            check_id=check_id,
            document_id=document_id,
            risk_score=risk_score,
            review_url=review_url,
        )

        auditor = getattr(self._inner, "_auditor", None)
        try:
            post_to_slack(webhook, message)
            logger.info("slack escalation sent for check %s", check_id)
            if auditor is not None:
                auditor.log(
                    tenant_id=tenant_id,
                    actor="notification-service",
                    action="notification.slack_sent",
                    dedup_key=f"{check_id}:slack",
                    before_state=None,
                    after_state={"check_id": check_id, "channel": "slack"},
                )
        except (urllib.error.URLError, InvalidWebhookUrlError, RuntimeError, OSError) as exc:
            # Never propagate: a failed alert must not fail a compliance check.
            logger.warning("slack escalation failed for check %s: %s", check_id, exc)
            if auditor is not None:
                auditor.log(
                    tenant_id=tenant_id,
                    actor="notification-service",
                    action="notification.slack_failed",
                    dedup_key=f"{check_id}:slack_failed",
                    before_state=None,
                    after_state={"check_id": check_id, "error": str(exc)[:300]},
                )
