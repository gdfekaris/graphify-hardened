# Re-emission surfaces — inventory of corpus-derived content reaching the assistant

Phase 3, Task 3.1. This doc lists every output where text *derived from corpus
files* (LLM-extracted, or AST-extracted from file contents) lands somewhere an
AI assistant will read it without the user opting in to each piece. It is the
target list for Tasks 3.2 (provenance), 3.4 (quarantine), and 3.5 (untrusted
framing).

## Scope criteria

A surface is in scope iff *all three* hold:

1. It contains text derived from corpus files (LLM output, or AST extraction
   that pulls verbatim content like docstrings/comments).
2. It is read into an AI assistant's context — via the always-on rules-file
   hook, via the MCP server, via `graphify query|path|explain` whose stdout
   the assistant captures, via the Obsidian/wiki exports, or via skill files
   the assistant follows.
3. It reaches the assistant without per-piece user opt-in. Interactive
   commands count: the user opts in to *running* the command, not to each
   node label inside the response.

Tooltip text in `graph.html` is **out of scope**: it is rendered for human
viewers, not consumed by an assistant. CSP / output-encoding hardening for
that surface was completed in Phase 2.

## Corpus-derived fields

These are the fields whose values come from corpus content rather than
graphify's own code. Anywhere these flow downstream is an injection surface.

### LLM-derived (semantic extraction in `graphify/llm.py` and the
`skill.md` subagent pipeline)

Schema (from `llm.py:_EXTRACTION_SYSTEM`):

| Location | Field | Notes |
|---|---|---|
| `node` | `label` | Free-text human-readable name. Already passed through `sanitize_label()` for HTML; that strips control chars and HTML-escapes but does not detect natural-language injection. |
| `node` | `id` | Constrained to `[a-z0-9_]` by prompt; not a free-text vector. |
| `node` | `source_file`, `source_url`, `source_location`, `author`, `contributor` | LLM is instructed to copy from corpus metadata; in practice can be hallucinated free text. Smaller surface but not zero. |
| `edge` | `relation` | Free-form (despite the prompt enumerating values, the model can emit anything). Renders into reports and Obsidian wikilinks as `--{relation}-->`. |
| `edge` | `confidence` | Constrained enum in the prompt. Low-risk. |
| `hyperedge` | `label` | Free-text. Already routed through `sanitize_label()` per Phase 2 fix F5, but only against control chars/HTML. |
| `hyperedge` | `nodes`, `id` | Reference fields, low-risk. |

### LLM-derived (community naming, performed by the *assistant itself* per
`skill.md` Step 5)

The assistant reads `.graphify_analysis.json`, looks at each community's node
labels, and writes a 2–5 word plain-language name — i.e. an LLM is asked to
summarise text from the corpus. The result is persisted to
`.graphify_labels.json` and threaded into every downstream export as
`community_labels: dict[int, str]`. **This is a second LLM stage, distinct
from the `extract_files_direct` pass in `llm.py`.** It also affects CLI users
who never ran an extraction LLM (they could still be targeted via labels the
assistant writes when summarising hostile node names).

### AST-derived from corpus content (no LLM, but still attacker-controlled)

| Location | Field | Source | Notes |
|---|---|---|---|
| `node[file_type=rationale]` | `label` | Python docstrings + `# rationale:` comments via `extract.py:_extract_python_rationale` (called for every `.py` ingest) | Truncated to 80 chars. Any malicious docstring in a corpus `.py` file becomes a node label. |
| `node` | `label` | For non-LLM file-metadata nodes (e.g. ingest of PDFs/images), the filename and any extracted metadata. Lower risk — typically constrained — but not LLM-validated. |

Anything else on a node — `community`, `degree`, `community_name` (the label
above), `norm_label` (computed) — is graphify-derived and not in scope.

`note` fields in `analyze.py:_cross_file_surprises` and
`_cross_community_surprises` are formatted strings built from numbers
(`f"Bridges graph structure (betweenness={score:.3f})"`). **Out of scope** —
graphify-authored, not corpus-derived.

## Surfaces (in scope)

### S1. `graphify-out/GRAPH_REPORT.md`

**Producer:** `graphify/report.py:generate`, called from `skill.md` Step 4 and
Step 5, from `graphify/__main__.py:1408` (the watch/CLI rebuild path), and
from `graphify/watch.py:109`.

**Corpus-derived content embedded:**
- Community names (Step 5 LLM stage): "Communities" section, "Community Hubs"
  navigation, ambiguous-edges section.
- Node labels: God Nodes, Surprising Connections (`source` and `target`),
  Communities (display list of 8 nodes per community), Knowledge Gaps
  (isolated/thin community node lists), Ambiguous Edges (`ul`/`vl`
  endpoint labels).
- Edge `relation` (Surprising Connections, Ambiguous Edges).
- Hyperedge `label` and `nodes` (Hyperedges section).
- `source_file` paths (Surprising Connections, Ambiguous Edges).

