"""Gemini client wrapper — the single choke point for every model call.

Why a wrapper (Phase 2 Thinking Protocol):
  Every Gemini call in ComplianceGuardian must, without exception:
    1. Retry transient failures with exponential backoff (429/500/502/503/504).
    2. Enforce strict JSON: parse the response, and if the model returns
       non-JSON despite response_mime_type='application/json', retry ONCE with
       an explicit repair instruction before failing loudly.
    3. Record reproducibility metadata (prompt_version + model_name +
       model_version echoed by the API) alongside the parsed result.
    4. Fail LOUDLY (typed GeminiCallError) so callers can route to their
       audit-logged failure branch — never return a silent partial result.

SDK surface used (verified against googleapis/python-genai v1.33 docs):
    genai.Client(api_key=...)
    client.models.generate_content(model=..., contents=..., config=...)
    types.GenerateContentConfig(system_instruction, temperature,
        response_mime_type, response_schema, max_output_tokens)
    types.Part.from_bytes(data=..., mime_type=...)
    response.text
    errors.APIError(.code, .message)
    types.HttpOptions(timeout=<ms>)

ASSUMPTION (flagged per anti-hallucination rule): response.model_version and
response.response_id are read via getattr() with a None fallback. They are
documented as fields of GenerateContentResponse but are accessed defensively
so a change in SDK response shape cannot crash a compliance run.
"""

from __future__ import annotations

import json
import logging
import os
import random
import re
import time
from dataclasses import dataclass, field
from typing import Any

from google import genai
from google.genai import errors, types

logger = logging.getLogger("cg.gemini")

# HTTP status codes worth retrying (transient server / rate-limit conditions).
_RETRYABLE_CODES = frozenset({429, 500, 502, 503, 504})

# Markdown code-fence stripper for models that wrap JSON in ```json ... ```.
_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)


class GeminiCallError(RuntimeError):
    """Raised when a Gemini call cannot produce valid JSON after all retries."""


class GeminiConfigError(RuntimeError):
    """Raised when the client is misconfigured (e.g. missing API key)."""


@dataclass(frozen=True)
class GeminiResult:
    """Parsed, validated result plus reproducibility metadata."""

    data: dict[str, Any]
    prompt_version: str
    model_name: str
    model_version: str | None
    response_id: str | None
    raw_text: str
    attempts: int


@dataclass
class RetryPolicy:
    max_attempts: int = 4
    base_delay_seconds: float = 1.0
    max_delay_seconds: float = 20.0
    jitter: bool = True

    def delay_for(self, attempt: int) -> float:
        raw = min(self.base_delay_seconds * (2 ** (attempt - 1)), self.max_delay_seconds)
        if self.jitter:
            raw = raw * (0.5 + random.random() / 2.0)  # 50–100% of computed delay
        return raw


