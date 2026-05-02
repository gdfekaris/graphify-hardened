# Skill installer review (Phase 6, Task 6.1)

Date: 2026-05-01
Branch: `development`
Scope: every install/uninstall path in `graphify/__main__.py` and `graphify/hooks.py`.

## Method

Each platform was audited along the five dimensions named in the implementation plan:

1. **What is written** — every file path created or modified, every line of content inserted.
2. **Idempotency** — second `install` does not duplicate / corrupt anything.
3. **Clean uninstall** — `uninstall` removes everything the matching `install` created.
4. **Hook content review** — no unbounded subprocess, no network exfil, fail-closed where appropriate.
5. **Always-on framing** — Phase 3.5 `_UNTRUSTED_FRAMING` (rules) and `_UNTRUSTED_HOOK_SUFFIX` (hooks) present in every emitted artifact.

Verification was performed with three probes against fresh tempdirs (`HOME` mocked, project dir distinct):

- A two-install diff that fails if any byte changes between install #1 and install #2.
- A round-trip diff that fails if any file remaining after `uninstall` was not present before `install`.
- A framing-presence scan against every emitted text artifact.

All probes are reproducible from this commit.

## Coverage matrix

There are two install surfaces:

- The **top-level** `graphify install --platform <P>` (routes through `install()` for 13 platforms, with two special cases routed through `gemini_install()` / `_cursor_install()`).
- The **subcommand** `graphify <platform> install` (16 distinct entry points: `claude`, `gemini`, `cursor`, `vscode`, `kiro`, `antigravity`, `copilot`, plus the 8 `_agents_install` platforms — `codex`, `opencode`, `aider`, `claw`, `droid`, `trae`, `trae-cn`, `hermes` — plus `hook install`).

The two surfaces have different semantics:

| Surface | What it writes |
|---|---|
| `graphify install --platform <P>` (top-level) | Skill file → `~/.<P>/skills/graphify/SKILL.md` (+ `.graphify_version` sidecar). For `claude`/`windows` only: also a registration line in `~/.claude/CLAUDE.md`. For `opencode` only: also `.opencode/plugins/graphify.js` + `.opencode/opencode.json` in **CWD**. |
| `graphify <platform> install` (subcommand) | Project-local rules file (CLAUDE.md / AGENTS.md / GEMINI.md / .cursor/rules/graphify.mdc / etc.) **plus** any platform-specific hook (PreToolUse / BeforeTool / opencode plugin / .codex/hooks.json). For `kiro` and `antigravity`: project-local skill file too. |

This split is itself a UX hazard — see **F3** below.

## Per-platform results

### Idempotency (install ∘ install)

All 27 entry points pass the byte-equal-on-second-install check:

| Surface | Result |
|---|---|
| `install('claude' \| 'codex' \| 'opencode' \| 'aider' \| 'copilot' \| 'claw' \| 'droid' \| 'trae' \| 'trae-cn' \| 'hermes' \| 'kiro' \| 'antigravity' \| 'windows')` | IDEMPOTENT |
| `claude_install` / `gemini_install` / `vscode_install` / `_cursor_install` / `_kiro_install` / `_antigravity_install` | IDEMPOTENT |
| `_agents_install` for codex / opencode / aider / claw / droid / trae / trae-cn / hermes | IDEMPOTENT |

The idempotency contract is enforced through three different mechanisms across the codebase, all observed working:

- **Marker-based** (preferred): the rules-file installers check for `## graphify` (`_CLAUDE_MD_MARKER`, `_AGENTS_MD_MARKER`, `_GEMINI_MD_MARKER`, `_VSCODE_INSTRUCTIONS_MARKER`, `_KIRO_STEERING_MARKER`) before appending. No-op if marker is present.
- **Filter-then-append** (hooks in JSON): `_install_claude_hook` / `_install_gemini_hook` / `_install_codex_hook` strip any existing `graphify` entries from the relevant hook list and re-append. Net change is zero on second install.
- **List-membership** (opencode): `.opencode/opencode.json` plugin list is checked with `entry not in plugins` before appending.
- **Existence-check** (cursor / antigravity): the file is only written if it does not exist. Idempotent at the file level — but means an upgrade to the rule body cannot land via re-install (small caveat; out of scope here).

