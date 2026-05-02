"""--dry-run never modifies the filesystem.

For every install command:
- snapshot tmp_home + tmp_project filesystems
- run `<install command> --dry-run` against them
- snapshot again
- assert the snapshots are byte-identical

Also asserts that dry-run output contains the expected paths and uses
the CREATE / MODIFY / NO-OP markers from `graphify.install_plan`.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
from unittest.mock import patch

import pytest


def _snapshot(root: Path) -> dict[str, str]:
    """Recursive {relative path -> sha256} for every file under root."""
    out: dict[str, str] = {}
    for p in sorted(root.rglob("*")):
        if p.is_file():
            out[str(p.relative_to(root))] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def _run_with_isolated_fs(tmp_home: Path, tmp_project: Path, fn):
    """Mock HOME → tmp_home, chdir → tmp_project, run fn(), restore cwd."""
    cwd = os.getcwd()
    try:
        os.chdir(tmp_project)
        with patch("graphify.__main__.Path.home", return_value=tmp_home):
            fn()
    finally:
        os.chdir(cwd)


def _assert_no_fs_changes(tmp_home: Path, tmp_project: Path, fn):
    """Run fn() with isolated HOME and CWD; assert no files were created
    or modified in either tmp dir."""
    before_home = _snapshot(tmp_home)
    before_proj = _snapshot(tmp_project)
    _run_with_isolated_fs(tmp_home, tmp_project, fn)
    after_home = _snapshot(tmp_home)
    after_proj = _snapshot(tmp_project)
    assert before_home == after_home, f"HOME mutated: {set(after_home) - set(before_home)}"
    assert before_proj == after_proj, f"PROJECT mutated: {set(after_proj) - set(before_proj)}"


@pytest.fixture
def tmp_home_and_project(tmp_path):
    home = tmp_path / "home"
    proj = tmp_path / "proj"
    home.mkdir()
    proj.mkdir()
    return home, proj


# ── Top-level `graphify install --platform <P>` ──────────────────────────────

@pytest.mark.parametrize("p", [
    "claude", "codex", "opencode", "aider", "copilot", "claw", "droid",
    "trae", "trae-cn", "hermes", "kiro", "antigravity", "windows",
])
def test_top_level_install_dry_run_does_not_modify_fs(p, tmp_home_and_project):
    home, proj = tmp_home_and_project
    from graphify.__main__ import install
    _assert_no_fs_changes(home, proj, lambda: install(platform=p, dry_run=True))


# ── Subcommand installers ────────────────────────────────────────────────────

def test_claude_install_dry_run(tmp_home_and_project):
    home, proj = tmp_home_and_project
    from graphify.__main__ import claude_install
    _assert_no_fs_changes(home, proj, lambda: claude_install(proj, dry_run=True))


def test_gemini_install_dry_run(tmp_home_and_project):
    home, proj = tmp_home_and_project
    from graphify.__main__ import gemini_install
    _assert_no_fs_changes(home, proj, lambda: gemini_install(proj, dry_run=True))


def test_cursor_install_dry_run(tmp_home_and_project):
    home, proj = tmp_home_and_project
    from graphify.__main__ import _cursor_install
    _assert_no_fs_changes(home, proj, lambda: _cursor_install(proj, dry_run=True))


def test_vscode_install_dry_run(tmp_home_and_project):
    home, proj = tmp_home_and_project
    from graphify.__main__ import vscode_install
    _assert_no_fs_changes(home, proj, lambda: vscode_install(proj, dry_run=True))


def test_kiro_install_dry_run(tmp_home_and_project):
    home, proj = tmp_home_and_project
    from graphify.__main__ import _kiro_install
    _assert_no_fs_changes(home, proj, lambda: _kiro_install(proj, dry_run=True))


def test_antigravity_install_dry_run(tmp_home_and_project):
    home, proj = tmp_home_and_project
    from graphify.__main__ import _antigravity_install
    _assert_no_fs_changes(home, proj, lambda: _antigravity_install(proj, dry_run=True))


@pytest.mark.parametrize("p", [
    "codex", "opencode", "aider", "claw", "droid", "trae", "trae-cn", "hermes",
])
def test_agents_install_dry_run(p, tmp_home_and_project):
    home, proj = tmp_home_and_project
    from graphify.__main__ import _agents_install
    _assert_no_fs_changes(home, proj, lambda: _agents_install(proj, p, dry_run=True))


# ── Dry-run output content ───────────────────────────────────────────────────

def test_dry_run_output_contains_create_markers(tmp_home_and_project, capsys):
    """A fresh project's dry-run output should mark every action as CREATE."""
    home, proj = tmp_home_and_project
    from graphify.__main__ import claude_install
    _run_with_isolated_fs(home, proj, lambda: claude_install(proj, dry_run=True))
    out = capsys.readouterr().out
    assert "=== plan: graphify claude install ===" in out
    assert "CREATE" in out
    # CLAUDE.md and .claude/settings.json are both new.
    assert "CLAUDE.md" in out
    assert ".claude/settings.json" in out


def test_dry_run_output_contains_unified_diff_for_existing_files(tmp_home_and_project, capsys):
    """If a target file exists with different content, dry-run shows a diff."""
    home, proj = tmp_home_and_project
    (proj / "CLAUDE.md").write_text("# Pre-existing CLAUDE.md\n\nMy rules.\n", encoding="utf-8")
    from graphify.__main__ import claude_install
    _run_with_isolated_fs(home, proj, lambda: claude_install(proj, dry_run=True))
    out = capsys.readouterr().out
    assert "MODIFY" in out
    assert "## graphify" in out
    # Unified-diff markers
    assert "@@ " in out
    assert "+## graphify" in out


def test_dry_run_output_contains_no_op_for_idempotent_install(tmp_home_and_project, capsys):
    """If everything is already installed, dry-run should report NO-OP."""
    home, proj = tmp_home_and_project
    from graphify.__main__ import claude_install
    _run_with_isolated_fs(home, proj, lambda: claude_install(proj))  # real install
    capsys.readouterr()  # discard install output
    _run_with_isolated_fs(home, proj, lambda: claude_install(proj, dry_run=True))
    out = capsys.readouterr().out
    assert "NO-OP" in out


# ── Dry-run does not emit audit events ───────────────────────────────────────

def test_dry_run_does_not_emit_audit_events(tmp_home_and_project, tmp_path):
    """Dry-run early-returns before apply_plan, so no audit events fire."""
    home, proj = tmp_home_and_project
    audit_log = tmp_path / "audit.log"
    with patch.dict(os.environ, {"GRAPHIFY_AUDIT_LOG_PATH": str(audit_log)}):
        from graphify.__main__ import claude_install
        _run_with_isolated_fs(home, proj, lambda: claude_install(proj, dry_run=True))
    assert not audit_log.exists()


# ── Sanity: dry-run is byte-identical to "no-op" check across two runs ──────

def test_dry_run_is_idempotent(tmp_home_and_project):
    """Two dry-runs in a row produce the same plan (no hidden state)."""
    home, proj = tmp_home_and_project
    from graphify.__main__ import claude_install
    _run_with_isolated_fs(home, proj, lambda: claude_install(proj, dry_run=True))
    snap1 = _snapshot(home), _snapshot(proj)
    _run_with_isolated_fs(home, proj, lambda: claude_install(proj, dry_run=True))
    snap2 = _snapshot(home), _snapshot(proj)
    assert snap1 == snap2
