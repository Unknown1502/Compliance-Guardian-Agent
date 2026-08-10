"""Support notifications.

Deliberately shaped like the Slack notifier already in this codebase: a real
adapter that is inert until configured, rather than a stub to be replaced
later. Adding an email provider is then a secret, not a code change.

Two channels, and the difference matters:

  * The AUDIT TRAIL is the guarantee. Every ticket event is written there
    before anything else is attempted, so a notification failing to send can
    never mean the event is lost.
  * EMAIL is the convenience. It is best-effort, never blocks a request, and
    is silently skipped when no provider is configured — a support system that
    500s because a mail API is down is worse than one that is quiet.

Nothing here invents delivery it cannot perform. With no provider configured,
`send` returns False and says why, and the caller carries on. The product
never tells a customer an email was sent when it was not.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request

logger = logging.getLogger("cg.support.notify")

_TIMEOUT = 10


class EmailNotifier:
    """Transactional email via Resend.

    Resend rather than SMTP because Cloud Run has no outbound SMTP and an HTTP
    API needs no connection pooling, no TLS negotiation and no credentials
    beyond one key. Swapping to another provider means changing this class and
    nothing else.
    """

    API = "https://api.resend.com/emails"

    def __init__(self, api_key: str | None = None, sender: str | None = None) -> None:
        self.api_key = api_key or os.environ.get("RESEND_API_KEY", "")
        # Must be a domain verified with the provider. Until one exists this
        # stays unset and the notifier stays inert.
        self.sender = sender or os.environ.get("SUPPORT_FROM_EMAIL", "")

    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.sender)

    def send(self, *, to: str, subject: str, body: str) -> bool:
        """Best-effort send. Returns whether it actually went out.

        Never raises. A support request must be recorded whether or not the
        mail provider is reachable, so every failure here is logged and
        swallowed rather than propagated into the request.
        """
        if not self.configured:
            logger.info("email not configured; skipping notification to %s", to)
            return False
        if not to:
            return False
        payload = json.dumps(
            {
                "from": self.sender,
                "to": [to],
                "subject": subject,
                # Plain text on purpose: support mail is read, not admired, and
                # HTML would mean escaping customer-supplied content into a
                # template — an injection surface for no benefit.
                "text": body,
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            self.API,
            data=payload,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
                return 200 <= resp.status < 300
        except urllib.error.HTTPError as exc:
            body_text = exc.read().decode("utf-8", errors="replace")[:200]
            logger.warning("email send failed (%s): %s", exc.code, body_text)
        except Exception:
            logger.warning("email send failed", exc_info=True)
        return False


def notify_new_ticket(notifier: EmailNotifier, *, reference: str, to: str) -> bool:
    """Acknowledge to the customer that their request exists."""
    return notifier.send(
        to=to,
        subject=f"[{reference}] We received your request",
        body=(
            f"Thanks for getting in touch.\n\n"
            f"Your reference is {reference}. Quote it if you write to us again.\n\n"
            f"We read every request and will reply as soon as we can. You can "
            f"also see the status and any replies by signing in and opening "
            f"Support.\n\n"
            f"— ComplianceGuardian"
        ),
    )


def notify_reply(notifier: EmailNotifier, *, reference: str, to: str) -> bool:
    """Tell the customer a reply is waiting.

    Deliberately does NOT include the reply text. Support threads can contain
    account details, and email is not a channel we control once sent — the
    customer signs in to read it.
    """
    return notifier.send(
        to=to,
        subject=f"[{reference}] ComplianceGuardian Support replied",
        body=(
            f"There is a new reply on your support request {reference}.\n\n"
            f"Sign in and open Support to read it and respond.\n\n"
            f"— ComplianceGuardian"
        ),
    )