### Round-trip uninstall (snapshot ∘ install ∘ uninstall ∘ snapshot)

Round-trip cleanliness is more nuanced. Files left behind fall into two categories:

**(a) JSON config stubs** (`.claude/settings.json`, `.gemini/settings.json`, `.codex/hooks.json`, `.opencode/opencode.json`) are **left behind by design** — they are shared user config files, and graphify uninstall correctly removes only its own entries. The leftover files are typically `{}` or `{"hooks":{X:[]}}`. Acceptable.

**(b) Empty parent directories** (`.kiro/`, `.kiro/skills/`, `.kiro/steering/`, `.cursor/`, `.cursor/rules/`, `.agents/`, `.agents/rules/`, `.agents/workflows/`, `.github/`, `.opencode/plugins/`) are cosmetic leftovers. Different uninstallers cleanup directories at different depths (vscode rmdirs three levels; kiro rmdirs only the leaf; antigravity walks three levels but only on the home skill, not the project rules/workflows). Inconsistent but not harmful.

| Surface | Files cleanly removed | Stubs left | Empty dirs left |
|---|---|---|---|
| `claude_install` / `claude_uninstall` | CLAUDE.md, settings.json hook entry | `.claude/settings.json` | `.claude/` |
| `gemini_install` / `gemini_uninstall` | GEMINI.md, settings.json hook entry, skill, version | `.gemini/settings.json` | `.gemini/`, `~/.gemini/` |
| `_cursor_install` / `_cursor_uninstall` | `.cursor/rules/graphify.mdc` | — | `.cursor/`, `.cursor/rules/` |
| `vscode_install` / `vscode_uninstall` | copilot-instructions.md, skill, version | — | `.github/` |
| `_kiro_install` / `_kiro_uninstall` | skill, steering | — | `.kiro/`, `.kiro/skills/`, `.kiro/steering/` |
| `_antigravity_install` / `_antigravity_uninstall` | rules, workflows, skill, version | — | `.agents/`, `.agents/rules/`, `.agents/workflows/` |
| `_agents_install('codex')` / matching uninstall + `_uninstall_codex_hook` | AGENTS.md, hooks.json hook entry | `.codex/hooks.json` | `.codex/` |
| `_agents_install('opencode')` / matching uninstall | AGENTS.md, plugin, opencode.json plugin entry | `.opencode/opencode.json` | `.opencode/`, `.opencode/plugins/` |
| `_agents_install('aider' \| 'claw' \| 'droid' \| 'trae' \| 'trae-cn' \| 'hermes')` / matching uninstall | AGENTS.md | — | — (clean) |

### Hook content review

Five distinct hook payloads were reviewed:

| Hook | Subprocess bound | Network | Fail mode | Verdict |
|---|---|---|---|---|
| `.git/hooks/post-commit` (`_HOOK_SCRIPT`) | `git diff` + bounded Python rebuild over changed files | none | `sys.exit(1)` on rebuild error — but post-commit is informational so the commit is not aborted | OK |
| `.git/hooks/post-checkout` (`_CHECKOUT_SCRIPT`) | identical to post-commit, gated on branch-switch param + `graphify-out/` existing | none | same | OK |
| `.claude/settings.json` PreToolUse (`_SETTINGS_HOOK`) | `python3 -c` + `[ -f ... ]` + `case` over command string | none | `\|\| true` on every step — fail-open advisory hook | OK |
| `.codex/hooks.json` PreToolUse (`_CODEX_HOOK`) | `[ -f ... ]` + `echo` | none | `\|\| true` | OK |
| `.gemini/settings.json` BeforeTool (`_GEMINI_HOOK`) | `[ -f ... ]` + `echo` | none | `\|\| echo '{"decision":"allow"}'` ensures Gemini always sees a decision | OK |
| `.opencode/plugins/graphify.js` (`_OPENCODE_PLUGIN_JS`) | `existsSync` + static string concatenation; `reminded` flag fires once per session | none | early-return on missing `graphify-out/graph.json` | OK |

