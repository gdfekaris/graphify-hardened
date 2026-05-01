# Phase 3 Task 3.7 — cross-reference for `graphify status`

Task 3.7 is satisfied by the implementation of Task 5.4 (the `graphify
status` command). This file records the dependency so the requirement is
not lost between phases.

## What 3.7 requires from `graphify status`

When the `status` command is built in Phase 5, it MUST:

1. **Report the count of flagged nodes.** Read
   `graphify-out/.flagged.json` (one JSON object per line — the format
   written by `graphify.build._quarantine_node` per Task 3.4). Print the
   total record count.

2. **Print the most recent 5 entries.** For each, surface at minimum:
   `node_id`, `field_name`, `matched_patterns`, `provenance`, `ts`. Do
   NOT print `original_text` by default — the whole point of quarantine
   is that the operator gets to decide whether to look at it. Offer a
   `graphify status --show-flagged-text` flag for that.

3. **Surface the build mode.** If `graphify-out/graph.json`'s graph
   attributes contain `mode: "untrusted-corpus"` (Task 3.6, see
   `graphify.untrusted.is_untrusted_corpus_graph`), say so prominently
   so the operator knows downstream consumers (MCP, exports) are
   running against a metadata-only graph.

## Why this matters

- Quarantine (3.4) silently redacts hostile content. Without `status`
  reporting, an operator might never realise the corpus they're
  building against contained an injection attempt.
- Untrusted-corpus mode (3.6) trades information density for safety.
  An operator who forgets they ran the build with `--untrusted-corpus`
  may misread a sparse graph as a small codebase.
- Both signals are persisted to disk; the only thing missing is the
  surfacing. `status` is the natural surface.

## Acceptance for 3.7

- A test in the Phase 5 `tests/test_status.py` (or wherever 5.4 lands)
  that:
  - Builds a graph in `--untrusted-corpus` mode and asserts the mode
    line appears in `graphify status` output.
  - Builds a graph against a corpus with one injection-flagged label
    and asserts `status` prints "1 flagged" and one record summary.
- Reference back to this file from the 5.4 commit message so the
  Phase 3 trail closes.

## Pointers

- `.flagged.json` writer: `graphify/build.py::_quarantine_node`,
  default path constant `_DEFAULT_FLAGGED_LOG`.
- Mode marker reader: `graphify/untrusted.py::is_untrusted_corpus_graph`.
- Re-emission inventory (the broader threat model context):
  `audit/re-emission-surfaces.md`.
