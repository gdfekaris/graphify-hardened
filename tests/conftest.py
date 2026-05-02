"""Test isolation hooks shared across the suite."""
from __future__ import annotations

import json
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def audit_log_path(tmp_path_factory, monkeypatch):
    """Redirect the audit log to a per-test tmp file and return the path.

    Phase 5 wired log_security_event into many call sites — safe_fetch,
    install/uninstall, _clone_repo, build's quarantine path. Without
    this fixture every test that exercises any of those would create a
    real graphify-out/.audit.log in the developer's working tree.

    Tests that need to drive _log_path's normal cwd-based resolution
    (notably tests/test_audit.py) explicitly delenv the override in
    their own fixtures.

    The fixture returns the path so wiring tests can read it back to
    assert that events were emitted. The autouse-ness means tests that
    don't care about audit still get isolation for free.
    """
    audit_dir = tmp_path_factory.mktemp("audit", numbered=True)
    path = audit_dir / "audit.log"
    monkeypatch.setenv("GRAPHIFY_AUDIT_LOG_PATH", str(path))
    return path


@pytest.fixture
def read_audit(audit_log_path):
    """Return a callable that parses the audit log to a list of records."""
    def _read() -> list[dict]:
        if not audit_log_path.exists():
            return []
        return [
            json.loads(line)
            for line in audit_log_path.read_text().splitlines()
            if line
        ]
    return _read