The git-hook Python interpreter discovery (`_PYTHON_DETECT` in `hooks.py`) deserves a separate note: it derives the interpreter from the `graphify` CLI's shebang, then **allowlists** it through `case "$GRAPHIFY_PYTHON" in *[!a-zA-Z0-9/_.@-]*) GRAPHIFY_PYTHON="" ;;` before invoking. This is the right defense against shebang-injection attacks against a pipx-managed graphify install. Verifies `graphify` importable before use, falls back to `python3` / `python`, exits 0 if none work. Fail-safe.

The OpenCode plugin **rewrites the user's bash command** by prepending an `echo` and `&&`. The injected text is a static string literal in `_OPENCODE_PLUGIN_JS` — no untrusted graph data is interpolated. The `&&` chain semantics are: echo (always succeeds) → user's command. Functionally a no-op except for the printed advisory.

### Always-on framing presence

| Artifact | Framing source | Present? |
|---|---|---|
| Project `CLAUDE.md` (`_CLAUDE_MD_SECTION`) | `_UNTRUSTED_FRAMING` | YES |
| Project `AGENTS.md` (`_AGENTS_MD_SECTION`) | `_UNTRUSTED_FRAMING` | YES |
| Project `GEMINI.md` (`_GEMINI_MD_SECTION`) | `_UNTRUSTED_FRAMING` | YES |
| `.github/copilot-instructions.md` (`_VSCODE_INSTRUCTIONS_SECTION`) | `_UNTRUSTED_FRAMING` | YES |
| `.cursor/rules/graphify.mdc` (`_CURSOR_RULE`) | `_UNTRUSTED_FRAMING` | YES |
| `.kiro/steering/graphify.md` (`_KIRO_STEERING`) | `_UNTRUSTED_FRAMING` | YES |
| `.agents/rules/graphify.md` (`_ANTIGRAVITY_RULES`) | `_UNTRUSTED_FRAMING` | YES |
| `.claude/settings.json` PreToolUse | `_UNTRUSTED_HOOK_SUFFIX` | YES |
| `.codex/hooks.json` PreToolUse | `_UNTRUSTED_HOOK_SUFFIX` | YES |
| `.gemini/settings.json` BeforeTool | `_UNTRUSTED_HOOK_SUFFIX` | YES |
| `.opencode/plugins/graphify.js` (literal string) | inline match of `_UNTRUSTED_HOOK_SUFFIX` text | YES |
| `.agents/workflows/graphify.md` (`_ANTIGRAVITY_WORKFLOW`) | — | NO (see F4) |
| `~/.<plat>/skills/graphify/SKILL.md` (every `skill*.md` file) | — | NO (see F3) |

## Findings

### F1 — `_uninstall_codex_hook` raises `KeyError` on configs missing `hooks` key (BUG)

`graphify/__main__.py:910–924`:

```python
def _uninstall_codex_hook(project_dir: Path) -> None:
    hooks_path = project_dir / ".codex" / "hooks.json"
    if not hooks_path.exists():
        return
    try:
        existing = json.loads(hooks_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return
    pre_tool = existing.get("hooks", {}).get("PreToolUse", [])  # safe read
    filtered = [h for h in pre_tool if "graphify" not in str(h)]
    existing["hooks"]["PreToolUse"] = filtered                  # ← KeyError when 'hooks' is absent
    hooks_path.write_text(json.dumps(existing, indent=2), encoding="utf-8")
    _audit_hook_uninstall("codex", [hooks_path])
```

If `.codex/hooks.json` is valid JSON but has no top-level `hooks` key (e.g. user has a Codex config with only their own root keys), the assignment on the line marked above raises `KeyError`.

The matching `_uninstall_gemini_hook` (`__main__.py:402–417`) has the right pattern: it computes `filtered`, returns early if `len(filtered) == len(before_tool)`, and only mutates `settings["hooks"]["BeforeTool"]` after the early-return. Codex was missed.

**Reproduction**: write `{"other": "unrelated"}` to `.codex/hooks.json` and call `_uninstall_codex_hook(Path("."))` — raises `KeyError: 'hooks'`.

**Fix**: mirror the gemini early-return guard. Filed as a separate commit.

### F2 — `install('kiro')` writes a home skill that Kiro doesn't read (UX)

`_PLATFORM_CONFIG["kiro"]["skill_dst"]` is `Path(".kiro") / "skills" / "graphify" / "SKILL.md"`, which `install()` resolves to `~/.kiro/skills/graphify/SKILL.md` (line 245). The Kiro-specific subcommand `_kiro_install(project_dir)` writes to `project_dir / ".kiro" / "skills" / "graphify" / "SKILL.md"` (line 597), i.e. the project-local path.

