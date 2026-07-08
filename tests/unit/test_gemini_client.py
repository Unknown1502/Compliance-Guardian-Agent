"""Unit tests: Gemini client wrapper — JSON handling, retry, repair, failures.

The underlying google-genai Client is patched at gemini_client.genai.Client, so
no network calls occur. Uses the documented response shape (response.text) and
error type (errors.APIError).
"""

from __future__ import annotations

import pytest

import gemini_client
from gemini_client import GeminiCallError, GeminiClient, GeminiConfigError, RetryPolicy


class FakeResponse:
    def __init__(self, text: str, model_version: str = "mv-1", response_id: str = "rid-1"):
        self.text = text
        self.model_version = model_version
        self.response_id = response_id


class FakeAPIError(gemini_client.errors.APIError):
    """Subclass so isinstance(errors.APIError) holds; bypass base __init__."""

    def __init__(self, code: int, message: str):  # noqa: D107
        self.code = code
        self.message = message


class FakeModels:
    def __init__(self, script: list):
        self._script = list(script)
        self.calls = 0

    def generate_content(self, **kwargs):
        self.calls += 1
        item = self._script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class FakeGenaiClient:
    def __init__(self, script: list, **kwargs):
        self.models = FakeModels(script)


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(gemini_client.time, "sleep", lambda *_: None)


def _make_client(monkeypatch, script: list) -> GeminiClient:
    holder = {}

    def factory(**kwargs):
        client = FakeGenaiClient(script)
        holder["client"] = client
        return client

    monkeypatch.setattr(gemini_client.genai, "Client", factory)
    gc = GeminiClient(api_key="test-key", retry=RetryPolicy(max_attempts=4, base_delay_seconds=0.01))
    gc._fake = holder  # type: ignore[attr-defined]
    return gc


class TestConfig:
    def test_missing_api_key_raises(self, monkeypatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.setattr(gemini_client.genai, "Client", lambda **k: FakeGenaiClient([]))
        with pytest.raises(GeminiConfigError):
            GeminiClient(api_key=None)


class TestJsonHandling:
    def test_clean_json_parsed(self, monkeypatch):
        gc = _make_client(monkeypatch, [FakeResponse('{"a": 1, "b": "x"}')])
        result = gc.generate_json(
            prompt_version="p_v1", system_instruction="sys", user_content="hi"
        )
        assert result.data == {"a": 1, "b": "x"}
        assert result.prompt_version == "p_v1"
        assert result.model_version == "mv-1"
        assert result.response_id == "rid-1"
        assert result.attempts == 1

    def test_markdown_fenced_json_parsed(self, monkeypatch):
        gc = _make_client(monkeypatch, [FakeResponse('```json\n{"ok": true}\n```')])
        result = gc.generate_json(
            prompt_version="p_v1", system_instruction="s", user_content="c"
        )
        assert result.data == {"ok": True}

    def test_embedded_json_span_extracted(self, monkeypatch):
        gc = _make_client(
            monkeypatch, [FakeResponse('Sure! Here you go: {"x": 5} — hope that helps')]
        )
        result = gc.generate_json(
            prompt_version="p_v1", system_instruction="s", user_content="c"
        )
        assert result.data == {"x": 5}

    def test_non_json_then_repair_succeeds(self, monkeypatch):
        gc = _make_client(
            monkeypatch,
            [FakeResponse("I cannot do that."), FakeResponse('{"fixed": 1}')],
        )
        result = gc.generate_json(
            prompt_version="p_v1", system_instruction="s", user_content="c"
        )
        assert result.data == {"fixed": 1}
        assert result.attempts == 2

    def test_all_non_json_raises(self, monkeypatch):
        gc = _make_client(
            monkeypatch,
            [FakeResponse("nope"), FakeResponse("still nope"),
             FakeResponse("nada"), FakeResponse("no json")],
        )
        with pytest.raises(GeminiCallError):
            gc.generate_json(prompt_version="p_v1", system_instruction="s", user_content="c")


class TestRetry:
    def test_retryable_error_then_success(self, monkeypatch):
        gc = _make_client(
            monkeypatch,
            [FakeAPIError(503, "unavailable"), FakeResponse('{"ok": 1}')],
        )
        result = gc.generate_json(
            prompt_version="p_v1", system_instruction="s", user_content="c"
        )
        assert result.data == {"ok": 1}
        assert result.attempts == 2

    def test_non_retryable_error_raises_immediately(self, monkeypatch):
        gc = _make_client(monkeypatch, [FakeAPIError(400, "bad request"), FakeResponse("{}")])
        with pytest.raises(GeminiCallError):
            gc.generate_json(prompt_version="p_v1", system_instruction="s", user_content="c")
        # Only one call made — no retry on 400.
        assert gc._fake["client"].models.calls == 1  # type: ignore[attr-defined]

    def test_exhausts_retryable_errors(self, monkeypatch):
        gc = _make_client(
            monkeypatch,
            [FakeAPIError(500, "err")] * 4,
        )
        with pytest.raises(GeminiCallError):
            gc.generate_json(prompt_version="p_v1", system_instruction="s", user_content="c")
        assert gc._fake["client"].models.calls == 4  # type: ignore[attr-defined]
