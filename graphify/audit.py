# Audit logger — Phase 5 / Task 5.2.
#
# Two functions, two failure semantics:
#   - log_event:           best-effort, swallows write failures (info events)
#   - log_security_event:  fail-loud, raises AuditLogError if both file
#                          write AND stderr fallback fail (security events)
#
# Format and field allowlist are defined in docs/AUDIT_LOG.md. Adding a
# new action requires updating both that doc AND _ACTION_ALLOWLIST below;
# unknown action names are rejected at the API surface.
from __future__ import annotations

import json
import os
import re
import sys
import threading
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import fcntl  # Unix only
except ImportError:  # pragma: no cover — Windows fallback
    fcntl = None  # type: ignore[assignment]


_FILE_MODE = 0o600
_AUDIT_DIR_NAME = "graphify-out"
_AUDIT_FILE_NAME = ".audit.log"


class AuditLogError(Exception):
    """Both file write and stderr fallback failed for a security event.

    Callers of log_security_event must propagate this — do not swallow.
    Letting it bubble is the fail-loud contract.
    """


# ---------------------------------------------------------------------------
# Action registry
# ---------------------------------------------------------------------------
# Every key here is also documented in docs/AUDIT_LOG.md. The two MUST
# stay in sync; the doc is the human-readable spec, this dict is the
# enforcement point.

_ACTION_ALLOWLIST: dict[str, frozenset[str]] = {
    "fetch_url": frozenset(
        {"status_code", "bytes", "content_type", "redirect_chain"}
    ),
    "clone_repo": frozenset(
        {"host", "owner", "repo", "dest", "duration_s"}
    ),
    "install_skill":   frozenset({"platform", "paths_modified"}),
    "install_hook":    frozenset({"platform", "paths_modified"}),
    "uninstall_skill": frozenset({"platform", "paths_modified"}),
    "uninstall_hook":  frozenset({"platform", "paths_modified"}),
    "subprocess": frozenset(
        {"binary", "argv_redacted", "exit_code",
         "duration_s", "stdout_bytes", "stderr_bytes"}
    ),
    "cache_integrity_failure": frozenset(
        {"cache_key", "expected_sha", "actual_sha"}
    ),
    "quarantine_flagged": frozenset(
        {"node_id", "matched_patterns", "provenance"}
    ),
    "content_type_violation": frozenset({"url", "expected", "received"}),
}

_ALLOWED_RESULTS = frozenset({"success", "error", "warning"})


# ---------------------------------------------------------------------------
# Secret denylist
# ---------------------------------------------------------------------------
# Substring replacement via re.sub: a value like
#   "401 Unauthorized: Bearer sk-abc..."
# loses just the token span, not the surrounding context. The four
# specific patterns always fire; the generic [A-Za-z0-9_-]{32,} pattern
# is bypassed for the carve-out keys (cache_integrity_failure SHAs).

_DENY_PATTERNS_SPECIFIC: tuple[re.Pattern[str], ...] = (
    re.compile(r"Bearer\s+[A-Za-z0-9._-]+"),
    re.compile(r"sk-ant-[A-Za-z0-9_-]+"),
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"gh[ps]_[A-Za-z0-9]{36}"),
)
_DENY_PATTERN_GENERIC: re.Pattern[str] = re.compile(r"[A-Za-z0-9_-]{32,}")
_REDACTION = "[REDACTED]"

# Per-key carve-out from the GENERIC pattern only. The four specific
# patterns above still apply: an Anthropic key smuggled into expected_sha
# (impossible in practice, but we don't trust callers) is still scrubbed.
_GENERIC_CARVEOUT_KEYS = frozenset({"expected_sha", "actual_sha"})


# ---------------------------------------------------------------------------
# Per-process state for the warn-once-per-(action,key) policy
# ---------------------------------------------------------------------------

_warned_keys: set[tuple[str, str]] = set()
_warn_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def log_event(
    action: str,
    target: str,
    result: str,
    details: Mapping[str, Any] | None = None,
) -> None:
    """Best-effort logger for routine events (severity: info).

    Catches Exception (NOT BaseException — KeyboardInterrupt and
    SystemExit still propagate) and surfaces failures on stderr.
    Never raises. Reserved for non-security operational events; the
    plan currently mandates no callers, so this exists for future use.
    """
    try:
        record = _build_record(action, target, result, "info", details)
        _append_record(_log_path(), record)
    except Exception as e:  # noqa: BLE001 — see docstring
        try:
            sys.stderr.write(f"[audit log unavailable: {e}]\n")
        except Exception:
            pass