Kiro IDE reads project-local `.kiro/`. The home install is functionally orphan: nothing reads `~/.kiro/skills/graphify/SKILL.md`. A user who runs `graphify install --platform kiro` thinks they have installed Kiro support but Kiro will not see the skill.

`_check_skill_version` (line 1445) walks every platform's `Path.home() / cfg["skill_dst"]` and warns on version skew, so the orphan home file does at least feed the version-warning system.

This is not a security defect — the worst outcome is that a user expects Kiro to pick up `/graphify` and finds nothing happens. But it is an installer-correctness issue worth surfacing.

**Recommendation**: defer to user. Two paths:
- Remove `kiro` from `_PLATFORM_CONFIG` and route `graphify install --platform kiro` through `_kiro_install(Path("."))` to match the subcommand.
- Or document that `--platform kiro` is a no-op alias and direct users to `graphify kiro install`.

Both options touch upstream's installer surface; the cleaner option (route through `_kiro_install`) reduces divergence and is suggested as part of the 6.2 plan/apply refactor.

### F3 — Skill files do not carry framing themselves; top-level install for non-Claude platforms ships only the skill (DESIGN)

The Phase 3.5 untrusted-data framing was added to the **rules-file** constants. None of the eleven `skill*.md` files carry the framing text:

```
$ grep -c -i "untrusted\|prompt-injection\|FLAGGED" graphify/skill*.md
graphify/skill-aider.md:0
graphify/skill-claw.md:0
graphify/skill-codex.md:0
graphify/skill-copilot.md:0
graphify/skill-droid.md:0
graphify/skill-kiro.md:0
graphify/skill.md:0
graphify/skill-opencode.md:0
graphify/skill-trae.md:0
graphify/skill-vscode.md:0
graphify/skill-windows.md:0
```

For the **subcommand** install path (`graphify <platform> install`) this is acceptable: the subcommand always writes a project-local rules file (CLAUDE.md / AGENTS.md / GEMINI.md / etc.) which carries `_UNTRUSTED_FRAMING` and is the always-on layer the assistant reads on every turn.

For the **top-level** `graphify install --platform <P>` path, the picture differs by platform:

| Platform | Top-level install writes | Framing exposure |
|---|---|---|
| `claude`, `windows` | skill + `~/.claude/CLAUDE.md` registration line | Registration line is just routing — has no framing. Project-local CLAUDE.md (with framing) is only written by the `claude` subcommand. |
| `codex`, `aider`, `copilot`, `claw`, `droid`, `trae`, `trae-cn`, `hermes` | skill only | No rules file → no framing reaches the assistant unless the user separately runs the subcommand. |
| `opencode` | skill + `.opencode/plugins/graphify.js` + `.opencode/opencode.json` (CWD) | Plugin string carries `_UNTRUSTED_HOOK_SUFFIX`. AGENTS.md (with framing) is only written by the `opencode` subcommand. |
| `kiro` | skill (orphan — see F2) | none |
| `antigravity` | skill | none |

A user who runs only `graphify install --platform aider` (for example) gets the skill but never the rules file with framing. The skill file itself describes how to *run* graphify; the assistant gets no instruction to *treat the report as untrusted*.

**This is not strictly a Task 6.1 acceptance failure** — Task 3.5's stated scope was the rules-file constants — but Task 6.1's dimension 5 reads strictly: "every install path's emitted content." Worth surfacing.

**Recommendation**: discuss with user. Three options, in increasing scope:

1. **Documentation only**: print a one-line nudge at the end of `install --platform <P>` for non-Claude platforms saying "to register always-on graphify rules and untrusted-data framing in this project, run `graphify <P> install`."
2. **Add framing to skill files**: thread a short version of `_UNTRUSTED_FRAMING` (likely a 2-3 line summary) into the top of every `skill*.md` so the framing follows the skill wherever it lands.
3. **Merge surfaces**: have `install --platform <P>` also call the subcommand's project-local install, removing the asymmetry. This is the cleanest fix but lands as part of the 6.2 refactor.