**Reaches assistant via:**
- The always-on installer hook for every supported platform — see S6 below for
  the list. The hook injects `additionalContext` telling the assistant to
  read this file before answering architecture questions, on every tool call
  and every turn.
- `skill-*.md` files explicitly direct the assistant: "paste these sections
  from GRAPH_REPORT.md directly into the chat" (`skill-kiro.md:661`,
  `skill-vscode.md:253`).

**Opt-in level:** None. Re-injected on every turn while the rules file is
installed.

**Why this is the headline surface:** persistent, automatic, no UI
indication, and read by the assistant *before* it does anything else.

### S2. `graphify-out/graph.json`

**Producer:** `graphify/export.py:to_json` (called from `skill.md` Step 4 and
the watch path).

**Corpus-derived content embedded:** Every node attribute and edge attribute
listed in the field tables above. This is the canonical store; everything
else is derived from it.

**Reaches assistant via:**
- **MCP server** (`graphify/serve.py`). Loads `graph.json` and exposes
  `query_graph`, `get_node`, `get_neighbors`, `get_community`, `god_nodes`,
  `graph_stats`, `shortest_path`. Each tool returns text containing node
  labels, edge relations, and `source_file` paths. `_subgraph_to_text`
  passes labels through `sanitize_label` (line 98, 104) — same caveat as
  elsewhere: control chars only, no NL-injection detection.
- The CLI commands `graphify query`, `graphify path`, `graphify explain`
  (in `__main__.py:1169`, `1246`, `1296`) load `graph.json` directly and
  print rendered subgraphs to stdout. When invoked by the assistant, that
  stdout is the assistant's tool result.

**Opt-in level:** Per-tool-call. The user picks up the phone (issues the
question); the assistant chooses which tool to call. Individual labels and
relations inside the response are not opted into.

### S3. `graphify-out/wiki/` (Wikipedia-style markdown, opt-in export)

**Producer:** `graphify/wiki.py:to_wiki`. Writes `index.md`, one
`<CommunityName>.md` per community, and one `<GodNodeLabel>.md` per god node.

**Corpus-derived content embedded:**
- Article titles and headings: community names + node labels (filename + H1).
- "Key Concepts" lists: node labels + `source_file`.
- "Connections by Relation" on god-node articles: edge `relation` as a
  section heading, neighbor labels as bullet items.
- Cross-community references: `[[community_label]]` wikilinks.

**Reaches assistant via:** All installed rule files explicitly say "If
`graphify-out/wiki/index.md` exists, navigate it instead of reading raw
files" (`__main__.py:207, 223, 237, 365, 439, 602`). The assistant follows
links across many articles in a single session.

**Opt-in level:** None at read time. The user opts in to *generating* the
wiki (`skill.md` Step 7); after that, the assistant traverses freely.

### S4. `graphify-out/<obsidian-vault>/` (opt-in export)

**Producer:** `graphify/export.py:to_obsidian`. One `.md` per node + one
`_COMMUNITY_<name>.md` per community.

**Corpus-derived content embedded:**
- Node `.md` files: H1 = node label, frontmatter `source_file`, `community`
  (= LLM community name), wikilinked neighbors with `relation` and
  `confidence`.
- Community `.md` files: H1 = community name, member list with labels and
  `source_file`, cross-community links with names.

**Reaches assistant via:** Same hook + skill rules as S3 — assistants are
told to read the vault. Less commonly an assistant target than the report,
but Codex/Cursor users with vault enabled hit it on every architecture
question.

**Opt-in level:** Same as S3 — generation is opt-in, traversal is not.

### S5. `graphify-out/.graphify_analysis.json` and `.graphify_labels.json`

**Producer:** `skill.md` Step 4 (analysis) and Step 5 (labels).

**Corpus-derived content embedded:** Community member lists by node id,
plus the LLM-named labels keyed by community id, plus god-node label
records, plus `surprises` (node label pairs + the graphify-built `note`).

**Reaches assistant via:** `skill.md` itself reads these files (Step 5
reads `.graphify_analysis.json` to pick names; downstream steps re-load
`.graphify_labels.json` to thread `labels` into every export). The
assistant directly ingests the JSON during the build flow.

**Opt-in level:** Internal pipeline state. The assistant reads it as part
of its build script. **Note for Task 3.4:** quarantine has to apply
*before* these files are written, otherwise hostile labels round-trip
through them and out into S1/S3/S4.

### S6. Always-on rules / hook files (the re-injection mechanism, not a
direct content surface)

The rule files installed by `graphify <platform> install` are themselves
graphify-authored (low risk in their own content), but they instruct the
assistant to read S1–S4 on every turn. Inventory of install paths and
target files (`graphify/__main__.py`):

