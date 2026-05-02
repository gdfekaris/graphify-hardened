"""Tests for `graphify status` — Phase 5 / Task 5.4 (closes Task 3.7)."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest


@pytest.fixture
def project_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Run each status test in an isolated cwd. graphify-out/ is resolved
    relative to cwd, so chdir gives us a per-test sandbox.
    """
    monkeypatch.chdir(tmp_path)
    (tmp_path / "graphify-out").mkdir()
    return tmp_path


def _run_status(capsys, **kwargs) -> str:
    from graphify.__main__ import status
    status(**kwargs)
    return capsys.readouterr().out


# ---------------------------------------------------------------------------
# Empty state — no flagged.json, no graph, no audit events
# ---------------------------------------------------------------------------

def test_status_empty_state(project_dir, capsys):
    out = _run_status(capsys)
    assert "graphify status" in out
    assert "Flagged content: 0 records" in out
    assert "Graph mode: no graph.json" in out
    assert "Recent audit events: 0" in out
    assert "Installed skills:" in out


# ---------------------------------------------------------------------------
# Flagged content — count + recent 5 + original_text gated behind flag
# ---------------------------------------------------------------------------

def _write_flagged(project_dir: Path, n: int) -> None:
    flagged = project_dir / "graphify-out" / ".flagged.json"
    with flagged.open("w", encoding="utf-8") as f:
        for i in range(n):
            rec = {
                "node_id": f"n{i}",
                "field_name": "rationale",
                "original_text": f"hostile_text_{i}_DO_NOT_LEAK",
                "matched_patterns": ["imperative_ignore"],
                "provenance": [f"src/{i}.py"],
                "ts": f"2026-05-01T12:00:0{i}+00:00",
            }
            f.write(json.dumps(rec) + "\n")


def test_status_reports_flagged_count(project_dir, capsys):
    _write_flagged(project_dir, 3)
    out = _run_status(capsys)
    assert "Flagged content: 3 record(s)" in out
    assert "n0" in out
    assert "n1" in out
    assert "n2" in out
    assert "imperative_ignore" in out


def test_status_truncates_to_recent_5_when_many(project_dir, capsys):
    _write_flagged(project_dir, 12)
    out = _run_status(capsys)
    assert "Flagged content: 12 record(s)" in out
    # Only the last 5 (n7..n11) appear in the recent block.
    for i in range(7, 12):
        assert f"n{i}" in out
    # Older records are present in the count but not the recent list.
    assert "n0" not in out
    assert "n6" not in out


def test_status_omits_original_text_by_default(project_dir, capsys):
    _write_flagged(project_dir, 1)
    out = _run_status(capsys)
    assert "hostile_text_0_DO_NOT_LEAK" not in out
    assert "--show-flagged-text" in out  # hint shown


def test_status_shows_original_text_when_flag_passed(project_dir, capsys):
    _write_flagged(project_dir, 1)
    out = _run_status(capsys, show_flagged_text=True)
    assert "hostile_text_0_DO_NOT_LEAK" in out


def test_status_tolerates_malformed_flagged_lines(project_dir, capsys):
    flagged = project_dir / "graphify-out" / ".flagged.json"
    flagged.write_text(
        '{"node_id": "ok", "field_name": "x", "matched_patterns": [], '
        '"provenance": [], "ts": "t"}\n'
        'GARBAGE NOT JSON\n'
        '{"node_id": "ok2", "field_name": "x", "matched_patterns": [], '
        '"provenance": [], "ts": "t"}\n'
    )
    out = _run_status(capsys)
    # Two valid records survive; the GARBAGE line is silently dropped.
    assert "Flagged content: 2 record(s)" in out


# ---------------------------------------------------------------------------
# Graph build mode (cross-ref to Task 3.6)
# ---------------------------------------------------------------------------

def test_status_reports_standard_graph_mode(project_dir, capsys):
    graph = project_dir / "graphify-out" / "graph.json"
    graph.write_text(json.dumps({
        "graph": {},
        "nodes": [],
        "links": [],
        "directed": False,
        "multigraph": False,
    }))
    out = _run_status(capsys)
    assert "Graph mode: standard" in out


def test_status_reports_untrusted_corpus_mode(project_dir, capsys):
    graph = project_dir / "graphify-out" / "graph.json"
    graph.write_text(json.dumps({
        "graph": {"mode": "untrusted-corpus"},
        "nodes": [],
        "links": [],
        "directed": False,
        "multigraph": False,
    }))
    out = _run_status(capsys)
    assert "UNTRUSTED-CORPUS" in out