### F4 — `_ANTIGRAVITY_WORKFLOW` does not include `_UNTRUSTED_FRAMING` (LOW)

`graphify/__main__.py:563–572`:

```python
_ANTIGRAVITY_WORKFLOW = """\
# Workflow: graphify
**Command:** /graphify
**Description:** Turn any folder of files into a navigable knowledge graph

## Steps
Follow the graphify skill installed at ~/.agents/skills/graphify/SKILL.md to run the full pipeline.

If no path argument is given, use `.` (current directory).
"""
```

This is a how-to-run pointer, not an always-on rules file. Its sibling `_ANTIGRAVITY_RULES` (the always-on file) does carry framing. By design.

Task 6.1 dimension 5 strict reading flags this. **Recommendation**: leave as-is; the rationale is documented here. No fix.

### F5 — Empty parent directories left after uninstall (COSMETIC)

After uninstall, several platforms leave empty parent directories: `.kiro/`, `.kiro/skills/`, `.kiro/steering/`, `.cursor/`, `.cursor/rules/`, `.agents/`, `.agents/rules/`, `.agents/workflows/`, `.github/`, `.opencode/`, `.opencode/plugins/`. Different uninstallers walk different rmdir depths.

Cosmetic. The Task 7.4 round-trip test will need to allow these as exemptions, or the uninstallers will need a uniform "rmdir until non-empty or hits project root" walk. Suggested for resolution alongside the 6.2 refactor.

### F6 — `test_install_opencode` pollutes the dev tree (TEST FOOTGUN)

`tests/test_install.py:35–37`:

```python
def test_install_opencode(tmp_path):
    _install(tmp_path, "opencode")
    assert (tmp_path / ".config" / "opencode" / "skills" / "graphify" / "SKILL.md").exists()
```

`_install` mocks `Path.home()` to `tmp_path` but `install("opencode")` calls `_install_opencode_plugin(Path("."))` (line 270) which writes to **CWD**, not `tmp_path`. Running the test from the dev tree creates / mutates `.opencode/plugins/graphify.js` and `.opencode/opencode.json` in the working tree.

Carrying-over note from Phase 5's CLAUDE.md resume point: the user explicitly asked to keep this flagged for fix-when-convenient.

**Fix**: have the test `monkeypatch.chdir(tmp_path)` (or pass `tmp_path` to a helper that calls `_install_opencode_plugin(tmp_path)` directly). Filed as a separate commit.

## Resolution plan

| Finding | Severity | Action |
|---|---|---|
| F1 — codex uninstall KeyError | bug | Fix in commit `cli: guard codex uninstall against missing hooks key` |
| F2 — kiro home skill orphan | UX | **Deferred to 6.2.** The plan/apply refactor is the right place to route `--platform kiro` through `_kiro_install(Path("."))` and remove the orphan home write. |
| F3 — skill files lack framing | design | **Deferred to 6.2** (option c — merge top-level and subcommand install surfaces). Doing it in 6.1 would inflate the audit task into a major refactor and would need to be reworked when 6.2 lands; 6.2 already restructures install logic into plan/apply, so the surface-merge is a natural fit there. |
| F4 — antigravity workflow no framing | low | Accept as-is, rationale documented |
| F5 — empty parent dirs | cosmetic | Defer to 7.4 round-trip test design |
| F6 — test_install_opencode CWD pollution | test bug | Fix in commit `test: stop test_install_opencode from writing into the dev tree` |

## Acceptance

- All 27 install entry points were verified on dimensions 1–4.
- Idempotency: pass on all 27 paths.
- Round-trip uninstall: pass on all paths modulo the documented stub-files-and-empty-dirs exceptions (F5).
- Hook content: pass on all five hook payloads (no unbounded subprocess, no network, fail mode appropriate to hook type).
- Framing presence: pass on all rules files and all hook commands; F3 and F4 documented.
- F1 and F6 fixed in separate commits accompanying this audit.
- F2 and F3 deferred to Phase 6 Task 6.2 (install plan/apply refactor + `--dry-run`). 6.2's scope picks up: (a) routing `graphify install --platform kiro` through `_kiro_install` so the home-vs-project skill divergence disappears, and (b) merging the top-level and subcommand install surfaces so the rules file (and its `_UNTRUSTED_FRAMING`) lands on every install path, not just the subcommand path.
