"""Tests for graphify/audit.py — Phase 5 / Task 5.2."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pytest

from graphify import audit
from graphify.audit import (
    AuditLogError,
    log_event,
    log_security_event,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def workdir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Run each test in an isolated cwd. Reset the warn-once cache so the
    'first occurrence' stderr behavior is observable per-test.
    """
    monkeypatch.chdir(tmp_path)
    audit._warned_keys.clear()
    return tmp_path


def _read_log(workdir: Path) -> list[dict]:
    log = workdir / "graphify-out" / ".audit.log"
    return [json.loads(line) for line in log.read_text().splitlines() if line]


# ---------------------------------------------------------------------------
# log_event — best-effort
# ---------------------------------------------------------------------------

def test_log_event_writes_valid_jsonl_line(workdir, capsys):
    log_event("fetch_url", "https://example.com/", "success",
              {"status_code": 200, "bytes": 1234})
    records = _read_log(workdir)
    assert len(records) == 1
    rec = records[0]
    assert rec["action"] == "fetch_url"
    assert rec["target"] == "https://example.com/"
    assert rec["result"] == "success"
    assert rec["severity"] == "info"
    assert rec["details"] == {"status_code": 200, "bytes": 1234}
    assert "T" in rec["ts"]  # ISO 8601


def test_log_event_swallows_write_failure(workdir, capsys):
    # Replace graphify-out with a regular file so .audit.log creation
    # fails on mkdir/open.
    (workdir / "graphify-out").write_text("blocker")
    log_event("fetch_url", "https://example.com/", "success")  # must not raise
    err = capsys.readouterr().err
    assert "audit log unavailable" in err


def test_log_event_does_not_swallow_keyboard_interrupt(workdir, monkeypatch):
    def boom(*a, **kw):
        raise KeyboardInterrupt
    monkeypatch.setattr(audit, "_append_record", boom)
    with pytest.raises(KeyboardInterrupt):
        log_event("fetch_url", "https://example.com/", "success")


# ---------------------------------------------------------------------------
# log_security_event — fail-loud
# ---------------------------------------------------------------------------

def test_log_security_event_writes_valid_jsonl_line(workdir):
    log_security_event(
        "clone_repo", "https://github.com/o/r", "success",
        {"host": "github.com", "owner": "o", "repo": "r",
         "dest": "/tmp/r", "duration_s": 1.5},
    )
    records = _read_log(workdir)
    assert len(records) == 1
    assert records[0]["severity"] == "security"
    assert records[0]["details"]["owner"] == "o"


def test_log_security_event_stderr_fallback_when_file_write_fails(
    workdir, capsys
):
    # Acceptance criterion from the plan: replace .audit.log with a
    # directory and the call must surface the failure rather than
    # silently dropping the event.
    log_dir = workdir / "graphify-out"
    log_dir.mkdir()
    (log_dir / ".audit.log").mkdir()  # log path is now a directory

    log_security_event("fetch_url", "https://example.com/", "error",
                       {"status_code": 500})
    err = capsys.readouterr().err
    assert "AUDIT FAILURE" in err
    assert "security event not persisted" in err
    # The full record payload is in the stderr line so an operator
    # tailing stderr loses no information vs the on-disk log.
    assert '"action":"fetch_url"' in err
    assert '"severity":"security"' in err


def test_log_security_event_raises_when_stderr_also_fails(
    workdir, monkeypatch
):
    log_dir = workdir / "graphify-out"
    log_dir.mkdir()
    (log_dir / ".audit.log").mkdir()  # force file write to fail

    def stderr_boom(*a, **kw):
        raise OSError("stderr broken")

    monkeypatch.setattr(sys.stderr, "write", stderr_boom)

    with pytest.raises(AuditLogError) as exc_info:
        log_security_event("fetch_url", "https://example.com/", "error")

    msg = str(exc_info.value)
    assert "audit log write failed" in msg
    assert "stderr fallback also failed" in msg
    # Critical: the in-flight exception must NOT auto-chain via __context__.
    # That's the same lesson as the API-key scrubbing in llm.py — a
    # chain-walking logger could otherwise see the original failure.
    assert exc_info.value.__context__ is None
    assert exc_info.value.__cause__ is None


# ---------------------------------------------------------------------------
# Allowlist — disallowed keys are dropped, warning fires once
# ---------------------------------------------------------------------------

