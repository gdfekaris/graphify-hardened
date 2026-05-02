"""Tests for graphify._parse_git_url and _clone_repo allowlist gates (Task 4.4)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from graphify.__main__ import (
    _clone_repo,
    _enforce_clone_allowlists,
    _parse_git_url,
)


# ---------------------------------------------------------------------------
# _parse_git_url — URL syntax equivalence and host coverage
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/karpathy/nanoGPT",
        "https://github.com/karpathy/nanoGPT.git",
        "https://github.com/karpathy/nanoGPT/",
        "ssh://git@github.com/karpathy/nanoGPT",
        "ssh://git@github.com/karpathy/nanoGPT.git",
        "git@github.com:karpathy/nanoGPT",
        "git@github.com:karpathy/nanoGPT.git",
    ],
)
def test_parse_git_url_all_syntaxes_yield_same_owner_repo_host(url):
    result = _parse_git_url(url)
    assert result["host"] == "github.com"
    assert result["owner"] == "karpathy"
    assert result["repo"] == "nanoGPT"


def test_parse_git_url_gitlab_host():
    r = _parse_git_url("https://gitlab.com/group/project")
    assert r["host"] == "gitlab.com"
    assert r["owner"] == "group"
    assert r["repo"] == "project"


def test_parse_git_url_self_hosted():
    r = _parse_git_url("https://git.internal.example.com/team/repo.git")
    assert r["host"] == "git.internal.example.com"
    assert r["owner"] == "team"
    assert r["repo"] == "repo"


def test_parse_git_url_scp_self_hosted():
    r = _parse_git_url("git@git.internal.example.com:team/repo")
    assert r["scheme"] == "scp"
    assert r["host"] == "git.internal.example.com"
    assert r["owner"] == "team"
    assert r["repo"] == "repo"


def test_parse_git_url_records_scheme():
    assert _parse_git_url("https://github.com/o/r")["scheme"] == "https"
    assert _parse_git_url("ssh://git@github.com/o/r")["scheme"] == "ssh"
    assert _parse_git_url("git@github.com:o/r")["scheme"] == "scp"


# ---------------------------------------------------------------------------
# _parse_git_url — rejection cases
# ---------------------------------------------------------------------------

def test_parse_git_url_rejects_empty():
    with pytest.raises(ValueError, match="empty"):
        _parse_git_url("")


def test_parse_git_url_rejects_unsupported_scheme():
    with pytest.raises(ValueError, match="scheme"):
        _parse_git_url("file:///etc/passwd")
    with pytest.raises(ValueError, match="scheme"):
        _parse_git_url("ftp://example.com/repo")


def test_parse_git_url_rejects_owner_with_shell_metachars():
    # The exact attacker shape called out in the plan's manual-acceptance check.
    with pytest.raises(ValueError, match="invalid"):
        _parse_git_url("https://github.com/owner/repo;rm -rf /")


def test_parse_git_url_rejects_scp_owner_with_metachars():
    with pytest.raises(ValueError, match="invalid"):
        _parse_git_url("git@github.com:owner;evil/repo")


def test_parse_git_url_rejects_path_traversal_owner():
    # ".." matches [a-zA-Z0-9._-]+ but would escape the cache dir if accepted.
    # The path-segment-count check fires first here (3 segments), but either
    # rejection path is acceptable as long as the URL is refused.
    with pytest.raises(ValueError):
        _parse_git_url("https://github.com/../etc/repo")


def test_parse_git_url_rejects_path_traversal_repo():
    with pytest.raises(ValueError, match="invalid"):
        _parse_git_url("https://github.com/owner/..")


def test_parse_git_url_rejects_subgroup_path():
    # GitLab subgroups have 3 path components; we require exactly 2 so the
    # cache-dir layout stays unambiguous. This is a deliberate limitation.
    with pytest.raises(ValueError, match="path segments"):
        _parse_git_url("https://gitlab.com/group/sub/repo")


def test_parse_git_url_rejects_missing_repo():
    with pytest.raises(ValueError, match="path segments"):
        _parse_git_url("https://github.com/onlyowner")


def test_parse_git_url_rejects_invalid_host():
    # Hostname with whitespace cannot survive the SCP regex or urlparse cleanly.
    with pytest.raises(ValueError):
        _parse_git_url("https:// bad host /owner/repo")


# ---------------------------------------------------------------------------
# _enforce_clone_allowlists
# ---------------------------------------------------------------------------

def test_allowlist_unset_is_a_no_op(monkeypatch):
    monkeypatch.delenv("GRAPHIFY_CLONE_ALLOWED_HOSTS", raising=False)
    monkeypatch.delenv("GRAPHIFY_CLONE_ALLOWED_OWNERS", raising=False)
    parsed = _parse_git_url("https://github.com/karpathy/nanoGPT")
    _enforce_clone_allowlists(parsed, "https://github.com/karpathy/nanoGPT")


def test_allowlist_host_mismatch_raises(monkeypatch):
    monkeypatch.setenv("GRAPHIFY_CLONE_ALLOWED_HOSTS", "github.com")
    parsed = _parse_git_url("https://gitlab.com/group/project")
    with pytest.raises(ValueError, match="GRAPHIFY_CLONE_ALLOWED_HOSTS"):
        _enforce_clone_allowlists(parsed, "https://gitlab.com/group/project")


def test_allowlist_owner_mismatch_raises(monkeypatch):
    monkeypatch.setenv("GRAPHIFY_CLONE_ALLOWED_OWNERS", "safishamsi")
    parsed = _parse_git_url("https://github.com/karpathy/nanoGPT")
    with pytest.raises(ValueError, match="GRAPHIFY_CLONE_ALLOWED_OWNERS"):
        _enforce_clone_allowlists(parsed, "https://github.com/karpathy/nanoGPT")


def test_allowlist_host_and_owner_combine_with_and(monkeypatch):
    # Host matches but owner does not → still rejected (AND, not OR).
    monkeypatch.setenv("GRAPHIFY_CLONE_ALLOWED_HOSTS", "github.com")
    monkeypatch.setenv("GRAPHIFY_CLONE_ALLOWED_OWNERS", "safishamsi")
    parsed = _parse_git_url("https://github.com/karpathy/nanoGPT")
    with pytest.raises(ValueError, match="GRAPHIFY_CLONE_ALLOWED_OWNERS"):
        _enforce_clone_allowlists(parsed, "https://github.com/karpathy/nanoGPT")


def test_allowlist_host_match_is_case_insensitive(monkeypatch):
    monkeypatch.setenv("GRAPHIFY_CLONE_ALLOWED_HOSTS", "GitHub.Com")
    parsed = _parse_git_url("https://github.com/karpathy/nanoGPT")
    _enforce_clone_allowlists(parsed, "https://github.com/karpathy/nanoGPT")  # no raise


def test_allowlist_owner_match_is_case_insensitive(monkeypatch):
    monkeypatch.setenv("GRAPHIFY_CLONE_ALLOWED_OWNERS", "Karpathy")
    parsed = _parse_git_url("https://github.com/karpathy/nanoGPT")
    _enforce_clone_allowlists(parsed, "https://github.com/karpathy/nanoGPT")  # no raise


# ---------------------------------------------------------------------------
# _clone_repo — rejection happens before subprocess
# ---------------------------------------------------------------------------

def test_clone_repo_invalid_url_exits_before_subprocess(tmp_path, monkeypatch):
    monkeypatch.delenv("GRAPHIFY_CLONE_ALLOWED_HOSTS", raising=False)
    monkeypatch.delenv("GRAPHIFY_CLONE_ALLOWED_OWNERS", raising=False)
    with patch("subprocess.run") as mock_run:
        with pytest.raises(SystemExit):
            _clone_repo("https://github.com/owner/repo;rm -rf /", out_dir=tmp_path / "x")
    mock_run.assert_not_called()


def test_clone_repo_host_allowlist_mismatch_exits_before_subprocess(tmp_path, monkeypatch):
    monkeypatch.setenv("GRAPHIFY_CLONE_ALLOWED_HOSTS", "gitlab.com")
    monkeypatch.delenv("GRAPHIFY_CLONE_ALLOWED_OWNERS", raising=False)
    with patch("subprocess.run") as mock_run:
        with pytest.raises(SystemExit):
            _clone_repo("https://github.com/karpathy/nanoGPT", out_dir=tmp_path / "x")
    mock_run.assert_not_called()


def test_clone_repo_owner_allowlist_mismatch_exits_before_subprocess(tmp_path, monkeypatch):
    monkeypatch.delenv("GRAPHIFY_CLONE_ALLOWED_HOSTS", raising=False)
    monkeypatch.setenv("GRAPHIFY_CLONE_ALLOWED_OWNERS", "safishamsi")
    with patch("subprocess.run") as mock_run:
        with pytest.raises(SystemExit):
            _clone_repo("https://github.com/karpathy/nanoGPT", out_dir=tmp_path / "x")
    mock_run.assert_not_called()


def test_clone_repo_happy_path_invokes_git_with_dash_dash_separator(tmp_path, monkeypatch):
    monkeypatch.delenv("GRAPHIFY_CLONE_ALLOWED_HOSTS", raising=False)
    monkeypatch.delenv("GRAPHIFY_CLONE_ALLOWED_OWNERS", raising=False)
    fake = MagicMock()
    fake.returncode = 0
    fake.stderr = ""
    with patch("subprocess.run", return_value=fake) as mock_run:
        _clone_repo("https://github.com/karpathy/nanoGPT", out_dir=tmp_path / "dest")
    mock_run.assert_called_once()
    argv = mock_run.call_args[0][0]
    assert argv[:4] == ["git", "clone", "--depth", "1"]
    # `--` separator must precede the URL and destination so they cannot be
    # mistaken for options even if the parser ever loosens.
    assert "--" in argv
    dash_idx = argv.index("--")
    assert argv[dash_idx + 1] == "https://github.com/karpathy/nanoGPT.git"
    assert argv[dash_idx + 2] == str(tmp_path / "dest")


def test_clone_repo_allowlist_match_proceeds(tmp_path, monkeypatch):
    monkeypatch.setenv("GRAPHIFY_CLONE_ALLOWED_HOSTS", "github.com")
    monkeypatch.setenv("GRAPHIFY_CLONE_ALLOWED_OWNERS", "karpathy")
    fake = MagicMock()
    fake.returncode = 0
    fake.stderr = ""
    with patch("subprocess.run", return_value=fake) as mock_run:
        _clone_repo("https://github.com/karpathy/nanoGPT", out_dir=tmp_path / "dest")
    mock_run.assert_called_once()


def test_clone_repo_passes_timeout_to_subprocess(tmp_path, monkeypatch):
    monkeypatch.delenv("GRAPHIFY_CLONE_ALLOWED_HOSTS", raising=False)
    monkeypatch.delenv("GRAPHIFY_CLONE_ALLOWED_OWNERS", raising=False)
    fake = MagicMock()
    fake.returncode = 0
    fake.stderr = ""
    with patch("subprocess.run", return_value=fake) as mock_run:
        _clone_repo("https://github.com/karpathy/nanoGPT", out_dir=tmp_path / "dest")
    # A timeout MUST be set; otherwise a stalled network connection would hang
    # the CLI forever.
    assert "timeout" in mock_run.call_args.kwargs
    assert mock_run.call_args.kwargs["timeout"] >= 60


def test_clone_repo_handles_clone_timeout(tmp_path, monkeypatch):
    import subprocess as _sp
    monkeypatch.delenv("GRAPHIFY_CLONE_ALLOWED_HOSTS", raising=False)
    monkeypatch.delenv("GRAPHIFY_CLONE_ALLOWED_OWNERS", raising=False)
    with patch("subprocess.run", side_effect=_sp.TimeoutExpired(cmd="git", timeout=300)):
        with pytest.raises(SystemExit):
            _clone_repo("https://github.com/karpathy/nanoGPT", out_dir=tmp_path / "dest")
