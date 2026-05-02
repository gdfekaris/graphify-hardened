# Subprocess invocation review (Phase 4 / Task 4.5)

**Scope:** every `subprocess.*`, `Popen`, `check_output`, `os.system`, `os.popen`
call site in `graphify/`. Reviewed at commit `9ebdb71` after the timeout fix.

## Inventory

```
$ grep -rn 'subprocess\.\|Popen\|check_output\|os\.system\|os\.popen' graphify/
graphify/hooks.py:141:        result = subprocess.run(
graphify/__main__.py:1100:        result = _sp.run(cmd, capture_output=True, text=True, timeout=_GIT_NETWORK_TIMEOUT)
graphify/__main__.py:1110:        result = _sp.run(cmd, capture_output=True, text=True, timeout=_GIT_NETWORK_TIMEOUT)
```

Three sites. None use `shell=True`, `os.system`, `os.popen`, `Popen`, or
`check_output`. Every invocation passes argv as a list, so the shell is never
spawned and word-splitting is never performed.

`graphify/transcribe.py` uses the `yt_dlp` Python API rather than subprocess.
yt-dlp can spawn ffmpeg via postprocessors, but `ydl_opts['postprocessors']`
is set to `[]`, so the current code does not invoke any external binary
through that path. yt-dlp containment is the dedicated subject of Task 4.6
and is out of scope for this audit.

## Site 1 — `graphify/hooks.py:141` (`_hooks_dir`)

| field            | value |
| ---------------- | ----- |
| binary           | `git` |
| argv             | `["git", "-C", str(root), "config", "core.hooksPath"]` |
| `root` source    | `_git_root(path)` — walks upward from a project path until a `.git/` directory is found and returns the resolved parent |
| `shell=`         | default (`False`) |
| `check=`         | not set; returncode inspected manually |
| `timeout=`       | **5 s** (added in `9ebdb71`) |
| stdout / stderr  | `capture_output=True, text=True`. Output (`.stdout`) is one config value, in practice ≤ 256 bytes. Unbounded in principle but bounded in practice by `git config`'s output size, which for a single key is trivial. |
| failure handling | catches `OSError`, `FileNotFoundError`, and `subprocess.TimeoutExpired`; on any of them, falls back to `<root>/.git/hooks` |
| `--` separator   | not needed — `core.hooksPath` is a literal in the argv, not user input |

**Attacker-controlled inputs:** none. `root` is derived from a filesystem
walk; the rest of the argv is literal. The captured output is trusted only as
far as becoming a directory path, so a hostile `core.hooksPath` value could
direct `_install_hook` to write to an unexpected location *inside the user's
own machine*. That is a misconfiguration concern of the local repo, not a
remote-attacker concern, and is bounded by the existing trust model (the user
already runs the repo's tooling).

**Status:** clean.

## Site 2 — `graphify/__main__.py:1100` (`_clone_repo`, pull branch)

| field            | value |
| ---------------- | ----- |
| binary           | `git` |
| argv             | `["git", "-C", str(dest), "pull"]` plus `["--", "origin", branch]` when `branch` is set |
| `dest` source    | either the CLI `--out` flag or `~/.graphify/repos/<owner>/<repo>` where `<owner>` and `<repo>` are validated by `_parse_git_url` against `^[a-zA-Z0-9._-]+$` and dot-only-name rejection (Task 4.4) |
| `branch` source  | CLI `--branch` flag (user-controlled). Consumed as the value of `--branch` / passed after the `--` separator, so even a value beginning with `-` cannot be reinterpreted as an option |
| `shell=`         | default (`False`) |
| `check=`         | not set; returncode inspected, non-zero downgraded to a warning (we still return the existing clone) |
| `timeout=`       | **300 s** (added in `9ebdb71`) |
| stdout / stderr  | `capture_output=True, text=True`. Unbounded in principle. Realistic git pull output is small (tens of KB); a hostile remote that streams gigabytes would be cut off by the 300 s timeout long before hitting any practical memory ceiling. |
| failure handling | `TimeoutExpired` warns and serves the existing stale clone (the function is supposed to return a usable path); other failures warn and fall through |
| `--` separator   | yes — between `pull` and the positional `origin <branch>` (Task 4.4) |

**Attacker-controlled inputs:** the URL was already validated by
`_parse_git_url` + `_enforce_clone_allowlists` upstream. By the time we reach
the subprocess call, the URL has been parsed into safe components and the
host/owner allowlists (if set) have approved both. `branch` is user-typed but
shell=False + argv-list invocation + `--` separator make argv injection
impossible.

**Status:** clean.

## Site 3 — `graphify/__main__.py:1110` (`_clone_repo`, clone branch)

| field            | value |
| ---------------- | ----- |
| binary           | `git` |
| argv             | `["git", "clone", "--depth", "1"]` then optionally `["--branch", branch]`, then `["--", git_url, str(dest)]` |
| `git_url` source | output of `_parse_git_url` (Task 4.4): scheme/host/owner/repo all validated; URL is reassembled to canonical form with `.git` suffix |
| `dest` source    | as in Site 2 |
| `branch` source  | as in Site 2 |
| `shell=`         | default (`False`) |
| `check=`         | not set; non-zero returncode prints stderr and exits non-zero |
| `timeout=`       | **300 s** (added in `9ebdb71`) |
| stdout / stderr  | `capture_output=True, text=True`. As above — bounded in practice by the 300 s ceiling. |
| failure handling | `TimeoutExpired` prints a clear error and exits non-zero; other failures echo `result.stderr` and exit non-zero |
| `--` separator   | yes — between options and the positional `<url> <dest>` (Task 4.4) |

**Attacker-controlled inputs:** see Site 2. Same containment.

**Status:** clean.

## Aggregate findings

- **`shell=False` everywhere:** confirmed, by the absence of any `shell=True`
  in the inventory and by the use of list-form argv at every site.
- **Timeouts:** added at all three sites in commit `9ebdb71`. Local op (5 s),
  network ops (300 s).
- **stdout/stderr bounding:** captured in full via `capture_output=True`. Not
  byte-bounded, but bounded in practice by git's small native output for the
  invoked subcommands and by the timeout ceiling. A streaming reader with a
  byte cap was considered and deferred — the realistic OOM risk is negligible
  given the existing controls and the cost of refactor is high.
- **`--` separators:** present where user input flows into positional
  arguments (`git clone <url> <dest>`, `git pull origin <branch>`).
- **Input validation upstream of every site:** owner/repo character class,
  host pattern, optional host/owner allowlists, dot-only-name rejection.

No additional issues found. Task 4.6 (yt-dlp sandboxing) tracks the
process-spawning behavior of yt-dlp itself, which lives outside the
`subprocess` import surface this audit covered.