def test_disallowed_keys_are_dropped(workdir, capsys):
    log_security_event(
        "fetch_url", "https://example.com/", "success",
        {"status_code": 200, "extra_secret": "should-be-dropped"},
    )
    rec = _read_log(workdir)[0]
    assert rec["details"] == {"status_code": 200}
    err = capsys.readouterr().err
    assert "extra_secret" in err
    assert "fetch_url" in err


def test_disallowed_key_warning_fires_once_per_process(workdir, capsys):
    for _ in range(5):
        log_security_event(
            "fetch_url", "https://example.com/", "success",
            {"extra_secret": "x"},
        )
    err = capsys.readouterr().err
    # Exactly one warning line for the (action, key) pair, regardless of
    # how many times it was hit.
    assert err.count("dropping disallowed details key 'extra_secret'") == 1


def test_disallowed_keys_for_different_actions_warn_separately(
    workdir, capsys
):
    log_security_event("fetch_url", "u", "success", {"weird": "x"})
    log_security_event(
        "clone_repo", "u", "success",
        {"host": "h", "owner": "o", "repo": "r",
         "dest": "d", "duration_s": 0, "weird": "x"},
    )
    err = capsys.readouterr().err
    assert err.count("dropping disallowed details key 'weird'") == 2


# ---------------------------------------------------------------------------
# Denylist — secret scrubbing
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("secret", [
    "Bearer abc123def456",
    "sk-1234567890abcdefghij1234567890",            # 30+ chars after sk-
    "sk-ant-api03-abcdef1234567890",
    "ghp_1234567890abcdef1234567890abcdef1234",     # 36 chars after gh[ps]_
    "ghs_1234567890abcdef1234567890abcdef1234",
    "AKIAIOSFODNN7EXAMPLE_AKIAIOSFODNN7EXAMPLE",    # generic 32+ alnum
])
def test_secret_denylist_redacts(workdir, secret):
    log_security_event(
        "fetch_url",
        f"https://example.com/?token={secret}",
        "success",
        {"content_type": f"text/plain; junk={secret}"},
    )
    rec = _read_log(workdir)[0]
    assert secret not in rec["target"]
    assert secret not in rec["details"]["content_type"]
    assert "[REDACTED]" in rec["target"]
    assert "[REDACTED]" in rec["details"]["content_type"]


def test_redaction_is_substring_not_whole_value(workdir):
    # A token embedded in a longer string should lose just the token
    # span, not the whole string. Operators want the surrounding context.
    log_security_event(
        "fetch_url", "https://example.com/", "error",
        {"content_type": "401 Unauthorized: Bearer xyzabc123 (cached)"},
    )
    rec = _read_log(workdir)[0]
    ct = rec["details"]["content_type"]
    assert "401 Unauthorized" in ct
    assert "(cached)" in ct
    assert "[REDACTED]" in ct
    assert "xyzabc123" not in ct


def test_sha_carveout_preserves_cache_integrity_hashes(workdir):
    sha = "a" * 64  # 64 lowercase hex would match the generic 32+ pattern
    log_security_event(
        "cache_integrity_failure", "/cache/abc", "error",
        {"cache_key": "abc", "expected_sha": sha, "actual_sha": "b" * 64},
    )
    rec = _read_log(workdir)[0]
    assert rec["details"]["expected_sha"] == sha
    assert rec["details"]["actual_sha"] == "b" * 64


def test_sha_carveout_does_not_exempt_specific_patterns(workdir):
    # An Anthropic key smuggled into expected_sha (impossible in
    # practice — but we don't trust callers) must still be scrubbed.
    log_security_event(
        "cache_integrity_failure", "/cache/abc", "error",
        {"expected_sha": "sk-ant-api03-malicious_payload_xyz"},
    )
    rec = _read_log(workdir)[0]
    assert "sk-ant" not in rec["details"]["expected_sha"]
    assert "[REDACTED]" in rec["details"]["expected_sha"]


def test_target_field_is_also_scrubbed(workdir):
    log_security_event(
        "fetch_url",
        "https://api.example.com/?Bearer abcdef1234567890",
        "success",
        {"status_code": 200},
    )
    rec = _read_log(workdir)[0]
    assert "Bearer" not in rec["target"]
    assert "[REDACTED]" in rec["target"]


