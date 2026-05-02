# Thanks

This fork (`graphify-hardened`) exists only because [`safishamsi`](https://github.com/safishamsi) built and maintains the upstream [`graphify`](https://github.com/safishamsi/graphify) project. Every feature this fork inherits — the AST extraction across 25 languages, the Leiden community detection, the multi-platform install paths, the MCP server, the wiki / Obsidian / SVG / GraphML exporters, the 71x token-reduction benchmark, the worked examples — is upstream work. The fork's contribution is narrower: hardening the seams where untrusted input meets the assistant's persistent context.

## Upstream

- Project: <https://github.com/safishamsi/graphify>
- Maintainer: [`safishamsi`](https://github.com/safishamsi)
- License: see upstream `LICENSE` (carried into this fork unchanged).

## Why a fork instead of upstream PRs

The hardening work in this fork was scoped and sequenced as a single coherent plan (see `IMPLEMENTATION_PLAN.md` if checked into your local copy). Threading every change through upstream review while the design was still settling would have stalled the work. Now that the plan is complete, several pieces are reasonable candidates for upstream contribution if `safishamsi` is willing to take them:

- **Prompt-injection containment (Phase 3).** `graphify/injection.py`, the `[FLAGGED — see graphify-out/.flagged.json]` quarantine in `build.build_from_json`, the `provenance: list[str]` field on every node, the untrusted-data framing block in the install rule files, and the `--untrusted-corpus` mode are all upstream-portable. They harden the boundary that exists in upstream by construction (LLM-extracted text is re-injected into the assistant's context on every turn) without changing user-visible behaviour for trusted corpora.
- **`uv.lock` + `audit.yml` (Phase 1).** The lockfile is mostly relevant for fork-internal CI, but the SHA-pinned `pip-audit` + `osv-scanner` workflow is generally useful.
- **Vendored `vis-network` bundle + CSP (Phase 2).** Removes the third-party CDN at HTML render time without changing the user-visible interactive graph.
- **Subprocess + cache hardening (Phase 4).** `--` separator on `git clone` / `git pull`, `urlsplit`-based URL parsing (defends against `;params` smuggling that `urlparse` strips), per-entry SHA256 sidecar on the cache, and the API-key scrubber on Anthropic / OpenAI auth-failure exceptions are all small, well-scoped patches.

The `--untrusted-corpus` mode in particular feels like the kind of thing that wants to live upstream rather than in a fork: it is a small amount of code (`graphify/untrusted.py` plus a CLI flag) that materially reduces the blast radius of running graphify on a freshly cloned repo, and it is opt-in by default.

## Other prior art

- **vis.js / vis-network** — the visualisation layer the fork now vendors at version `10.0.2` (npm `dist.shasum` + `dist.integrity` verified).
- **NetworkX**, **graspologic** (Leiden), **tree-sitter** — the graph and parsing primitives.
- **uv** by Astral — the Python package + lock manager this fork standardises on.
- **`pip-audit`** (PyPA) and **`osv-scanner`** (Google) — the two CVE scanners pinned in `audit.yml`.