| Platform | Function | File written | Mechanism |
|---|---|---|---|
| Claude Code | `_install_claude_hook` (l. 853) | `.claude/settings.json` PreToolUse hook + project `CLAUDE.md` block | additionalContext injection on every tool call |
| Codex | `_install_codex_hook` (l. 734) | `.codex/...` hook + `AGENTS.md` block | additionalContext injection |
| OpenCode | `_install_opencode_plugin` (l. 663) | `.opencode/plugin.ts` | hook script that echoes a directive |
| Cursor | `_cursor_install` (l. 608) | `.cursor/rules/graphify.mdc` | always-applied rule |
| Gemini | `_install_gemini_hook` (l. 292) | `.gemini/settings.json` + `GEMINI.md` | rules block |
| Kiro | `_kiro_install` (l. 471) | `.kiro/steering/graphify.md` | steering rule |
| Antigravity | `_antigravity_install` (l. 520) | `.antigravity/...` | rules block |
| Aider / Claw / Droid / Trae / Hermes | `_agents_install` (l. 770) | `AGENTS.md` block | rules block |
| VS Code (Copilot) | `vscode_install` (l. 370) | MCP config + rules | rules + MCP |

**All of these tell the assistant the same thing:** read
`graphify-out/GRAPH_REPORT.md`, navigate `graphify-out/wiki/index.md` if
present.

**Why call this out as a surface even though it is graphify-authored:**
Task 3.5 modifies *these files* to add untrusted-data framing. Knowing the
full list now means we know the full list of edits 3.5 has to make.

## Out of scope (verified, recorded so 3.4 doesn't re-investigate)

- **`graph.html`** — read by humans in a browser, not assistants. Browser-
  side review and CSP hardening completed in Phase 2 (`audit/html-output-review.md`).
- **`graph.svg` / `graph.canvas`** — same: human-facing visualisation outputs.
- **`analyze.py:note` fields on surprises** — generated from numbers
  (betweenness, community ids), not corpus content.
- **`norm_label`** — algorithmic transform of `label` for case-insensitive
  matching. Not a separate vector — anything in `norm_label` is already in
  `label`.
- **AST node labels for code structure** (`function`, `class`, `module`
  identifiers) — these come from parsed source identifiers, which are
  technically attacker-controlled in a hostile repo, but the tree-sitter
  grammars constrain them to identifier syntax. Lowest priority. Worth
  flagging as "out of scope for heuristic detection but covered by
  `--untrusted-corpus` mode in 3.6."

## Implications for Phase 3 task ordering

- **Task 3.2 (provenance):** Must add `provenance` to every node at *write
  time* in `build.py` and at LLM-call time in `extract.py` / `llm.py`.
  AST-rationale nodes (`extract.py:_extract_python_rationale`) need
  provenance set to the source `.py` path. Community-name labels need
  provenance recording the *set of source files contributing nodes to that
  community* — that is a derived value, but recording it lets a downstream
  reviewer answer "which file caused this hostile community name."
- **Task 3.4 (quarantine):** must run before S5 is written. The natural
  insertion point is `build.build_from_json` (after validation, before
  graph assembly) and the LLM-call return paths in `llm.py:_call_claude`
  and `llm.py:_call_openai_compat`. Edge `relation`, hyperedge `label`,
  AST-rationale `label`, and (later) the assistant-written
  `community_labels` all need to flow through `flag_suspicious()`. The
  community-naming step is special: by the time `labels` exists, the
  assistant has already been exposed to the input — quarantine there has
  to be belt-and-suspenders, with the framing in 3.5 doing the load-bearing
  defense.
- **Task 3.5 (framing):** The 12 install paths in S6 above are the full
  edit set. MCP responses (`serve.py`) need a prepended note in each
  handler in `_handlers` (l. 341).
- **Task 3.6 (`--untrusted-corpus`):** disables the LLM extraction path
  in `llm.py`. Must also disable the assistant-driven community-naming
  step in `skill.md` Step 5 — consider a fallback to `Community {cid}`
  literal labels in this mode, and document that limitation.

## Summary

| ID | Surface | Mode | Opt-in | LLM-derived? | AST-derived? |
|---|---|---|---|---|---|
| S1 | `GRAPH_REPORT.md` | always-on (hook) | none | yes | yes |
| S2 | `graph.json` via MCP / `query` / `path` / `explain` | per-tool | per-call | yes | yes |
| S3 | `graphify-out/wiki/` | always-on if generated | none | yes | yes |
| S4 | `graphify-out/<obsidian-vault>/` | always-on if generated | none | yes | yes |
| S5 | `.graphify_analysis.json`, `.graphify_labels.json` | internal | n/a (build step) | yes | yes |
| S6 | rules-files / hooks (12 platforms) | always-on | none | (instrumentation, not content) | n/a |

S1 is the load-bearing surface. S2 is the second priority. S3/S4 inherit
the same content as S1. S5 is internal but gates everything. S6 is the
edit set for Task 3.5.