def test_status_handles_unreadable_graph(project_dir, capsys):
    graph = project_dir / "graphify-out" / "graph.json"
    graph.write_text("not json {{{")
    out = _run_status(capsys)
    assert "graph.json present but unreadable" in out


# ---------------------------------------------------------------------------
# Audit events
# ---------------------------------------------------------------------------

def test_status_reports_recent_audit_events(project_dir, capsys, monkeypatch):
    # Drop the conftest's GRAPHIFY_AUDIT_LOG_PATH so status reads the
    # cwd-based default (graphify-out/.audit.log).
    monkeypatch.delenv("GRAPHIFY_AUDIT_LOG_PATH", raising=False)
    audit = project_dir / "graphify-out" / ".audit.log"
    with audit.open("w", encoding="utf-8") as f:
        for i in range(3):
            f.write(json.dumps({
                "ts": f"2026-05-01T12:00:0{i}+00:00",
                "action": "fetch_url",
                "target": f"http://x/{i}",
                "result": "success",
                "severity": "security",
                "details": {},
            }) + "\n")
    out = _run_status(capsys)
    assert "Recent audit events (3 total" in out
    assert "fetch_url" in out
    assert "http://x/0" in out


def test_status_truncates_to_last_10_audit_events(project_dir, capsys, monkeypatch):
    monkeypatch.delenv("GRAPHIFY_AUDIT_LOG_PATH", raising=False)
    audit = project_dir / "graphify-out" / ".audit.log"
    with audit.open("w", encoding="utf-8") as f:
        for i in range(15):
            f.write(json.dumps({
                "ts": f"t{i}",
                "action": "fetch_url",
                "target": f"http://x/{i}",
                "result": "success",
                "severity": "security",
                "details": {},
            }) + "\n")
    out = _run_status(capsys)
    assert "15 total" in out
    # Last 10: indices 5..14 should appear, 0..4 should not.
    assert "http://x/5" in out
    assert "http://x/14" in out
    assert "http://x/0" not in out
    assert "http://x/4" not in out


def test_status_honors_audit_log_path_env_var(project_dir, capsys, tmp_path,
                                              monkeypatch):
    # Status uses graphify.audit._log_path which honors the env var, so
    # tests in environments where the conftest fixture has set the var
    # see the redirected log — this is the integration-with-conftest
    # check we couldn't make in the previous test.
    custom = tmp_path / "elsewhere.log"
    custom.write_text(json.dumps({
        "ts": "t1", "action": "clone_repo", "target": "https://x/r",
        "result": "success", "severity": "security", "details": {},
    }) + "\n")
    monkeypatch.setenv("GRAPHIFY_AUDIT_LOG_PATH", str(custom))
    out = _run_status(capsys)
    assert "clone_repo" in out
    assert "https://x/r" in out


# ---------------------------------------------------------------------------
# Skill installs and git hooks
# ---------------------------------------------------------------------------

def test_status_reports_no_skills_installed(project_dir, capsys, monkeypatch):
    # Point HOME at an empty tmp dir so the install probe finds nothing.
    fake_home = project_dir / "fake-home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setattr("pathlib.Path.home", lambda: fake_home)
    out = _run_status(capsys)
    # No real platform skill files exist under the empty home, so
    # "(none)" appears under Installed skills.
    assert "Installed skills:" in out
    # The "(none)" line is emitted only if zero installs are detected.
    # Any real platform install elsewhere on the dev machine would
    # break this assertion if HOME wasn't shimmed.
    assert "(none)" in out


def test_status_reports_skills_when_present(project_dir, capsys, monkeypatch):
    fake_home = project_dir / "fake-home"
    fake_home.mkdir()
    monkeypatch.setattr("pathlib.Path.home", lambda: fake_home)
    # Plant a fake claude skill install under the shimmed home.
    from graphify.__main__ import _PLATFORM_CONFIG
    skill_dst = fake_home / _PLATFORM_CONFIG["claude"]["skill_dst"]
    skill_dst.parent.mkdir(parents=True, exist_ok=True)
    skill_dst.write_text("fake skill")
    (skill_dst.parent / ".graphify_version").write_text("1.2.3")

    out = _run_status(capsys)
    assert "claude" in out
    assert "v1.2.3" in out


def test_status_handles_non_git_dir(project_dir, capsys):
    # No .git/ in the project, so hook status should report "Not in a
    # git repository." without crashing.
    out = _run_status(capsys)
    assert "Git hooks:" in out
    assert "Not in a git repository" in out
