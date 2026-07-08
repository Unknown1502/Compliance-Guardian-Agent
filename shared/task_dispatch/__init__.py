"""Task dispatch abstraction.

The Orchestrator dispatches agent work through this interface. Two backends:

  CloudTasksDispatcher (production): enqueues an authenticated HTTP task onto a
  Cloud Tasks queue targeting the agent's Cloud Run URL with an OIDC token.
  Cloud Tasks provides the retry/backoff and at-least-once delivery — which is
  exactly why the agents are idempotent (deterministic IDs from Phase 2).

  InlineDispatcher (local/dev): calls the registered handler synchronously in
  the same process. This is NOT a background thread or ad-hoc timer (which the
  spec forbids) — it is a direct synchronous call, used only because there is
  no official Cloud Tasks emulator. The production path uses Cloud Tasks.

SDK surface verified against docs.cloud.google.com/tasks (google-cloud-tasks
v2): tasks_v2.CloudTasksClient, HttpRequest, OidcToken, HttpMethod,
CreateTaskRequest, client.queue_path, client.create_task.
"""

from __future__ import annotations

import json
import logging
from typing import Callable, Protocol

logger = logging.getLogger("cg.dispatch")


class TaskDispatcher(Protocol):
    def dispatch(self, *, target: str, payload: dict) -> str:
        """Enqueue (or run) work for `target`; return a task identifier."""
        ...


class InlineDispatcher:
    """Synchronous dispatcher for local development and integration tests."""

    def __init__(self, handlers: dict[str, Callable[[dict], None]]):
        self._handlers = handlers

    def dispatch(self, *, target: str, payload: dict) -> str:
        handler = self._handlers.get(target)
        if handler is None:
            raise KeyError(f"no inline handler registered for target {target!r}")
        logger.info("inline dispatch -> %s payload=%s", target, payload)
        handler(payload)
        return f"inline:{target}"


class CloudTasksDispatcher:
    """Production dispatcher: authenticated HTTP tasks onto a Cloud Tasks queue.

    target_urls maps a logical target name (e.g. 'ingest', 'check') to the full
    Cloud Run URL of the receiving endpoint. The OIDC token's audience is the
    target URL so the receiving Cloud Run service can verify it.
    """

    def __init__(
        self,
        *,
        project: str,
        location: str,
        queue: str,
        target_urls: dict[str, str],
        invoker_service_account: str,
        internal_token: str | None = None,
    ):
        # Imported lazily so local/dev environments don't need the tasks client.
        from google.cloud import tasks_v2

        self._tasks_v2 = tasks_v2
        self._client = tasks_v2.CloudTasksClient()
        self._project = project
        self._location = location
        self._queue = queue
        self._target_urls = target_urls
        self._sa = invoker_service_account
        self._internal_token = internal_token

    def dispatch(self, *, target: str, payload: dict) -> str:
        url = self._target_urls.get(target)
        if not url:
            raise KeyError(f"no Cloud Run URL configured for target {target!r}")

        tasks_v2 = self._tasks_v2
        headers = {"Content-Type": "application/json"}
        if self._internal_token:
            headers["X-Internal-Token"] = self._internal_token

        task = tasks_v2.Task(
            http_request=tasks_v2.HttpRequest(
                http_method=tasks_v2.HttpMethod.POST,
                url=url,
                headers=headers,
                body=json.dumps(payload).encode("utf-8"),
                oidc_token=tasks_v2.OidcToken(
                    service_account_email=self._sa,
                    audience=url,
                ),
            ),
        )
        response = self._client.create_task(
            tasks_v2.CreateTaskRequest(
                parent=self._client.queue_path(self._project, self._location, self._queue),
                task=task,
            )
        )
        logger.info("cloud task created: %s", response.name)
        return response.name