def test_recursive_scrub_into_nested_lists_and_dicts(workdir):
    log_security_event(
        "quarantine_flagged",
        "node:42",
        "warning",
        {
            "node_id": "n42",
            "matched_patterns": ["imperative_ignore", "Bearer abc1234567890_xyz"],
            "provenance": ["src/a.py", "Bearer secret_zzzzzzzz_in_a_path"],
        },
    )
    rec = _read_log(workdir)[0]
    serialized = json.dumps(rec)
    assert "Bearer abc" not in serialized
    assert "Bearer secret" not in serialized
    assert serialized.count("[REDACTED]") >= 2


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def test_unknown_action_raises(workdir):
    with pytest.raises(ValueError, match="unknown audit action"):
        log_security_event("not_an_action", "x", "success")


def test_invalid_result_raises(workdir):
    with pytest.raises(ValueError, match="invalid audit result"):
        log_security_event("fetch_url", "x", "ok")


def test_action_registry_matches_documented_set():
    # If you add a new action without updating the doc, this fails.
    # Doc-side counterpart is docs/AUDIT_LOG.md; we don't parse the doc
    # here, but we lock the registry's keys so a forgotten doc update is
    # surfaced by review of this test rather than by a silent shipping.
    expected = {
        "fetch_url", "clone_repo",
        "install_skill", "install_hook",
        "uninstall_skill", "uninstall_hook",
        "subprocess", "cache_integrity_failure",
        "quarantine_flagged", "content_type_violation",
    }
    assert set(audit._ACTION_ALLOWLIST.keys()) == expected


# ---------------------------------------------------------------------------
# File permissions
# ---------------------------------------------------------------------------

@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")
def test_file_permissions_are_0o600_after_first_write(workdir):
    log_security_event("fetch_url", "u", "success")
    log_path = workdir / "graphify-out" / ".audit.log"
    mode = log_path.stat().st_mode & 0o777
    assert mode == 0o600


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")
def test_pre_existing_loose_perms_are_tightened(workdir):
    log_dir = workdir / "graphify-out"
    log_dir.mkdir()
    log_path = log_dir / ".audit.log"
    log_path.write_text("")
    log_path.chmod(0o644)  # group/world readable

    log_security_event("fetch_url", "u", "success")
    mode = log_path.stat().st_mode & 0o777
    assert mode == 0o600


# ---------------------------------------------------------------------------
# Multi-process append safety (the load-bearing test for flock)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(sys.platform == "win32", reason="flock is Unix-only")
def test_multiprocess_append_no_interleaving(workdir):
    """10 worker processes × 100 events each = 1000 valid JSON lines.

    Without flock, buffered IO under contention interleaves bytes
    inside individual records and json.loads fails on at least some
    lines. With flock, every line round-trips.
    """
    repo_root = Path(__file__).resolve().parent.parent
    worker_script = (
        "import os, sys\n"
        "sys.path.insert(0, sys.argv[1])\n"
        "from graphify.audit import log_security_event\n"
        "worker_id = sys.argv[2]\n"
        "for i in range(100):\n"
        "    log_security_event(\n"
        "        'clone_repo',\n"
        "        f'https://h/{worker_id}/{i}',\n"
        "        'success',\n"
        "        {'host': 'h', 'owner': worker_id, 'repo': str(i),\n"
        "         'dest': '/' + worker_id + '/' + str(i),\n"
        "         'duration_s': 0.001 * i},\n"
        "    )\n"
    )

    def run_worker(worker_id: str) -> int:
        result = subprocess.run(
            [sys.executable, "-c", worker_script, str(repo_root), worker_id],
            cwd=workdir,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0, (
            f"worker {worker_id} failed: {result.stderr}"
        )
        return result.returncode

    # Use threads to launch processes in parallel — the contention happens
    # in the kernel between the spawned processes, not in the test driver.
    with ThreadPoolExecutor(max_workers=10) as ex:
        futures = [ex.submit(run_worker, str(i)) for i in range(10)]
        for f in as_completed(futures):
            assert f.result() == 0

    log_path = workdir / "graphify-out" / ".audit.log"
    lines = log_path.read_text().splitlines()
    assert len(lines) == 1000

    # Every line must parse as JSON. This is the truncation/interleaving
    # canary — corrupted append produces invalid JSON.
    seen_pairs: set[tuple[str, str]] = set()
    for line in lines:
        rec = json.loads(line)
        assert rec["action"] == "clone_repo"
        assert rec["severity"] == "security"
        seen_pairs.add((rec["details"]["owner"], rec["details"]["repo"]))

    # Every (worker_id, repo_id) pair appears exactly once — no records
    # were lost or duplicated.
    expected_pairs = {(str(w), str(i)) for w in range(10) for i in range(100)}
    assert seen_pairs == expected_pairs
