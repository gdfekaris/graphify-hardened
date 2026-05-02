"""Phase 7.8: audit logger fail-loud and secret-scrubbing semantics.

Four scenarios mapped from the plan:

1. **Audit log path is a directory (file write fails), stderr works.**
   `log_security_event` falls back to stderr — the full record is
   surfaced to operators tailing stderr — and returns normally. No
   raise, no information loss. (This is the "everyone sees it
   somewhere" leg of the contract.)

2. **Audit log path is a directory AND stderr is broken.**
   `log_security_event` raises `AuditLogError`. The exception's
   `__context__` and `__cause__` must both be None — the implementation
   must capture the in-flight file-write failure, exit the except
   block, and re-raise outside, so a chain-walking logger doesn't see
   the original (potentially secret-bearing) error message.

3. **A wired-in security path under the same fail-loud condition
   aborts the operation.** `safe_fetch` is the canonical example: if
   the audit emit raises, the fetch must propagate rather than
   complete-and-return its bytes silently. The Phase 5.3 wiring
   guarantees this and Phase 7.8 reasserts it as part of the threat
   model.

4. **Field allowlist + secret denylist both fire on the same record.**
   A `details` dict carrying an `auth_header` key (not in the
   `fetch_url` action allowlist) AND a value that matches the
   `sk-…` OpenAI pattern: the disallowed key is dropped before the
   record is serialised, AND the secret value (if smuggled into an
   *allowed* key like `content_type`) is substring-redacted. Neither
   defence on its own carries the load; both must fire.

Most of these scenarios are also covered exhaustively in
``tests/test_audit.py`` (Phase 5.2) and ``tests/test_audit_wiring.py``
(Phase 5.3). The Phase 7 file restates the threat model in one place
so the suite is self-contained — deleting either of those files would
not erase the threat-model coverage.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from graphify import audit
from graphify.audit import AuditLogError, log_security_event


# ---------------------------------------------------------------------------
# Local fixture: real cwd-based audit log path (the conftest autouse fixture
# redirects via env var; these tests need the natural resolution).
# ---------------------------------------------------------------------------

@pytest.fixture
def workdir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.delenv("GRAPHIFY_AUDIT_LOG_PATH", raising=False)
    monkeypatch.chdir(tmp_path)
    # Reset the warn-once cache so each test sees first-occurrence stderr.
    audit._warned_keys.clear()
    return tmp_path


def _force_log_path_to_be_a_directory(workdir: Path) -> Path:
    """Replace `<cwd>/graphify-out/.audit.log` with a directory so file
    writes / O_APPEND opens against the path raise."""
    log_dir = workdir / "graphify-out"
    log_dir.mkdir()
    log_path = log_dir / ".audit.log"
    log_path.mkdir()
    return log_path


# ---------------------------------------------------------------------------
# Scenario 1 — file fails, stderr works -> fall back without raise.
# ---------------------------------------------------------------------------

def test_audit_log_directory_falls_back_to_stderr_without_raising(
    workdir, capsys,
):
    _force_log_path_to_be_a_directory(workdir)

    # Must not raise — stderr fallback succeeds.
    log_security_event(
        "fetch_url", "https://example.com/", "error", {"status_code": 503},
    )

    err = capsys.readouterr().err
    assert "AUDIT FAILURE" in err, (
        "stderr fallback line missing the [AUDIT FAILURE …] prefix that "
        "operators grep for"
    )
    assert "security event not persisted" in err
    # The full record must travel with the failure line — operators tailing
    # stderr should lose no forensic data versus reading the file.
    assert '"action":"fetch_url"' in err
    assert '"severity":"security"' in err
    assert '"status_code":503' in err


# ---------------------------------------------------------------------------
# Scenario 2 — file fails AND stderr fails -> AuditLogError, no exception
# chain leakage.
# ---------------------------------------------------------------------------

def test_both_file_and_stderr_failure_raises_audit_log_error(
    workdir, monkeypatch,
):
    _force_log_path_to_be_a_directory(workdir)

    def _stderr_boom(*_args, **_kwargs):
        raise OSError("stderr is broken in this test")

    monkeypatch.setattr(sys.stderr, "write", _stderr_boom)

    with pytest.raises(AuditLogError) as exc_info:
        log_security_event(
            "fetch_url", "https://example.com/", "error", {"status_code": 503},
        )

    msg = str(exc_info.value)
    assert "audit log write failed" in msg
    assert "stderr fallback also failed" in msg

    # Load-bearing: the file-write OSError must NOT leak into the public
    # exception chain. The audit module's contract is "raise the
    # AuditLogError clean of context" — a chain-walking logger that
    # serialises __context__/__cause__ into structured logs could
    # otherwise reflect a secret in the original error message.
    assert exc_info.value.__context__ is None, (
        "AuditLogError leaked __context__ — the file-write exception is "
        "auto-attached and a chain-walking logger could see it"
    )
    assert exc_info.value.__cause__ is None


# ---------------------------------------------------------------------------
# Scenario 3 — wired-in security path aborts under the same condition.
# ---------------------------------------------------------------------------

def test_safe_fetch_aborts_when_audit_emit_raises_audit_log_error(
    workdir, monkeypatch,
):
    """Phase 5.3 wired log_security_event into safe_fetch's success and
    error paths. If the audit emit raises (file broken AND stderr
    broken), the fetch must propagate rather than complete-and-return
    silently — otherwise a hostile log-write failure could mask the
    forensic trail of a successful fetch.
    """
    _force_log_path_to_be_a_directory(workdir)

    def _stderr_boom(*_args, **_kwargs):
        raise OSError("stderr broken")

    monkeypatch.setattr(sys.stderr, "write", _stderr_boom)

    # Mock the network so the call doesn't hit the real internet —
    # we want the audit emit to be the failing layer, not DNS.
    from unittest.mock import MagicMock
    mock_resp = MagicMock()
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    mock_resp.status = 200
    mock_resp.code = 200
    mock_resp.headers = {"content-type": "text/html"}
    mock_resp.read.side_effect = [b"hello", b""]

    from graphify.security import safe_fetch
    with patch("graphify.security._build_opener") as mock_opener_fn:
        mock_opener = MagicMock()
        mock_opener.open.return_value = mock_resp
        mock_opener_fn.return_value = mock_opener

        # The fetch itself would succeed — but the audit emit fails loud,
        # propagating AuditLogError up through safe_fetch.
        with pytest.raises(AuditLogError):
            safe_fetch("https://example.com/")


# ---------------------------------------------------------------------------
# Scenario 4 — field allowlist + secret denylist double defence.
# ---------------------------------------------------------------------------

def test_disallowed_key_with_secret_value_is_double_redacted(
    workdir, capsys,
):
    """Both the field allowlist (drop unknown keys) and the secret
    denylist (substring-redact recognised tokens) must fire. Neither is
    the load-bearing defence on its own:

      - if the field allowlist were dropped and the secret value
        landed in `auth_header`, the substring redaction would still
        catch the sk-… pattern and the value would not appear verbatim;
      - if the secret denylist were dropped but the field allowlist
        held, the entry under `auth_header` would still be discarded
        before serialization, so the value would not be persisted.

    Either alone is a backstop, but defence in depth requires both.
    Verified by writing a record that exercises both layers and
    asserting nothing leaks.
    """
    smuggled_key = "sk-1234567890abcdef1234567890abcdef"

    log_security_event(
        "fetch_url",
        "https://example.com/",
        "error",
        {
            # Disallowed key for the fetch_url action: must be dropped.
            "auth_header": f"Bearer {smuggled_key}",
            # Allowed key but value contains an OpenAI-shaped token.
            # Must be substring-redacted in place.
            "content_type": f"text/html; api-key={smuggled_key}",
            # Plain allowed values to confirm the rest of the record
            # makes it through.
            "status_code": 401,
            "bytes": 0,
        },
    )

    log_path = workdir / "graphify-out" / ".audit.log"
    assert log_path.exists(), "audit log was not written"
    content = log_path.read_text(encoding="utf-8")

    # Defence #1: the disallowed key must not appear in the persisted
    # record at all (and the warn-once stderr line names it).
    assert "auth_header" not in content, (
        "field allowlist failed: disallowed key landed in the persisted log"
    )
    assert "auth_header" in capsys.readouterr().err, (
        "field allowlist must surface a warn-once stderr line naming the "
        "dropped key so operators see misuse"
    )

    # Defence #2: the secret value must not appear anywhere in the
    # serialised record — the substring redaction must catch it.
    assert smuggled_key not in content, (
        "secret denylist failed: sk-… value smuggled in an allowed field "
        "appears verbatim in the persisted log"
    )
    assert "[REDACTED]" in content, (
        "redaction marker missing from the record — substring scrub did "
        "not fire"
    )

    # The benign fields survive untouched so the record is still useful.
    assert '"status_code":401' in content