@dataclass
class GeminiClient:
    """Thin, retrying, JSON-enforcing wrapper over google-genai.

    Construct once per process. Thread-safe for concurrent generate_json calls
    because it holds no per-call mutable state (the underlying genai.Client is
    safe to share).
    """

    model_name: str = field(default_factory=lambda: os.environ.get("GEMINI_MODEL", "gemini-2.5-flash"))
    api_key: str | None = None
    request_timeout_ms: int = 60_000
    retry: RetryPolicy = field(default_factory=RetryPolicy)
    _client: genai.Client = field(init=False, repr=False)

    def __post_init__(self) -> None:
        key = self.api_key or os.environ.get("GEMINI_API_KEY")
        if not key:
            raise GeminiConfigError(
                "GEMINI_API_KEY is not set. Provide it via env var or GeminiClient(api_key=...)."
            )
        self._client = genai.Client(
            api_key=key,
            http_options=types.HttpOptions(timeout=self.request_timeout_ms),
        )

    # -- public API ---------------------------------------------------------

    def generate_json(
        self,
        *,
        prompt_version: str,
        system_instruction: str,
        user_content: str,
        file_bytes: bytes | None = None,
        file_mime_type: str | None = None,
        response_schema: Any | None = None,
        temperature: float = 0.0,
        max_output_tokens: int | None = None,
    ) -> GeminiResult:
        """Run a strict-JSON generation with retries + one JSON-repair pass.

        Returns a GeminiResult whose .data is a parsed dict. Raises
        GeminiCallError if a valid JSON object cannot be obtained.
        """
        contents = self._build_contents(user_content, file_bytes, file_mime_type)
        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=temperature,
            response_mime_type="application/json",
            **({"response_schema": response_schema} if response_schema is not None else {}),
            **({"max_output_tokens": max_output_tokens} if max_output_tokens else {}),
        )

        last_error: Exception | None = None
        total_attempts = 0

        for attempt in range(1, self.retry.max_attempts + 1):
            total_attempts = attempt
            try:
                response = self._client.models.generate_content(
                    model=self.model_name,
                    contents=contents,
                    config=config,
                )
            except errors.APIError as exc:
                last_error = exc
                code = getattr(exc, "code", None)
                if code in _RETRYABLE_CODES and attempt < self.retry.max_attempts:
                    delay = self.retry.delay_for(attempt)
                    logger.warning(
                        "Gemini APIError code=%s (attempt %d/%d), retrying in %.1fs: %s",
                        code, attempt, self.retry.max_attempts, delay, getattr(exc, "message", exc),
                    )
                    time.sleep(delay)
                    continue
                # Non-retryable (e.g. 400/403/404) or out of attempts.
                raise GeminiCallError(
                    f"Gemini call failed (code={code}, prompt={prompt_version}): "
                    f"{getattr(exc, 'message', exc)}"
                ) from exc

            raw_text = response.text or ""
            parsed = self._try_parse_json(raw_text)
            if parsed is not None:
                return GeminiResult(
                    data=parsed,
                    prompt_version=prompt_version,
                    model_name=self.model_name,
                    # ASSUMPTION: defensive getattr — see module docstring.
                    model_version=getattr(response, "model_version", None),
                    response_id=getattr(response, "response_id", None),
                    raw_text=raw_text,
                    attempts=total_attempts,
                )

            # Valid HTTP response but invalid JSON: attempt one targeted repair.
            logger.warning(
                "Gemini returned non-JSON (attempt %d/%d, prompt=%s); requesting repair",
                attempt, self.retry.max_attempts, prompt_version,
            )
            last_error = GeminiCallError(f"non-JSON response: {raw_text[:200]!r}")
            if attempt < self.retry.max_attempts:
                contents = self._build_contents(
                    self._repair_instruction(raw_text), None, None
                )
                continue

        raise GeminiCallError(
            f"Gemini call for prompt {prompt_version} failed to yield valid JSON "
            f"after {self.retry.max_attempts} attempts: {last_error}"
        )

    # -- internals ----------------------------------------------------------

    @staticmethod
    def _build_contents(
        user_content: str, file_bytes: bytes | None, file_mime_type: str | None
    ) -> list[Any]:
        parts: list[Any] = [user_content]
        if file_bytes is not None:
            if not file_mime_type:
                raise ValueError("file_mime_type is required when file_bytes is provided")
            parts.append(types.Part.from_bytes(data=file_bytes, mime_type=file_mime_type))
        return parts

    @staticmethod
    def _try_parse_json(text: str) -> dict[str, Any] | None:
        if not text or not text.strip():
            return None
        cleaned = _FENCE_RE.sub("", text.strip())
        try:
            value = json.loads(cleaned)
        except json.JSONDecodeError:
            # Last resort: extract the outermost {...} span.
            start, end = cleaned.find("{"), cleaned.rfind("}")
            if start == -1 or end == -1 or end <= start:
                return None
            try:
                value = json.loads(cleaned[start : end + 1])
            except json.JSONDecodeError:
                return None
        return value if isinstance(value, dict) else None

    @staticmethod
    def _repair_instruction(bad_text: str) -> str:
        return (
            "Your previous response was not valid JSON. Return ONLY a single valid "
            "JSON object, with no markdown fences, no commentary, and no leading or "
            "trailing text. Here was your previous invalid output to correct:\n\n"
            f"{bad_text[:4000]}"
        )
