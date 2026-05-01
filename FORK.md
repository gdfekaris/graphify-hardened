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

#### Rationale for dropping `[video]`

The `[video]` extra turns graphify from "parses local code and docs" into "downloads arbitrary media from arbitrary URLs and feeds it to two complex C/Python parsers." That is a categorical jump in attack surface that is not justified by the user's intended use, which does not include video/audio ingestion. Specifically:

- **yt-dlp** has a long history of CVEs, particularly around argument injection (the `--exec` family runs shell commands post-download), output-template substitution, and parsers for site-specific extractors. The plan's Task 4.6 sandboxing recipe (URL after `--`, forced `--no-exec`/`--no-call-home`/`--no-update`, hard timeout, bounded output dir) addresses the known classes but not future bugs in extractor code. Dropping eliminates the entire class.
- **faster-whisper** downloads model weights from `huggingface.co` on first run, leaking the user's IP and chosen model size to a third party and loading code/data from that third party into the process. It uses CTranslate2 (not raw PyTorch pickle), which avoids the classic pickle-checkpoint-as-RCE vector, but the runtime download is still a trust extension we don't need.
- **ffmpeg** (transitive, invoked by both packages) is not a Python dependency but a system binary with a massive memory-corruption surface in its container and codec parsers. Hostile media files have repeatedly led to ffmpeg CVEs. Subprocess argument hardening does not mitigate this — only sandboxing (firejail/bubblewrap/container) or "don't feed it untrusted media" does, and neither is in scope for this fork.

If the user later needs video/audio ingestion, the right path is to install the necessary tooling explicitly outside this fork (e.g., transcribe locally, then point graphify at the resulting text), or to introduce a sandboxed video-ingest task as a separate hardened plan.

## Upstream cherry-pick process

(Placeholder — to be filled in at Phase 8 of the implementation plan.)

## Public release trigger

This fork goes public when:

- (a) the lockfile lands and is verified
- (b) the SRI/vendoring patch is applied and tested
- (c) the prompt-injection containment from Phase 3 is in place
- (d) the subprocess and cache audits from Phase 4 are clean
- (e) the audit logger from Phase 5 is wired in with fail-loud semantics for security events
- (f) the test suite passes including the new hardening tests in Phase 7

Until then, it remains private.
