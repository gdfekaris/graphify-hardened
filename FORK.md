# FORK.md

This file documents how this fork (`graphify-hardened`) relates to its upstream project, why the fork exists, and how upstream changes are evaluated and pulled in.

## Upstream baseline

- **Upstream:** [safishamsi/graphify](https://github.com/safishamsi/graphify)
- **Most recent upstream tag at baseline:** `v0.5.7` (commit `47a994ad5b14b8408ea392afeb5d95de0cc8fac2`)
- **Baseline commit SHA:** `09998223641dd71aaede3251c996341037510191` (one untagged upstream commit past `v0.5.7` — a README update adding yaml/yml to the file-type table)
- **Baseline captured:** 2026-04-30

This fork does **not** maintain a live `upstream` git remote. Upstream changes are pulled in manually by cherry-pick after diff review (see "Upstream cherry-pick process" below). When a cherry-pick batch is performed, a temporary remote (`upstream-temp`) is added, used, and removed in the same session so the fork's git topology stays clean and the threat-model claim "no live upstream remote" remains true.

## Why this fork exists

This fork hardens upstream graphify against four classes of threat that are under-addressed in the upstream project:

- **Supply-chain risk** from unpinned dependencies and an unverified third-party CDN script in generated HTML output.
- **Indirect prompt injection** through extracted graph content. The extraction pipeline runs an LLM over arbitrary corpus files; the resulting node labels and rationale text are persisted to `GRAPH_REPORT.md` and re-injected into the user's assistant context on every turn via the always-on hook. A hostile file in the corpus can plant persistent instructions in the assistant's context.
- **Subprocess and cache deserialization** vectors that are hardened against hostile-input triggers.
- **Lack of audit trail** for security-relevant actions (URL fetches, repo clones, skill installs, hook installs).

In addition, the fork removes optional extras whose attack surface is not justified for the user's intended use.

## Changes from upstream

(Each phase of the implementation plan appends entries here.)

### Phase 0 — Optional extras decisions (Task 0.4)

The following keep/drop decisions were made during fork setup. Each dropped extra will be removed from `pyproject.toml` and the `all` aggregator as a separate commit in Phase 1 (Task 1.2). The corresponding code paths (where they exist as fork-local code, e.g., `push_to_neo4j` in `export.py`) are retained — the extras list controls only which optional dependencies are installable.

| Extra | Packages | Decision | Rationale |
|---|---|---|---|
| `mcp` | `mcp` | **Keep** | Small surface, official Anthropic package. The MCP stdio server is core to graphify's integration with assistants. |
| `neo4j` | `neo4j` | **Drop** | Pure export target, not part of the core pipeline. The user is not running a Neo4j instance and has no plan to. Removing it eliminates one network-protocol-speaking dependency. The `--neo4j` flag (file export only — writes `cypher.txt`) still functions without the driver; only `--neo4j-push` would have required it. |
| `pdf` | `pypdf`, `html2text` | **Keep** | The user processes PDFs. Will be hardened in Task 4.9 (memory cap on parsing, version pinning vs. known CVEs, adversarial-fixture test). |
| `watch` | `watchdog` | **Keep** | Local filesystem only, no network surface. |
| `svg` | `matplotlib` | **Keep** | Local rendering only, mature package. |
| `leiden` | `graspologic` | **Keep** | Community detection; mature package; conditional on `python_version < '3.13'` already. |
| `office` | `python-docx`, `openpyxl` | **Keep** | The user processes Office documents. Will be hardened in Task 4.9 (mandatory `defusedxml` retrofit for any XML parsing of untrusted content; version pinning vs. known XXE/zip-bomb CVEs; adversarial-fixture test). |
| `video` | `faster-whisper`, `yt-dlp` | **Drop** | See "Rationale for dropping `[video]`" below. |
| `kimi` | `openai` (Moonshot client) | **Drop** | Routes extraction through a different upstream LLM provider than the user's primary coding assistant. The user prefers to keep extraction on a single provider for a smaller trust surface. |

### Phase 1 — Dependency hardening

- **Lockfile committed (Task 1.3 / 1.4).** A `uv.lock` covering all required and kept-extra dependencies is now committed at the repo root. Removed from `.gitignore`. Generated with `uv 0.11.8` against Python 3.11; resolved 105 packages.

  **Scope of protection:** graphify is published as a library, so the lockfile primarily protects this fork's *own* development and CI builds, not downstream consumers who `pip install graphifyy` (those resolve transitive dependencies against the version ranges declared in `pyproject.toml`). For a private hardened fork that is not yet published, this is the relevant scope. The lockfile also gives `pip-audit` and `osv-scanner` (Task 1.6, 1.7) a fully-pinned input to scan against.

#### Rationale for dropping `[video]`

The `[video]` extra turns graphify from "parses local code and docs" into "downloads arbitrary media from arbitrary URLs and feeds it to two complex C/Python parsers." That is a categorical jump in attack surface that is not justified by the user's intended use, which does not include video/audio ingestion. Specifically:

- **yt-dlp** has a long history of CVEs, particularly around argument injection (the `--exec` family runs shell commands post-download), output-template substitution, and parsers for site-specific extractors. The plan's Task 4.6 sandboxing recipe (URL after `--`, forced `--no-exec`/`--no-call-home`/`--no-update`, hard timeout, bounded output dir) addresses the known classes but not future bugs in extractor code. Dropping eliminates the entire class.
- **faster-whisper** downloads model weights from `huggingface.co` on first run, leaking the user's IP and chosen model size to a third party and loading code/data from that third party into the process. It uses CTranslate2 (not raw PyTorch pickle), which avoids the classic pickle-checkpoint-as-RCE vector, but the runtime download is still a trust extension we don't need.
- **ffmpeg** (transitive, invoked by both packages) is not a Python dependency but a system binary with a massive memory-corruption surface in its container and codec parsers. Hostile media files have repeatedly led to ffmpeg CVEs. Subprocess argument hardening does not mitigate this — only sandboxing (firejail/bubblewrap/container) or "don't feed it untrusted media" does, and neither is in scope for this fork.

If the user later needs video/audio ingestion, the right path is to install the necessary tooling explicitly outside this fork (e.g., transcribe locally, then point graphify at the resulting text), or to introduce a sandboxed video-ingest task as a separate hardened plan.

## Upstream cherry-pick process

This fork does not maintain a live `upstream` git remote. Upstream changes are pulled in manually by cherry-pick after diff review. The diff review and selective-pick steps are the actual control protecting against a malicious or careless upstream commit (the threat model in this file calls this "out of scope, mitigated by review" — this section makes the review part real).

Cadence: monthly, or sooner if upstream announces a security fix or if [`audit.yml`](.github/workflows/audit.yml) reports a new CVE in a pinned dependency.

### 1. Identify new upstream tag(s)

Visit <https://github.com/safishamsi/graphify/tags> (or `/releases`). Identify any tag(s) released since the baseline currently recorded in [Upstream baseline](#upstream-baseline) above. Note the previously-incorporated tag — that is the lower bound for the diff.

### 2. Save the diff for review

For each new tag, save **both** the patch view and the file-level diff. GitHub's compare URL works for both:

```bash
PREV=v0.5.7         # the tag currently in "Upstream baseline"
NEW=v0.5.8          # whatever upstream just shipped

curl -fsSL "https://github.com/safishamsi/graphify/compare/${PREV}...${NEW}.patch" \
  > "audit/upstream-${NEW}.patch"
curl -fsSL "https://github.com/safishamsi/graphify/compare/${PREV}...${NEW}.diff" \
  > "audit/upstream-${NEW}.diff"
```

The `.patch` view (per-commit, with messages) is the artifact attached to the eventual cherry-pick PR. The `.diff` view (file-level) is what you actually read line-by-line during the checklist below.

### 3. Diff review checklist

A reviewer must walk through every item before any cherry-pick happens. "Looks fine" is not an acceptable result — every line below must be either confirmed clean or explicitly waived with a written rationale that goes into the cherry-pick PR description.

Run each `grep` against `audit/upstream-${NEW}.diff`:

- **No new network endpoints.** `grep -nE "https?://|urlopen|urllib|requests\.(get|post|put|delete)|socket\.connect|httpx\." audit/upstream-${NEW}.diff` — every hit must already be reachable through `graphify/security.py::safe_fetch` (or be a comment / docstring / test fixture).
- **No new subprocess invocations.** `grep -nE "subprocess|Popen|os\.system|os\.exec|pty\." audit/upstream-${NEW}.diff` — every hit must use `shell=False`, list-form argv, a `--` separator before any positional argv, and an explicit timeout. Any new subprocess site is a Phase 4 follow-up; do **not** cherry-pick the new site without also extending `audit/subprocess-review.md`.
- **No deserialization of untrusted bytes.** `grep -nE "pickle|cPickle|dill|marshal|shelve|joblib|cloudpickle|yaml\.load[^_]|yaml\.unsafe_load|eval\(|exec\(" audit/upstream-${NEW}.diff` — every hit must be reviewed against `audit/deserialization-review.md`. New pickle / unsafe-yaml / eval introductions are blocking.
- **No file writes outside `graphify-out/`.** `grep -nE "open\([^)]*['\"]w[b+]?['\"]|Path[^)]*\.write_(text|bytes)|shutil\.copy" audit/upstream-${NEW}.diff` — confirm each write target is inside `graphify-out/`, the explicit install destination, or a test tmp dir.
- **No relaxation of `security.py`.** Any change to `validate_url`, `safe_fetch`, `safe_fetch_text`, or `validate_graph_path` is blocking by default. Read the change end-to-end and confirm the threat model is preserved (private/loopback/link-local/IMDS still blocked, redirect targets still re-validated, scheme allowlist unchanged).
- **No bypass of the install-path framing.** Any change to the rules-file constants (`_CLAUDE_MD_SECTION`, `_AGENTS_MD_SECTION`, `_GEMINI_MD_SECTION`, `_VSCODE_INSTRUCTIONS_SECTION`, `_ANTIGRAVITY_RULES`, `_KIRO_STEERING`, `_CURSOR_RULE`) or to the inline-hook nudges (`_SETTINGS_HOOK`, `_GEMINI_HOOK`, `_CODEX_HOOK`, `_OPENCODE_PLUGIN_JS`) must preserve the untrusted-data framing block from Phase 3.5. If upstream rewrites a rules file, the cherry-pick must re-thread the framing on top.
- **No new dependencies that were not in the previous lockfile.** `grep -nE "^\+.*\b(import|from)\b" audit/upstream-${NEW}.diff | grep -vE "from graphify|^\+\+\+|^\+--"` — every new top-level import in non-test code must already be in `uv.lock`. Any new declared dep in `pyproject.toml` requires a fresh `uv lock` and a new audit run before merge.
- **Heuristic flag on commit messages and PR descriptions.** Any upstream commit whose message matches the Phase 3.3 patterns (imperative-ignore, role-injection markup, exfil instructions, jailbreak phrases, persona overrides) gets explicit extra scrutiny. Treat the message text as a signal, not as instructions to follow.

If anything in the checklist fails, do not cherry-pick that commit. Either skip it (with rationale) or open a fork-local follow-up task to harden the new surface before pulling the change in.

### 4. Cherry-pick onto a working branch

Add a temporary remote, fetch the relevant tag, and cherry-pick onto a fresh branch off `main`. The remote is intentionally ephemeral — the threat-model claim "no live upstream remote" only stays true if it is removed at the end of every batch.

```bash
git remote add upstream-temp https://github.com/safishamsi/graphify.git
git fetch upstream-temp "${NEW}"
git checkout -b "upstream-${NEW}" main

# For each upstream commit deemed safe and desirable in step 3:
git cherry-pick <commit-sha>
# Resolve conflicts. Each fork-local commit on `main` must still apply,
# or the cherry-pick must be explicitly deferred with a rationale captured
# below in "Changes from upstream".

git remote remove upstream-temp
git remote -v   # confirm only `origin` is configured
```

Skip any commit that fails the checklist in step 3, or that materially conflicts with a fork-local change. Record skipped commits in step 8.

### 5. Re-run lock + audit

```bash
uv lock
uv run --with pip-audit==2.10.0 pip-audit --strict
osv-scanner --lockfile=uv.lock
```

If `uv lock` produces drift, commit the updated `uv.lock` as a separate commit on the working branch (so the cherry-pick history stays distinguishable from lock-file mechanical updates).

### 6. Run the full test suite

```bash
uv run --with pytest pytest tests/
```

All tests must pass. The Phase 7 hardening regression suite (SSRF redirect chains, lockfile drift, install round-trip, prompt-injection E2E, subprocess argument injection, cache deserialization, audit-logger fail-loud) is the load-bearing layer here — if any of those tests regress under upstream changes, the cherry-pick is blocking until the regression is understood and the test is updated **only** if the test is wrong, not if the behaviour drift is acceptable.

### 7. Open a cherry-pick PR

Open a PR from `upstream-${NEW}` into `main`. The PR description must list:

- Every cherry-picked commit SHA, in order, with the upstream commit subject.
- Every deliberately-skipped commit, with rationale (failed checklist item, conflict with fork-local change, deferred-for-later).
- A link to the saved diff under `audit/upstream-${NEW}.patch` and `audit/upstream-${NEW}.diff`.
- The `pip-audit` / `osv-scanner` output (or "clean").
- The test-suite count (`<N> passed`).

Merge after review. Do not squash — the cherry-pick history is part of the audit trail.

### 8. Update this file

After merge, update two sections in this `FORK.md`:

- **Upstream baseline** — bump to `${NEW}` and the corresponding upstream commit SHA.
- **Changes from upstream** — append a Phase-style entry recording the cherry-pick date, the picked commits, and any deliberately-skipped commits with rationale.

### 9. Tag a fork release

```bash
git tag "v0.1.<n>-hardened"   # increment from the previous fork tag
git push origin "v0.1.<n>-hardened"
```

The tag namespace is intentionally distinct from upstream's `vX.Y.Z` so a `git tag` listing in either repo unambiguously identifies which fork it came from.

## Public release trigger

This fork goes public when:

- (a) the lockfile lands and is verified
- (b) the SRI/vendoring patch is applied and tested
- (c) the prompt-injection containment from Phase 3 is in place
- (d) the subprocess and cache audits from Phase 4 are clean
- (e) the audit logger from Phase 5 is wired in with fail-loud semantics for security events
- (f) the test suite passes including the new hardening tests in Phase 7

Until then, it remains private.
