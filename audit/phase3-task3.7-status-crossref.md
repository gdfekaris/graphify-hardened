# Phase 3 Task 3.7 — cross-reference for `graphify status`

**Status:** SATISFIED by Task 5.4. Implementation is `graphify.__main__.status`,
CLI dispatch is `graphify status`, with `--show-flagged-text` for the
gated original text. Tests are in `tests/test_status.py`. The remainder
of this doc records the original requirement and the post-implementation
acceptance check.

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

Met by the test set in `tests/test_status.py`:

- `test_status_reports_untrusted_corpus_mode` — builds a graph.json
  with `graph: {mode: "untrusted-corpus"}` and asserts the
  `UNTRUSTED-CORPUS` marker is in the status output.
- `test_status_reports_flagged_count` — writes flagged records to
  `graphify-out/.flagged.json` and asserts the count + recent summary
  appear (with the actual node_id and matched_patterns visible).
- `test_status_omits_original_text_by_default` /
  `test_status_shows_original_text_when_flag_passed` — verify the
  `--show-flagged-text` gate works in both directions; the redacted
  text is never surfaced unless explicitly asked for.

The 5.4 commit references this file by path.

## Pointers

- `.flagged.json` writer: `graphify/build.py::_quarantine_node`,
  default path constant `_DEFAULT_FLAGGED_LOG`.
- Mode marker reader: `graphify/untrusted.py::is_untrusted_corpus_graph`.
- Re-emission inventory (the broader threat model context):
  `audit/re-emission-surfaces.md`.
