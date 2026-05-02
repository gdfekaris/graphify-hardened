# graphify-hardened

> **This is a hardened fork of [safishamsi/graphify](https://github.com/safishamsi/graphify).** For the upstream project and its features, see the original repo. The text up to the next "Hardened-fork additions" divider is the upstream README, lightly edited to remove references to dropped extras. The fork-specific material is at the bottom: [Differences from upstream](#differences-from-upstream), [When to use this fork vs. upstream](#when-to-use-this-fork-vs-upstream), [Trust model](#trust-model), [Environment variables](#environment-variables-hardened-fork-additions), and [CLI additions](#cli-additions-hardened-fork).
>
> **Working baseline:** upstream commit `0999822` (one commit past `v0.5.7`). See [`FORK.md`](FORK.md) for the per-extra keep/drop rationale and the upstream cherry-pick review process.

---

**An AI coding assistant skill.** Type `/graphify` in Claude Code, Codex, OpenCode, Cursor, Gemini CLI, GitHub Copilot CLI, VS Code Copilot Chat, Aider, OpenClaw, Factory Droid, Trae, Hermes, Kiro, or Google Antigravity - it reads your files, builds a knowledge graph, and gives you back structure you didn't know was there. Understand a codebase faster. Find the "why" behind architectural decisions.

Fully multimodal. Drop in code, PDFs, markdown, screenshots, diagrams, whiteboard photos, or images in other languages - graphify extracts concepts and relationships from all of it and connects them into one graph. YAML/YML files (Kubernetes, Kustomize, Helm, config) are indexed for semantic extraction. 25 languages supported via tree-sitter AST (Python, JS, TS, Go, Rust, Java, C, C++, Ruby, C#, Kotlin, Scala, PHP, Swift, Lua, Zig, PowerShell, Elixir, Objective-C, Julia, Verilog, SystemVerilog, Vue, Svelte, Dart).

> Andrej Karpathy keeps a `/raw` folder where he drops papers, tweets, screenshots, and notes. graphify is the answer to that problem - 71.5x fewer tokens per query vs reading the raw files, persistent across sessions, honest about what it found vs guessed.

```
/graphify .                        # works on any folder - your codebase, notes, papers, anything
```

```
graphify-out/
├── graph.html       interactive graph - open in any browser, click nodes, search, filter by community
├── GRAPH_REPORT.md  god nodes, surprising connections, suggested questions
├── graph.json       persistent graph - query weeks later without re-reading
└── cache/           SHA256 cache - re-runs only process changed files
```

Add a `.graphifyignore` file to exclude folders you don't want in the graph:

```
# .graphifyignore
vendor/
node_modules/
dist/
*.generated.py
```

Same syntax as `.gitignore`. You can keep a single `.graphifyignore` at your repo root — patterns work correctly even when graphify is run on a subfolder.

## How it works

graphify runs in two passes. First, a deterministic AST pass extracts structure from code files (classes, functions, imports, call graphs, docstrings, rationale comments) with no LLM needed. Second, Claude subagents run in parallel over docs, papers, and images to extract concepts, relationships, and design rationale. The results are merged into a NetworkX graph, clustered with Leiden community detection, and exported as interactive HTML, queryable JSON, and a plain-language audit report.

**Clustering is graph-topology-based — no embeddings.** Leiden finds communities by edge density. The semantic similarity edges that Claude extracts (`semantically_similar_to`, marked INFERRED) are already in the graph, so they influence community detection directly. The graph structure is the similarity signal — no separate embedding step or vector database needed.

Every relationship is tagged `EXTRACTED` (found directly in source), `INFERRED` (reasonable inference, with a confidence score), or `AMBIGUOUS` (flagged for review). You always know what was found vs guessed.

## Install

**Requires:** Python 3.10+ and one of: [Claude Code](https://claude.ai/code), [Codex](https://openai.com/codex), [OpenCode](https://opencode.ai), [Cursor](https://cursor.com), [Gemini CLI](https://github.com/google-gemini/gemini-cli), [GitHub Copilot CLI](https://docs.github.com/en/copilot/how-tos/copilot-cli), [VS Code Copilot Chat](https://code.visualstudio.com/docs/copilot/overview), [Aider](https://aider.chat), [OpenClaw](https://openclaw.ai), [Factory Droid](https://factory.ai), [Trae](https://trae.ai), [Kiro](https://kiro.dev), Hermes, or [Google Antigravity](https://antigravity.google)

```bash
# Recommended — works on Mac and Linux with no PATH setup needed
uv tool install graphifyy && graphify install
# or with pipx
pipx install graphifyy && graphify install
# or plain pip
pip install graphifyy && graphify install
```

> **Official package:** The PyPI package is named `graphifyy` (install with `pip install graphifyy`). Other packages named `graphify*` on PyPI are not affiliated with this project. The only official repository is [safishamsi/graphify](https://github.com/safishamsi/graphify). The CLI and skill command are still `graphify`.

> **`graphify: command not found`?** Use `uv tool install graphifyy` (recommended) or `pipx install graphifyy` — both put the CLI in a managed location that's automatically on PATH. With plain `pip`, you may need to add `~/.local/bin` (Linux) or `~/Library/Python/3.x/bin` (Mac) to your PATH, or run `python -m graphify` instead. On Windows, pip scripts land in `%APPDATA%\Python\PythonXY\Scripts`.

### Platform support

| Platform | Install command |
|----------|----------------|
| Claude Code (Linux/Mac) | `graphify install` |
| Claude Code (Windows) | `graphify install` (auto-detected) or `graphify install --platform windows` |
| Codex | `graphify install --platform codex` |
| OpenCode | `graphify install --platform opencode` |
| GitHub Copilot CLI | `graphify install --platform copilot` |
| VS Code Copilot Chat | `graphify vscode install` |
| Aider | `graphify install --platform aider` |
| OpenClaw | `graphify install --platform claw` |
| Factory Droid | `graphify install --platform droid` |
| Trae | `graphify install --platform trae` |
| Trae CN | `graphify install --platform trae-cn` |
| Gemini CLI | `graphify install --platform gemini` |
| Hermes | `graphify install --platform hermes` |
| Kiro IDE/CLI | `graphify kiro install` |
| Cursor | `graphify cursor install` |
| Google Antigravity | `graphify antigravity install` |

Codex users also need `multi_agent = true` under `[features]` in `~/.codex/config.toml` for parallel extraction. Factory Droid uses the `Task` tool for parallel subagent dispatch. OpenClaw and Aider use sequential extraction (parallel agent support is still early on those platforms). Trae uses the Agent tool for parallel subagent dispatch and does **not** support PreToolUse hooks — AGENTS.md is the always-on mechanism. Codex supports PreToolUse hooks — `graphify codex install` installs one in `.codex/hooks.json` in addition to writing AGENTS.md.

Then open your AI coding assistant and type:

```
/graphify .
```

Note: Codex uses `$` instead of `/` for skill calling, so type `$graphify .` instead.

### Make your assistant always use the graph (recommended)

After building a graph, run this once in your project:

| Platform | Command |
|----------|---------|
| Claude Code | `graphify claude install` |
| Codex | `graphify codex install` |
| OpenCode | `graphify opencode install` |
| GitHub Copilot CLI | `graphify copilot install` |
| VS Code Copilot Chat | `graphify vscode install` |
| Aider | `graphify aider install` |
| OpenClaw | `graphify claw install` |
| Factory Droid | `graphify droid install` |
| Trae | `graphify trae install` |
| Trae CN | `graphify trae-cn install` |
| Cursor | `graphify cursor install` |
| Gemini CLI | `graphify gemini install` |
| Hermes | `graphify hermes install` |
| Kiro IDE/CLI | `graphify kiro install` |
| Google Antigravity | `graphify antigravity install` |

**Claude Code** does two things: writes a `CLAUDE.md` section telling Claude to read `graphify-out/GRAPH_REPORT.md` before answering architecture questions, and installs a **PreToolUse hook** (`settings.json`) that fires before every Glob and Grep call. If a knowledge graph exists, Claude sees: _"graphify: Knowledge graph exists. Read GRAPH_REPORT.md for god nodes and community structure before searching raw files."_ — so Claude navigates via the graph instead of grepping through every file.

**Codex** writes to `AGENTS.md` and also installs a **PreToolUse hook** in `.codex/hooks.json` that fires before every Bash tool call — same always-on mechanism as Claude Code.

**OpenCode** writes to `AGENTS.md` and also installs a **`tool.execute.before` plugin** (`.opencode/plugins/graphify.js` + `opencode.json` registration) that fires before bash tool calls and injects the graph reminder into tool output when the graph exists.

**Cursor** writes `.cursor/rules/graphify.mdc` with `alwaysApply: true` — Cursor includes it in every conversation automatically, no hook needed.

**Gemini CLI** copies the skill to `~/.gemini/skills/graphify/SKILL.md`, writes a `GEMINI.md` section, and installs a `BeforeTool` hook in `.gemini/settings.json` that fires before file-read tool calls — same always-on mechanism as Claude Code.

**Aider, OpenClaw, Factory Droid, Trae, and Hermes** write the same rules to `AGENTS.md` in your project root and copy the skill to the platform's global skill directory. These platforms don't support tool hooks, so AGENTS.md is the always-on mechanism.

**Kiro IDE/CLI** writes the skill to `.kiro/skills/graphify/SKILL.md` (invoked via `/graphify`) and a steering file to `.kiro/steering/graphify.md` with `inclusion: always` — Kiro injects this into every conversation automatically, no hook needed.

**Google Antigravity** writes `.agents/rules/graphify.md` (always-on rules) and `.agents/workflows/graphify.md` (registers `/graphify` as a slash command). No hook equivalent exists in Antigravity — rules are the always-on mechanism.

**GitHub Copilot CLI** copies the skill to `~/.copilot/skills/graphify/SKILL.md`. Run `graphify copilot install` to set it up.

**VS Code Copilot Chat** installs a Python-only skill (works on Windows PowerShell and macOS/Linux alike) and writes `.github/copilot-instructions.md` in your project root — VS Code reads this automatically every session, making graph context always-on without any hook mechanism. Run `graphify vscode install`. Note: this configures the chat panel in VS Code, not the Copilot CLI terminal tool.

Uninstall with the matching uninstall command (e.g. `graphify claude uninstall`).

**Always-on vs explicit trigger — what's the difference?**

The always-on hook surfaces `GRAPH_REPORT.md` — a one-page summary of god nodes, communities, and surprising connections. Your assistant reads this before searching files, so it navigates by structure instead of keyword matching. That covers most everyday questions.

`/graphify query`, `/graphify path`, and `/graphify explain` go deeper: they traverse the raw `graph.json` hop by hop, trace exact paths between nodes, and surface edge-level detail (relation type, confidence score, source location). Use them when you want a specific question answered from the graph rather than a general orientation.

Think of it this way: the always-on hook gives your assistant a map. The `/graphify` commands let it navigate the map precisely.

### Team workflows

`graphify-out/` is designed to be committed to git so every teammate starts with a fresh map.

**Recommended `.gitignore` additions:**
```
# keep graph outputs, skip heavy/local-only files

# optional: commit for shared extraction speed, skip to keep repo small
graphify-out/cache/

# mtime-based, invalid after git clone - always gitignore this
graphify-out/manifest.json

# local token tracking, not useful to share
graphify-out/cost.json
```

**Shared setup:**
1. One person runs `/graphify .` to build the initial graph and commits `graphify-out/`.
2. Everyone else pulls — their assistant reads `GRAPH_REPORT.md` immediately with no extra steps.
3. Install the post-commit hook (`graphify hook install`) so the graph rebuilds automatically after code changes — no LLM calls needed for code-only updates.
4. For doc/paper changes, whoever edits the files runs `/graphify --update` to refresh semantic nodes.

**Excluding paths** — create `.graphifyignore` in your project root (same syntax as `.gitignore`). Files matching those patterns are skipped during detection and extraction.

```
# .graphifyignore example
AGENTS.md          # graphify install files — don't extract your own instructions as knowledge
CLAUDE.md
GEMINI.md
.gemini/
.opencode/
docs/translations/ # generated content you don't want in the graph
```

## Using `graph.json` with an LLM

`graph.json` is not meant to be pasted into a prompt all at once. The useful
workflow is:

1. Start with `graphify-out/GRAPH_REPORT.md` for the high-level overview.
2. Use `graphify query` to pull a smaller subgraph for the specific question
   you want to answer.
3. Give that focused output to your assistant instead of dumping the full raw
   corpus.

For example, after running graphify on a project:

```bash
graphify query "show the auth flow" --graph graphify-out/graph.json
graphify query "what connects DigestAuth to Response?" --graph graphify-out/graph.json
```

The output includes node labels, edge types, confidence tags, source files, and
source locations. That makes it a good intermediate context block for an LLM:

```text
Use this graph query output to answer the question. Prefer the graph structure
over guessing, and cite the source files when possible.
```

If your assistant supports tool calling or MCP, use the graph directly instead
of pasting text. graphify can expose `graph.json` as an MCP server:

```bash
python -m graphify.serve graphify-out/graph.json
```

That gives the assistant structured graph access for repeated queries such as
`query_graph`, `get_node`, `get_neighbors`, and `shortest_path`.

> **WSL / Linux note:** Ubuntu ships `python3`, not `python`. Install into a project venv to avoid PEP 668 conflicts, and use the full venv path in your `.mcp.json`:
> ```bash
> python3 -m venv .venv && .venv/bin/pip install "graphifyy[mcp]"
> ```
> ```json
> { "mcpServers": { "graphify": { "type": "stdio", "command": ".venv/bin/python3", "args": ["-m", "graphify.serve", "graphify-out/graph.json"] } } }
> ```
> Also note: the PyPI package is `graphifyy` (double-y) — `pip install graphify` installs an unrelated package.

<details>
<summary>Manual install (curl)</summary>

```bash
mkdir -p ~/.claude/skills/graphify
curl -fsSL https://raw.githubusercontent.com/safishamsi/graphify/v4/graphify/skill.md \
  > ~/.claude/skills/graphify/SKILL.md
```

Add to `~/.claude/CLAUDE.md`:

```
- **graphify** (`~/.claude/skills/graphify/SKILL.md`) - any input to knowledge graph. Trigger: `/graphify`
When the user types `/graphify`, invoke the Skill tool with `skill: "graphify"` before doing anything else.
```

</details>

## Usage

```
/graphify                          # run on current directory
/graphify ./raw                    # run on a specific folder
/graphify ./raw --mode deep        # more aggressive INFERRED edge extraction
/graphify ./raw --update           # re-extract only changed files, merge into existing graph
/graphify ./raw --directed          # build directed graph (preserves edge direction: source→target)
/graphify ./raw --cluster-only     # rerun clustering on existing graph, no re-extraction
/graphify ./raw --no-viz           # skip HTML, just produce report + JSON
/graphify ./raw --obsidian                          # also generate Obsidian vault (opt-in)
/graphify ./raw --obsidian --obsidian-dir ~/vaults/myproject  # write vault to a specific directory

/graphify add https://arxiv.org/abs/1706.03762        # fetch a paper, save, update graph
/graphify add https://x.com/karpathy/status/...       # fetch a tweet
/graphify add https://... --author "Name"             # tag the original author
/graphify add https://... --contributor "Name"        # tag who added it to the corpus

/graphify query "what connects attention to the optimizer?"
/graphify query "what connects attention to the optimizer?" --dfs   # trace a specific path
/graphify query "what connects attention to the optimizer?" --budget 1500  # cap at N tokens
/graphify path "DigestAuth" "Response"
/graphify explain "SwinTransformer"

/graphify ./raw --watch            # auto-sync graph as files change (code: instant, docs: notifies you)
/graphify ./raw --wiki             # build agent-crawlable wiki (index.md + article per community)
/graphify ./raw --svg              # export graph.svg
/graphify ./raw --graphml          # export graph.graphml (Gephi, yEd)
/graphify ./raw --mcp              # start MCP stdio server

# git hooks - platform-agnostic, rebuild graph on commit and branch switch
graphify hook install
graphify hook uninstall
graphify hook status

# always-on assistant instructions - platform-specific
graphify claude install            # CLAUDE.md + PreToolUse hook (Claude Code)
graphify claude uninstall
graphify codex install             # AGENTS.md + PreToolUse hook in .codex/hooks.json (Codex)
graphify opencode install          # AGENTS.md + tool.execute.before plugin (OpenCode)
graphify cursor install            # .cursor/rules/graphify.mdc (Cursor)
graphify cursor uninstall
graphify gemini install            # GEMINI.md + BeforeTool hook (Gemini CLI)
graphify gemini uninstall
graphify copilot install           # skill file (GitHub Copilot CLI)
graphify copilot uninstall
graphify aider install             # AGENTS.md (Aider)
graphify aider uninstall
graphify claw install              # AGENTS.md (OpenClaw)
graphify droid install             # AGENTS.md (Factory Droid)
graphify trae install              # AGENTS.md (Trae)
graphify trae uninstall
graphify trae-cn install           # AGENTS.md (Trae CN)
graphify trae-cn uninstall
graphify hermes install             # AGENTS.md + ~/.hermes/skills/ (Hermes)
graphify hermes uninstall
graphify kiro install               # .kiro/skills/ + .kiro/steering/graphify.md (Kiro IDE/CLI)
graphify kiro uninstall
graphify antigravity install       # .agents/rules + .agents/workflows (Google Antigravity)
graphify antigravity uninstall

# query and navigate the graph directly from the terminal (no AI assistant needed)
graphify query "what connects attention to the optimizer?"
graphify query "show the auth flow" --dfs
graphify query "what is CfgNode?" --budget 500
graphify query "..." --graph path/to/graph.json
graphify path "DigestAuth" "Response"       # shortest path between two nodes
graphify explain "SwinTransformer"           # plain-language explanation of a node

# add content and update the graph from the terminal
graphify add https://arxiv.org/abs/1706.03762          # fetch paper, save to ./raw, update graph
graphify add https://... --author "Name" --contributor "Name"

# clone any GitHub repo and run the full pipeline on it
graphify clone https://github.com/karpathy/nanoGPT    # clones to ~/.graphify/repos/karpathy/nanoGPT
graphify clone https://github.com/org/repo --branch dev --out ./my-clone

# cross-repo graphs — merge two or more graph.json outputs into one
graphify merge-graphs repo1/graphify-out/graph.json repo2/graphify-out/graph.json
graphify merge-graphs g1.json g2.json g3.json --out cross-repo.json

# incremental update and maintenance
graphify watch ./src                         # auto-rebuild on code changes
graphify check-update ./src                  # check if semantic re-extraction is pending (cron-safe)
graphify update ./src                        # re-extract code files, no LLM needed
graphify cluster-only ./my-project           # rerun clustering on existing graph.json

# untrusted-corpus mode — first-pass exploration of a freshly cloned repo
# Skips every LLM call. Code goes through the AST extractor as usual; docs,
# papers, and images become metadata-only nodes (path + size + sha256 + type)
# with no content read. The resulting graph is structurally smaller but
# carries zero LLM-generated text from the corpus, so a hostile README or
# paper cannot inject instructions into your assistant. Re-run without
# the flag once you have read the contents and trust the corpus.
graphify update ./untrusted-clone --untrusted-corpus
graphify watch  ./untrusted-clone --untrusted-corpus

# `graphify add <url>` refuses to extend a graph that was built in
# --untrusted-corpus mode unless --force is given.
graphify add https://example.com/x --force

# dry-run any install command — print the plan (CREATE / MODIFY with unified diff / NO-OP)
# without touching the filesystem. Every install entry point accepts --dry-run.
graphify install --dry-run
graphify claude install --dry-run
graphify codex install --dry-run

# audit summary — flagged content (recent 5), graph mode (standard / UNTRUSTED-CORPUS),
# recent 10 audit events, installed skills, git hooks
graphify status
graphify status --show-flagged-text     # surface original quarantined text (off by default)
```

Works with any mix of file types:

| Type | Extensions | Extraction |
|------|-----------|------------|
| Code | `.py .ts .js .jsx .tsx .mjs .go .rs .java .c .cpp .rb .cs .kt .scala .php .swift .lua .zig .ps1 .ex .exs .m .mm .jl .vue .svelte` | AST via tree-sitter + call-graph (cross-file for all languages) + Java extends/implements + docstring/comment rationale |
| Docs | `.md .mdx .html .txt .rst .yaml .yml` | Concepts + relationships + design rationale via Claude |
| Office | `.docx .xlsx` | Converted to markdown then extracted via Claude (requires `pip install graphifyy[office]`) |
| Papers | `.pdf` | Citation mining + concept extraction |
| Images | `.png .jpg .webp .gif` | Claude vision - screenshots, diagrams, any language |

## What you get

**God nodes** - highest-degree concepts (what everything connects through)

**Surprising connections** - ranked by composite score. Code-paper edges rank higher than code-code. Each result includes a plain-English why.

**Suggested questions** - 4-5 questions the graph is uniquely positioned to answer

**The "why"** - docstrings, inline comments (`# NOTE:`, `# IMPORTANT:`, `# HACK:`, `# WHY:`), and design rationale from docs are extracted as `rationale_for` nodes. Not just what the code does - why it was written that way.

**Confidence scores** - every INFERRED edge has a `confidence_score` (0.0-1.0). You know not just what was guessed but how confident the model was. EXTRACTED edges are always 1.0.

**Semantic similarity edges** - cross-file conceptual links with no structural connection. Two functions solving the same problem without calling each other, a class in code and a concept in a paper describing the same algorithm.

**Hyperedges** - group relationships connecting 3+ nodes that pairwise edges can't express. All classes implementing a shared protocol, all functions in an auth flow, all concepts from a paper section forming one idea.

**Token benchmark** - printed automatically after every run. On a mixed corpus (Karpathy repos + papers + images): **71.5x** fewer tokens per query vs reading raw files. The first run extracts and builds the graph (this costs tokens). Every subsequent query reads the compact graph instead of raw files — that's where the savings compound. The SHA256 cache means re-runs only re-process changed files.

**Auto-sync** (`--watch`) - run in a background terminal and the graph updates itself as your codebase changes. Code file saves trigger an instant rebuild (AST only, no LLM). Doc/image changes notify you to run `--update` for the LLM re-pass.

**Git hooks** (`graphify hook install`) - installs post-commit and post-checkout hooks. Graph rebuilds automatically after every commit and every branch switch. If a rebuild fails, the hook exits with a non-zero code so git surfaces the error instead of silently continuing. No background process needed.

**Wiki** (`--wiki`) - Wikipedia-style markdown articles per community and god node, with an `index.md` entry point. Point any agent at `index.md` and it can navigate the knowledge base by reading files instead of parsing JSON.

## Worked examples

| Corpus | Files | Reduction | Output |
|--------|-------|-----------|--------|
| Karpathy repos + 5 papers + 4 images | 52 | **71.5x** | [`worked/karpathy-repos/`](worked/karpathy-repos/) |
| graphify source + Transformer paper | 4 | **5.4x** | [`worked/mixed-corpus/`](worked/mixed-corpus/) |
| httpx (synthetic Python library) | 6 | ~1x | [`worked/httpx/`](worked/httpx/) |

Token reduction scales with corpus size. 6 files fits in a context window anyway, so graph value there is structural clarity, not compression. At 52 files (code + papers + images) you get 71x+. Each `worked/` folder has the raw input files and the actual output (`GRAPH_REPORT.md`, `graph.json`) so you can run it yourself and verify the numbers.

## Privacy

graphify sends file contents to your AI coding assistant's underlying model API for semantic extraction of docs, papers, and images — Anthropic (Claude Code), OpenAI (Codex), or whichever provider your platform uses. Code files are processed locally via tree-sitter AST — no file contents leave your machine for code. No telemetry, usage tracking, or analytics of any kind. The only network calls are to your platform's model API during extraction, using your own API key.

## Tech stack

NetworkX + Leiden (graspologic) + tree-sitter + vis.js. Semantic extraction via Claude (Claude Code), GPT-4 (Codex), or whichever model your platform runs. No Neo4j required, no server, runs entirely locally.

## Built on graphify — Penpax

[**Penpax**](https://safishamsi.github.io/penpax.ai) is the enterprise layer on top of graphify. Where graphify turns a folder of files into a knowledge graph, Penpax applies the same graph to your entire working life — continuously.

| | graphify | Penpax |
|---|---|---|
| Input | A folder of files | Browser history, meetings, emails, files, code — everything |
| Runs | On demand | Continuously in the background |
| Scope | A project | Your entire working life |
| Query | CLI / MCP / AI skill | Natural language, always on |
| Privacy | Local by default | Fully on-device, no cloud |

Built for lawyers, consultants, executives, doctors, researchers — anyone whose work lives across hundreds of conversations and documents they can never fully reconstruct.

**Free trial launching soon.** [Join the waitlist →](https://safishamsi.github.io/penpax.ai)

## What we are building next

graphify is the graph layer. Penpax is the always-on layer on top of it — an on-device digital twin that connects your meetings, browser history, files, emails, and code into one continuously updating knowledge graph. No cloud, no training on your data. [Join the waitlist.](https://safishamsi.github.io/penpax.ai)

---

# Hardened-fork additions

The sections below describe how `graphify-hardened` differs from upstream `safishamsi/graphify`. Everything above this divider is upstream content.

## Differences from upstream

The fork's working baseline is upstream commit `0999822` (one commit past `v0.5.7`). Each entry below names the implementing change; commit SHAs are on the `development` branch of this repo.

**Phase 0 — Reduced optional-extra surface**

- Dropped `[neo4j]` (pure export target; one fewer network-protocol-speaking dependency).
- Dropped `[video]` (`yt-dlp` + `faster-whisper`): the user does not ingest media; the attack surface (yt-dlp `--exec` family CVE history, `huggingface.co` runtime model fetch, transitive `ffmpeg` codec parsers) is not justified. See `FORK.md`.
- Dropped `[kimi]`: routes extraction through a second LLM provider; keeping a single trust surface.
- Kept: `mcp`, `pdf`, `watch`, `svg`, `leiden`, `office`.

**Phase 1 — Dependency hardening**

- `uv.lock` committed (105 packages resolved against Python 3.11) and removed from `.gitignore`.
- Version specifiers tightened in `pyproject.toml`: tree-sitter language parsers pinned `==`, everything else lower+upper bounded.
- New `.github/workflows/audit.yml` runs weekly + on PRs into `development` + manually, scanning the locked tree with `pip-audit==2.10.0` and `osv-scanner v2.3.5` (release binary, SHA256-verified). GitHub Actions SHA-pinned in both `audit.yml` and `ci.yml`.

**Phase 2 — Vendored vis-network bundle**

- The interactive HTML output no longer loads `vis-network` from a third-party CDN. `vis-network@10.0.2` is vendored at `graphify/static/vis-network.min.js` after verifying the npm-published `dist.shasum` (sha1) and `dist.integrity` (sha512) against the downloaded bytes (`audit/vis-network-pin.txt`). Loaded via `importlib.resources` with a `</script` substring guard.
- Added `_safe_href` helper for any future hyperlink emission and a `<meta http-equiv="Content-Security-Policy">` block to the generated HTML (`default-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'none'; object-src 'none'; base-uri 'none'`; `'unsafe-eval'` intentionally omitted).
- Routed edge `relation` / `confidence` and hyperedge `label` through `sanitize_label()`. Adversarial regression test in `tests/test_export.py`.

**Phase 3 — Prompt-injection containment**

- New `graphify/injection.py` with `flag_suspicious(text)` and 12 named heuristic patterns (imperative-ignore, role-injection markup, exfiltration instructions, jailbreak phrases, persona overrides).
- `build.build_from_json` is the central choke point: free-text fields (label, rationale, summary) on every node are scanned; flagged content is redacted to `[FLAGGED — see graphify-out/.flagged.json]`, the node is tagged `flagged: True`, and the original is appended to `.flagged.json` with provenance and matched-pattern names.
- Every node now carries `provenance: list[str]` (defaults to `[source_file]`); merges union provenance instead of overwriting.
- An "untrusted-data framing" block is embedded in all 7 rules-file install constants and threaded into the 4 inline hook nudges. MCP `serve.py` prepends an untrusted-data prefix to every text-bearing handler (numeric-only handlers exempted).
- New `--untrusted-corpus` mode for `graphify update` and `graphify watch` (and `graphify add` refuses to extend such a graph without `--force`). LLM-free: code goes through the AST extractor as usual; docs, papers, and images become metadata-only nodes (path + size + SHA256 + file_type — file contents are never read).

**Phase 4 — External-input hardening**

- `safe_fetch` gains a `GRAPHIFY_FETCH_ALLOWLIST` hostname allowlist (after the existing scheme/IP-range checks).
- Default text-fetch cap lowered from 10 MB to 2 MB; `GRAPHIFY_MAX_TEXT_BYTES` env override clamped to a 50 MB hard ceiling.
- Per-URL-type Content-Type validation in `ingest`; `GRAPHIFY_CONTENT_TYPE_STRICT=0` downgrades enforcement to a `RuntimeWarning`.
- `git clone` / `git pull` URLs parsed with `urlsplit` (not `urlparse`, which strips `;params` from HTTP/HTTPS paths), owner/repo validated against `^[a-zA-Z0-9._-]+$` plus an explicit dot-only check, optional `GRAPHIFY_CLONE_ALLOWED_HOSTS` / `GRAPHIFY_CLONE_ALLOWED_OWNERS` gates, `--` separator before positional args, and 5 s / 300 s timeouts on the three subprocess sites (`audit/subprocess-review.md`).
- Cache deserialization audit: zero pickle/marshal/dill/joblib usage; JSON-only with quiet demotion to a cache miss on malformed entries (`audit/deserialization-review.md`). Per-entry SHA256 sidecar (`<hash>.json.sha256`); hash mismatch logs an integrity event and treats the entry as a miss.
- PDF parsing pre-checks file size (`GRAPHIFY_PDF_MAX_BYTES`, default 100 MB) and lowers `RLIMIT_AS` (`GRAPHIFY_PDF_MEMORY_CAP_BYTES`, default 2 GB) on Unix for the duration of pypdf parsing. Office (`.docx` / `.xlsx`) zip central directories are inspected before any decompression — non-zip files, archives over `GRAPHIFY_OFFICE_MAX_UNCOMPRESSED_BYTES` (default 200 MB), and archives with more than 10 000 entries are rejected (`audit/office-pdf-hardening.md`).
- Anthropic / OpenAI SDK exceptions on auth failure are scrubbed of the API-key value before re-raising; chain-walking loggers do not see the original (`audit/api-key-handling-review.md`).

**Phase 5 — Audit log**

- New `graphify/audit.py`: `log_event` (best-effort) and `log_security_event` (fail-loud — file failure → stderr fallback → `AuditLogError` if both fail). Atomic append via `os.write` under `fcntl.flock(LOCK_EX)` on Unix; bare `O_APPEND` on Windows. Recursive secret-scrubbing (Bearer, `sk-`, `sk-ant-`, `gh[ps]_`, generic 32+ char tokens) applied to every record. Format and the per-action `details` allowlist documented in [`docs/AUDIT_LOG.md`](docs/AUDIT_LOG.md).
- Wired into nine action families: `fetch_url`, `content_type_violation`, `quarantine_flagged`, `cache_integrity_failure`, `clone_repo`, `subprocess`, `install_hook` / `uninstall_hook`, `install_skill` / `uninstall_skill`.
- New `graphify status` command surfaces the audit and quarantine state at a glance (flagged content, graph mode, recent 10 audit events, installed skills, git hooks).

**Phase 6 — Skill installer hardening**

- `graphify install --dry-run` plans every install action (CREATE / MODIFY with unified diff / NO-OP) without touching the filesystem. Every install entry point splits into `plan_<X>()` + `<X>()`.
- Top-level `graphify install --platform <P>` for kiro / cursor / gemini / antigravity now routes through the dedicated subcommand entirely (eliminates orphan home-skill writes that those platforms never read); for codex / opencode / aider / claw / droid / trae / trae-cn / hermes the top-level chains into `_agents_install` after the home skill copy so the framing-bearing rules file always lands.
- Idempotent uninstall fix for codex (`_agents_uninstall(_, platform="codex")` now removes the codex hook from `.codex/hooks.json`, mirroring the opencode branch).

**Phase 7 — Hardening regression tests**

+70 tests covering: SSRF redirect chains (`file://`, RFC1918, IMDS, link-local, A→B→metadata), `uv.lock` drift, vendored-bundle adversarial HTML, install round-trip cleanup, prompt-injection end-to-end (build → `graph.json` → MCP), subprocess argument-injection vectors (shell metachars, option-prefix smuggling, SCP-form, path traversal, missing `--`, missing timeouts), cache deserialization (AST scan + tamper + pickle-gadget under tripwires), audit-logger fail-loud + scrubbing.

## When to use this fork vs. upstream

**Use upstream `safishamsi/graphify`** if you want the fastest release cadence, all optional features (including `[neo4j]`, `[video]`, `[kimi]`), the original interactive HTML built around the `vis-network` CDN, and you are comfortable with the LLM-extraction model running over arbitrary corpus content.

**Use this fork** if any of the following matter to you:

- You run graphify on third-party content you do not fully trust (open-source repos, scraped papers, downloaded archives) and want indirect prompt injection through extracted nodes contained rather than ignored.
- You want a committed `uv.lock`, dependency CVE scanning in CI, and a reduced optional-extra surface.
- You want a vendored `vis-network` bundle (no third-party CDN at HTML render time) with CSP applied to the generated output.
- You want an audit log of security-relevant operations (URL fetches, repo clones, skill installs, cache integrity failures).
- You want a `--dry-run` flag on every install path and a `graphify status` command to inspect flagged content, audit history, and installed surfaces.

**Tradeoffs.** Slower release cadence — upstream changes are pulled in monthly by manual cherry-pick after diff review (see [`FORK.md`](FORK.md)). No `[video]` / `[kimi]` / `[neo4j]` extras. The default `safe_fetch_text` cap is lower (2 MB vs. upstream 10 MB; raise via `GRAPHIFY_MAX_TEXT_BYTES`). The audit log is **not tamper-evident**; an attacker with local write access to `graphify-out/.audit.log` can rewrite history. Tamper-evidence (HMAC chain, remote shipping) is out of scope for a local-only tool.

**Use neither** if you process untrusted media (audio/video files from arbitrary sources). The upstream `[video]` extra is dropped here, and neither fork sandboxes ffmpeg / yt-dlp at the OS level.

## Trust model

**Running graphify on third-party content gives that content's authors persistent injection access to your assistant via the always-on hook.** Every file in the corpus passes through an LLM-extraction stage; the resulting node labels, rationale text, community names, and summaries are persisted to `GRAPH_REPORT.md` and re-injected into your assistant's context on every turn. A hostile README, paper, or image caption can plant instructions that the assistant sees indefinitely.

This fork mitigates this with three layered defences:

1. **Heuristic flagging at build time** (`graphify/injection.py`) scans every free-text field for 12 known injection-pattern families (imperative-ignore, role-injection markup, exfiltration instructions, jailbreak phrases, persona overrides) and redacts matches to a quarantine placeholder. The original is recorded in `graphify-out/.flagged.json` with provenance and matched-pattern names.
2. **Untrusted-data framing** is embedded in every rules file installed by `graphify *install` (CLAUDE.md, AGENTS.md, GEMINI.md, `.cursor/rules/`, `.kiro/steering/`, `.agents/rules/`, `.github/copilot-instructions.md`) telling the assistant to treat the report and wiki as **data**, not instructions, and to surface suspicious content as a possible prompt-injection attempt rather than acting on it.
3. **`--untrusted-corpus` mode** for cases where the heuristic is not enough. In this mode the entire LLM-extraction pass is skipped: code goes through the AST extractor as usual, but docs, papers, and images become metadata-only nodes (path + size + SHA256 + file_type — file contents are never read). The graph is structurally smaller but carries zero LLM-generated text from the corpus, so a hostile file cannot inject instructions into your assistant. Re-run without the flag once you have read the contents and trust them.

**No heuristic is complete.** If you do not trust the corpus, use `--untrusted-corpus` until you have read the contents and trust them. Treat `graphify-out/GRAPH_REPORT.md` and `graphify-out/wiki/` as untrusted data even on a corpus you mostly trust.

## Environment variables (hardened-fork additions)

| Variable | Default | Purpose |
|---|---|---|
| `GRAPHIFY_FETCH_ALLOWLIST` | unset | Comma-separated hostname allowlist for `safe_fetch`. Empty / unset = no allowlist gate (existing scheme and private-IP-range checks still apply). |
| `GRAPHIFY_MAX_TEXT_BYTES` | `2097152` (2 MB) | Override the text-fetch cap. Hard ceiling 50 MB. Non-positive or malformed values raise `ValueError`. |
| `GRAPHIFY_CONTENT_TYPE_STRICT` | `1` | When `0`, Content-Type mismatches in `ingest` are downgraded to `RuntimeWarning` instead of raising. |
| `GRAPHIFY_CLONE_ALLOWED_HOSTS` | unset | Comma-separated host allowlist for `graphify clone` / `graphify add` git URLs. AND-combined with `GRAPHIFY_CLONE_ALLOWED_OWNERS`. |
| `GRAPHIFY_CLONE_ALLOWED_OWNERS` | unset | Comma-separated owner allowlist for `graphify clone` / `graphify add` git URLs. |
| `GRAPHIFY_PDF_MAX_BYTES` | `104857600` (100 MB) | File-size pre-check before pypdf parses a PDF. |
| `GRAPHIFY_PDF_MEMORY_CAP_BYTES` | `2147483648` (2 GB) | Address-space cap (`RLIMIT_AS`) for pypdf parsing on Unix. No-op on Windows. |
| `GRAPHIFY_OFFICE_MAX_UNCOMPRESSED_BYTES` | `209715200` (200 MB) | Total-uncompressed-size cap on `.docx` / `.xlsx` zip central directories. Archives with more than 10 000 entries or that are not valid zips are also rejected. |
| `GRAPHIFY_AUDIT_LOG_PATH` | `graphify-out/.audit.log` | Override the audit log path. Primarily for test isolation — production behaviour is unchanged when unset. |

## CLI additions (hardened-fork)

- `graphify update <path> --untrusted-corpus` and `graphify watch <path> --untrusted-corpus` build an LLM-free graph (AST + metadata-only nodes for non-code files). Persisted into the graph as a `mode` attribute.
- `graphify add <url>` refuses to extend an untrusted-corpus graph unless `--force` is given.
- `graphify <any-install-command> --dry-run` prints the install plan (CREATE byte counts / MODIFY unified diffs / NO-OP) without touching the filesystem and without emitting audit events. Available on every install entry point.
- `graphify status` prints flagged content (count + recent 5), graph mode (standard / `UNTRUSTED-CORPUS`), the most recent 10 audit events, installed skills, and git-hook state. `--show-flagged-text` surfaces original quarantined text (off by default; the placeholder lists the count and pattern families without leaking the injection payload).

<details>
<summary>Contributing</summary>

**Worked examples** are the most trust-building contribution. Run `/graphify` on a real corpus, save output to `worked/{slug}/`, write an honest `review.md` evaluating what the graph got right and wrong, submit a PR.

**Extraction bugs** - open an issue with the input file, the cache entry (`graphify-out/cache/`), and what was missed or invented.

See [ARCHITECTURE.md](ARCHITECTURE.md) for module responsibilities and how to add a language.

</details>