def log_security_event(
    action: str,
    target: str,
    result: str,
    details: Mapping[str, Any] | None = None,
) -> None:
    """Fail-loud logger for security-relevant events (severity: security).

    On file-write failure: serialize the full record to stderr, prefixed
    `[AUDIT FAILURE — security event not persisted: <reason>]` so an
    operator tailing stderr loses no information. If stderr ALSO fails,
    raise AuditLogError. Callers must propagate.
    """
    record = _build_record(action, target, result, "security", details)

    try:
        _append_record(_log_path(), record)
        return
    except Exception as e:
        file_error = e
    # Falling out of the except block normally clears the active-exception
    # state, so a `raise` later in this function does NOT auto-attach
    # file_error via __context__ — same lesson as the API-key scrubbing
    # in llm.py (Task 4.10). `raise X from None` alone is insufficient:
    # it sets __suppress_context__ but __context__ is still populated.

    stderr_error: BaseException | None = None
    try:
        payload = json.dumps(record, separators=(",", ":"), sort_keys=True)
        sys.stderr.write(
            f"[AUDIT FAILURE — security event not persisted: {file_error}] "
            f"{payload}\n"
        )
        sys.stderr.flush()
    except Exception as e:
        stderr_error = e

    if stderr_error is not None:
        # Raised AFTER both except blocks have exited, so __context__
        # is None on the resulting AuditLogError.
        raise AuditLogError(
            f"audit log write failed ({file_error}); "
            f"stderr fallback also failed ({stderr_error})"
        )


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _log_path() -> Path:
    """Resolve the audit log path relative to the current working directory.

    Resolved at call time, not import time — tests change cwd, and so do
    real users when they `cd` into a project. No caching.
    """
    return Path.cwd() / _AUDIT_DIR_NAME / _AUDIT_FILE_NAME


def _build_record(
    action: str,
    target: str,
    result: str,
    severity: str,
    details: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if action not in _ACTION_ALLOWLIST:
        raise ValueError(f"unknown audit action: {action!r}")
    if result not in _ALLOWED_RESULTS:
        raise ValueError(f"invalid audit result: {result!r}")

    # Apply substring redaction to `target` too — a URL with an embedded
    # token in its query string would otherwise leak. Use key=None so
    # the generic pattern fires (target is never a SHA carve-out).
    safe_target = _scrub_string(str(target), key=None)

    sanitized = _sanitize_details(action, details or {})
    return {
        "ts": datetime.now(timezone.utc).isoformat(),
        "action": action,
        "target": safe_target,
        "result": result,
        "severity": severity,
        "details": sanitized,
    }


def _sanitize_details(
    action: str, details: Mapping[str, Any]
) -> dict[str, Any]:
    allowed = _ACTION_ALLOWLIST[action]
    out: dict[str, Any] = {}
    for k, v in details.items():
        if k not in allowed:
            _warn_dropped_key(action, k)
            continue
        out[k] = _scrub(v, key=k)
    return out


def _warn_dropped_key(action: str, key: str) -> None:
    pair = (action, key)
    with _warn_lock:
        if pair in _warned_keys:
            return
        _warned_keys.add(pair)
    try:
        sys.stderr.write(
            f"[graphify audit] dropping disallowed details key {key!r} "
            f"for action {action!r} (further occurrences silenced)\n"
        )
    except Exception:
        pass


def _scrub(value: Any, key: str | None) -> Any:
    """Recursively redact secrets from a details value.

    The `key` argument is the dict key the value sits directly under;
    when descending into a nested dict the inner key takes over, but
    when descending into a list/tuple the OUTER key carries down so
    that list elements under e.g. `expected_sha` (hypothetically) would
    still benefit from the carve-out. In practice none of the carve-out
    fields are list-shaped today, but the rule is the natural one.
    """
    if isinstance(value, str):
        return _scrub_string(value, key)
    if isinstance(value, Mapping):
        return {k: _scrub(v, key=k) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_scrub(v, key=key) for v in value]
    # Numbers, bool, None — pass through. Anything else (sets, custom
    # objects) is left to json.dumps to serialize or refuse; we do not
    # walk into them.
    return value


def _scrub_string(value: str, key: str | None) -> str:
    out = value
    for pat in _DENY_PATTERNS_SPECIFIC:
        out = pat.sub(_REDACTION, out)
    if key not in _GENERIC_CARVEOUT_KEYS:
        out = _DENY_PATTERN_GENERIC.sub(_REDACTION, out)
    return out


def _append_record(path: Path, record: dict[str, Any]) -> None:
    """Atomically append a single JSONL record.

    Uses os.write under flock so concurrent processes interleave whole
    records, never bytes. Buffered open() can split a write across
    syscalls under contention; os.write is one syscall per call, and
    POSIX guarantees O_APPEND atomicity for writes < PIPE_BUF on top
    of that. The flock is the load-bearing guarantee; the O_APPEND
    semantics are belt-and-suspenders for the Windows fallback path.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, separators=(",", ":"), sort_keys=True) + "\n"
    data = line.encode("utf-8")

    flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT
    fd = os.open(path, flags, _FILE_MODE)
    try:
        # The audit log is always 0o600. Idempotent chmod every write —
        # one extra syscall on a rare path is cheaper than reasoning
        # about which contact is "first" across processes. A user who
        # wants the file unwritable should rotate it out, not chmod it
        # in place; we'd just re-create at 0o600 anyway.
        try:
            os.chmod(path, _FILE_MODE)
        except OSError:
            pass

        if fcntl is not None:
            fcntl.flock(fd, fcntl.LOCK_EX)
            try:
                _write_all(fd, data)
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
        else:  # pragma: no cover — Windows
            _write_all(fd, data)
    finally:
        os.close(fd)


def _write_all(fd: int, data: bytes) -> None:
    """os.write may return short; loop until done. Still atomic from the
    perspective of other processes because we hold flock the whole time.
    """
    while data:
        n = os.write(fd, data)
        if n == 0:  # pragma: no cover — would mean kernel refuses progress
            raise OSError("os.write returned 0")
        data = data[n:]
