"""Phase 7.4: skill installer round-trip cleanup test.

For each subcommand install/uninstall pair: starting from empty HOME and
empty project dirs, install must write something; uninstall must
return the filesystem to the pre-install state, modulo a documented
class of *acceptable* leftovers (Phase 6 audit finding F5):

1. Empty parent directories. Several uninstallers remove their files
   but do not walk up rmdir'ing empty ancestor dirs (.kiro/, .cursor/,
   .agents/, .github/, etc.). Cosmetic.

2. JSON config-file stubs. When graphify shares a config file with
   user-owned settings (.claude/settings.json, .gemini/settings.json,
   .codex/hooks.json, .opencode/opencode.json), uninstall removes only
   graphify's own entries and leaves the surrounding structure intact.
   The leftover is structurally empty — `{}`, or `{"hooks": {X: []}}`
   — and is left by design, because the file is shared user config:
   deleting it could destroy non-graphify state.

The test recursively walks any post-uninstall path that did not exist
pre-install and accepts it iff (1) it is an empty directory, or (2) it
is a JSON file whose content is "structurally empty" (every leaf is an
empty dict or empty list).

A note on scope: this test exercises the **subcommand** install paths
(`graphify <platform> install`), which have matched install/uninstall
function pairs. The **top-level** `graphify install --platform <P>`
chains to subcommand installers (F3 surface merge) but has no matching
top-level uninstaller — `install --platform claude` writes a HOME skill
file at `~/.<platform>/skills/...` that no uninstall command removes.
This is a pre-existing gap, not a hardening regression, and is out of
scope for Phase 7.4.

Forward path (F5 resolution): an alternative to declaring these
leftovers acceptable would be to tighten each uninstaller to delete
its own dirs and stub-JSONs. The conservative choice taken here is
that JSON stubs may belong to non-graphify user config and must not
be deleted, while empty-dir cleanup could land in a future PR
without changing this test (those leftovers would just stop appearing).
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# Snapshot helpers
# ---------------------------------------------------------------------------

def _walk(root: Path):
    """Yield (relpath_str, kind, full_path).

    kind is "file" for any regular file, or "empty-dir" for any directory
    that contains no entries at all (post-install or post-uninstall). The
    root itself is never yielded as empty-dir — only descendants.
    """
    for dirpath_str, dirnames, filenames in os.walk(root):
        dirpath = Path(dirpath_str)
        for name in filenames:
            full = dirpath / name
            yield (full.relative_to(root).as_posix(), "file", full)
        if not dirnames and not filenames and dirpath != root:
            yield (dirpath.relative_to(root).as_posix() + "/", "empty-dir", dirpath)


def _snapshot(roots: dict[str, Path]) -> dict[tuple[str, str], str]:
    """Return {(label, relpath): content_hash_or_marker}.

    Files are SHA-256'd. Empty descendant directories carry an
    "<empty-dir>" marker so we can detect post-install dir creation
    even when no file was written.
    """
    state: dict[tuple[str, str], str] = {}
    for label, root in roots.items():
        for rel, kind, full in _walk(root):
            if kind == "file":
                state[(label, rel)] = hashlib.sha256(full.read_bytes()).hexdigest()
            else:
                state[(label, rel)] = "<empty-dir>"
    return state


# ---------------------------------------------------------------------------
# Acceptable-leftover predicate
# ---------------------------------------------------------------------------

def _json_is_structurally_empty(value) -> bool:
    """True if value is a (possibly nested) container with only empty
    containers as leaves. Strings, numbers, bools, null are non-empty."""
    if isinstance(value, dict):
        return all(_json_is_structurally_empty(v) for v in value.values())
    if isinstance(value, list):
        return all(_json_is_structurally_empty(v) for v in value)
    return False


def _is_acceptable_leftover(rel: str, kind: str, full: Path) -> bool:
    if kind == "empty-dir":
        return True
    if rel.endswith(".json"):
        try:
            data = json.loads(full.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        return _json_is_structurally_empty(data)
    return False


# ---------------------------------------------------------------------------
# Per-platform install/uninstall callable pairs
# ---------------------------------------------------------------------------

def _setup_isolated(monkeypatch, home: Path, project: Path) -> None:
    """Patch Path.home() and chdir into project. graphify's installers
    consult Path.home() for HOME-located writes (skills, ~/.claude/CLAUDE.md
    registration) and Path('.') / project_dir for project-located writes."""
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.chdir(project)


def _claude_install(home, project):
    from graphify.__main__ import claude_install
    claude_install(project)


def _claude_uninstall(home, project):
    from graphify.__main__ import claude_uninstall
    claude_uninstall(project)


def _gemini_install(home, project):
    from graphify.__main__ import gemini_install
    gemini_install(project)


def _gemini_uninstall(home, project):
    from graphify.__main__ import gemini_uninstall
    gemini_uninstall(project)


def _vscode_install(home, project):
    from graphify.__main__ import vscode_install
    vscode_install(project)


def _vscode_uninstall(home, project):
    from graphify.__main__ import vscode_uninstall
    vscode_uninstall(project)


def _cursor_install(home, project):
    from graphify.__main__ import _cursor_install as fn
    fn(project)


def _cursor_uninstall(home, project):
    from graphify.__main__ import _cursor_uninstall as fn
    fn(project)


def _kiro_install(home, project):
    from graphify.__main__ import _kiro_install as fn
    fn(project)


def _kiro_uninstall(home, project):
    from graphify.__main__ import _kiro_uninstall as fn
    fn(project)


def _antigravity_install(home, project):
    from graphify.__main__ import _antigravity_install as fn
    fn(project)


def _antigravity_uninstall(home, project):
    from graphify.__main__ import _antigravity_uninstall as fn
    fn(project)


def _make_agents_pair(platform: str):
    def install(home, project):
        from graphify.__main__ import _agents_install as fn
        fn(project, platform)

    def uninstall(home, project):
        from graphify.__main__ import _agents_uninstall as fn
        fn(project, platform=platform)
    return install, uninstall


def _git_hooks_install(home, project):
    from graphify import hooks
    hooks.install(project)


def _git_hooks_uninstall(home, project):
    from graphify import hooks
    hooks.uninstall(project)


_AGENTS_PLATFORMS = ("codex", "opencode", "aider", "claw", "droid", "trae", "trae-cn", "hermes")

_PAIRS = [
    ("claude",      _claude_install,      _claude_uninstall,      False),
    ("gemini",      _gemini_install,      _gemini_uninstall,      False),
    ("vscode",      _vscode_install,      _vscode_uninstall,      False),
    ("cursor",      _cursor_install,      _cursor_uninstall,      False),
    ("kiro",        _kiro_install,        _kiro_uninstall,        False),
    ("antigravity", _antigravity_install, _antigravity_uninstall, False),
    ("git-hooks",   _git_hooks_install,   _git_hooks_uninstall,   True),
]
for _p in _AGENTS_PLATFORMS:
    _ins, _un = _make_agents_pair(_p)
    _PAIRS.append((f"agents:{_p}", _ins, _un, False))


# ---------------------------------------------------------------------------
# git-init helper for the hooks platform
# ---------------------------------------------------------------------------

def _init_git_repo(path: Path) -> None:
    """Initialize a minimal git repo with a stable identity. Captures stderr
    to keep pytest output clean."""
    subprocess.run(
        ["git", "init", "--quiet", str(path)],
        check=True, capture_output=True,
    )
    # `git init` may print a hint about default-branch config; --quiet
    # suppresses it. We don't need a commit — install/uninstall hooks
    # only touch .git/hooks/.


# ---------------------------------------------------------------------------
# The test
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "label,install_fn,uninstall_fn,needs_git",
    _PAIRS,
    ids=[p[0] for p in _PAIRS],
)
def test_install_round_trip(label, install_fn, uninstall_fn, needs_git, tmp_path, monkeypatch):
    home = tmp_path / "home"
    project = tmp_path / "project"
    home.mkdir()
    project.mkdir()

    if needs_git:
        _init_git_repo(project)

    _setup_isolated(monkeypatch, home, project)

    roots = {"home": home, "project": project}

    before = _snapshot(roots)

    install_fn(home, project)

    after_install = _snapshot(roots)
    assert after_install != before, f"{label}: install wrote nothing"

    uninstall_fn(home, project)

    after_uninstall = _snapshot(roots)

    leftover_keys = set(after_uninstall) - set(before)
    unacceptable: list[tuple[tuple[str, str], str]] = []
    for key in sorted(leftover_keys):
        lbl, rel = key
        kind = "empty-dir" if rel.endswith("/") else "file"
        full = roots[lbl] / rel.rstrip("/")
        if not _is_acceptable_leftover(rel, kind, full):
            try:
                preview = full.read_text(encoding="utf-8")[:200] if kind == "file" else "<dir>"
            except OSError:
                preview = "<unreadable>"
            unacceptable.append((key, preview))

    assert not unacceptable, (
        f"{label}: uninstall left non-empty, non-stub residue. "
        f"Each entry is ((root, relpath), preview):\n  "
        + "\n  ".join(f"{k} -> {p!r}" for k, p in unacceptable)
    )


# ---------------------------------------------------------------------------
# Acceptable-leftover predicate self-tests
# ---------------------------------------------------------------------------

def test_json_structurally_empty_predicate():
    assert _json_is_structurally_empty({})
    assert _json_is_structurally_empty([])
    assert _json_is_structurally_empty({"hooks": {"PreToolUse": []}})
    assert _json_is_structurally_empty({"plugin": [], "model": []})
    assert _json_is_structurally_empty({"a": {}, "b": {"c": []}})

    assert not _json_is_structurally_empty({"a": "value"})
    assert not _json_is_structurally_empty({"hooks": {"PreToolUse": [{"x": 1}]}})
    assert not _json_is_structurally_empty([1])
    assert not _json_is_structurally_empty("string")
    assert not _json_is_structurally_empty(0)
    assert not _json_is_structurally_empty(False)


def test_is_acceptable_leftover_for_empty_dir(tmp_path):
    d = tmp_path / "empty"
    d.mkdir()
    assert _is_acceptable_leftover("empty/", "empty-dir", d)


def test_is_acceptable_leftover_rejects_non_json_file(tmp_path):
    f = tmp_path / "stray.md"
    f.write_text("# leftover content\n")
    assert not _is_acceptable_leftover("stray.md", "file", f)


def test_is_acceptable_leftover_rejects_user_content_in_json(tmp_path):
    f = tmp_path / "settings.json"
    f.write_text(json.dumps({"theme": "dark"}))
    assert not _is_acceptable_leftover("settings.json", "file", f)
