"""Regression tests for API-key handling in graphify.llm (Task 4.10).

The contract: an SDK exception whose text contains the API key value must
not propagate that value to the caller. The fix lives in `_redact_key` and
the try/except wrappers around the SDK calls in `_call_claude` and
`_call_openai_compat`.
"""
from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock, patch

import pytest

from graphify import llm
from graphify.llm import _redact_key, extract_files_direct


# ---------------------------------------------------------------------------
# _redact_key unit tests
# ---------------------------------------------------------------------------

def test_redact_key_replaces_when_key_present():
    key = "sk-ant-live-aaaaaaaabbbbbbbbcccccccc"
    exc = ValueError(f"Authentication failed for token {key} on /messages")
    result = _redact_key(exc, key)
    assert key not in str(result)
    assert "[REDACTED]" in str(result)
    assert isinstance(result, ValueError)


def test_redact_key_returns_unchanged_when_key_absent():
    exc = ValueError("rate limited; status 429")
    result = _redact_key(exc, "sk-ant-live-zzzzzzzz")
    assert result is exc


def test_redact_key_skips_short_keys():
    """The 8-char floor prevents pathological replacement on placeholders.

    A legitimate Anthropic / OpenAI key is well over 8 chars, so this
    floor cannot mask a real leak; it only stops `key='test'` from
    obliterating the word 'test' inside an unrelated error message.
    """
    exc = ValueError("test failure: something went wrong")
    assert _redact_key(exc, "test") is exc


def test_redact_key_skips_empty_key():
    exc = ValueError("anything")
    assert _redact_key(exc, "") is exc


def test_redact_key_falls_back_to_runtime_error_for_uncloneable():
    """Some SDK exceptions take many constructor args; we cannot rebuild
    them from a single message. The helper must still scrub the message,
    falling back to RuntimeError rather than letting the original through."""
    class WeirdException(Exception):
        def __init__(self, status: int, body: str) -> None:
            super().__init__(f"status={status} body={body}")
            self.status = status
            self.body = body

    key = "sk-ant-live-aaaaaaaabbbbbbbbcccccccc"
    exc = WeirdException(401, f"invalid api key {key}")
    result = _redact_key(exc, key)
    assert key not in str(result)
    assert "[REDACTED]" in str(result)
    # Fell back to RuntimeError because WeirdException cannot be constructed
    # from a single string argument.
    assert isinstance(result, RuntimeError)


# ---------------------------------------------------------------------------
# End-to-end: extract_files_direct must not leak the key on SDK error
# ---------------------------------------------------------------------------

@pytest.fixture
def long_fake_key():
    """A fake key that's long enough to clear the 8-char floor in _redact_key."""
    return "sk-ant-live-aaaaaaaabbbbbbbbcccccccc"


def _install_fake_anthropic_module(monkeypatch, exc_to_raise):
    """Stub `anthropic` so import succeeds and `.messages.create` raises."""
    fake = types.ModuleType("anthropic")

    class FakeAnthropic:
        def __init__(self, api_key=None, **_):
            self.api_key = api_key
            self.messages = MagicMock()
            self.messages.create = MagicMock(side_effect=exc_to_raise)

    fake.Anthropic = FakeAnthropic  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "anthropic", fake)


def _install_fake_openai_module(monkeypatch, exc_to_raise):
    fake = types.ModuleType("openai")

    class FakeOpenAI:
        def __init__(self, api_key=None, base_url=None, **_):
            self.api_key = api_key
            self.chat = types.SimpleNamespace(
                completions=MagicMock(create=MagicMock(side_effect=exc_to_raise))
            )

    fake.OpenAI = FakeOpenAI  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "openai", fake)


def test_claude_backend_does_not_leak_key_in_exception(tmp_path, monkeypatch, long_fake_key):
    """When the anthropic SDK raises with the key in its message, the key
    must be scrubbed before the exception propagates to the caller."""
    leaky = ValueError(f"401 Unauthorized — invalid API key {long_fake_key}")
    _install_fake_anthropic_module(monkeypatch, leaky)

    sample = tmp_path / "x.py"
    sample.write_text("def f(): pass\n")

    with pytest.raises(Exception) as excinfo:
        extract_files_direct(
            [sample], backend="claude", api_key=long_fake_key, root=tmp_path,
        )

    # Walk the entire exception chain — in case `from None` was forgotten,
    # the original message would still surface via __cause__ / __context__.
    err = excinfo.value
    seen: list[str] = []
    while err is not None:
        seen.append(str(err))
        err = err.__cause__ or err.__context__

    full = "\n".join(seen)
    assert long_fake_key not in full, (
        f"API key value leaked through exception chain: {full!r}"
    )
    assert "[REDACTED]" in str(excinfo.value)


def test_kimi_backend_does_not_leak_key_in_exception(tmp_path, monkeypatch, long_fake_key):
    """Same contract through the OpenAI-compatible code path."""
    leaky = RuntimeError(f"403 Forbidden — token {long_fake_key} disabled")
    _install_fake_openai_module(monkeypatch, leaky)

    sample = tmp_path / "x.py"
    sample.write_text("def f(): pass\n")

    with pytest.raises(Exception) as excinfo:
        extract_files_direct(
            [sample], backend="kimi", api_key=long_fake_key, root=tmp_path,
        )

    err = excinfo.value
    seen: list[str] = []
    while err is not None:
        seen.append(str(err))
        err = err.__cause__ or err.__context__

    full = "\n".join(seen)
    assert long_fake_key not in full
    assert "[REDACTED]" in str(excinfo.value)


def test_no_api_key_set_error_does_not_contain_a_key():
    """The `No API key for backend` ValueError refers to the env var name,
    not its value. Regression guard against accidental f-string changes."""
    import os
    real_anth = os.environ.pop("ANTHROPIC_API_KEY", None)
    real_moon = os.environ.pop("MOONSHOT_API_KEY", None)
    try:
        with pytest.raises(ValueError) as excinfo:
            extract_files_direct([], backend="claude", api_key=None)
        msg = str(excinfo.value)
        assert "ANTHROPIC_API_KEY" in msg
        assert "sk-" not in msg  # neither prefix nor secret
    finally:
        if real_anth is not None:
            os.environ["ANTHROPIC_API_KEY"] = real_anth
        if real_moon is not None:
            os.environ["MOONSHOT_API_KEY"] = real_moon
