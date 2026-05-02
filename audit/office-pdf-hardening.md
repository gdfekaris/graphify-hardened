# Office and PDF parser hardening (Phase 4 / Task 4.9)

**Scope:** the three parser entry points in `graphify/detect.py` —
`extract_pdf_text` (pypdf), `docx_to_markdown` (python-docx), and
`xlsx_to_markdown` (openpyxl). Both `[pdf]` and `[office]` extras are kept
per `FORK.md` Phase 0 decisions, so this hardening is required, not waived.

## Version pinning

`pyproject.toml`:

```
pdf    = ["pypdf>=6.10.2,<7", "html2text>=2025.4.15,<2026"]
office = ["python-docx>=1.2.0,<2", "openpyxl>=3.1.5,<4"]
```

`pip-audit` (2.10.0) and `osv-scanner` (2.3.5) — both run as part of Task 1.6
and reproducible via `.github/workflows/audit.yml` — report zero CVEs against
the pinned ranges as of the Phase 1 baseline. The audit workflow re-runs on
every PR into `development` and weekly, so a future advisory against any of
these will fail CI before the parser path can be exercised against a hostile
input on a vulnerable build.

## XML parser surface and `defusedxml`

The Task 4.9 spec calls for replacing direct `xml.etree.ElementTree` /
`lxml` usage with `defusedxml` equivalents.

- `grep -rn 'xml\.etree\|lxml\|defusedxml\|fromstring\|XMLParser' graphify/`
  returns **zero hits.** No graphify code parses XML directly.
- The XML parsing happens *inside* `python-docx` and `openpyxl`, both of
  which use `lxml` directly when present. `defusedxml.defuse_stdlib()`
  monkey-patches the *stdlib* parsers (`xml.etree.ElementTree`,
  `xml.dom.minidom`, etc.) and has no effect on `lxml`-based parsers, so
  applying it would be process-wide cosmetic with zero practical defence
  for the libraries we actually depend on.
- `lxml` defaults to `resolve_entities=True` for XXE-style external entity
  resolution; both python-docx and openpyxl construct their parsers without
  enabling network resolvers, but neither exposes a public API for us to
  override the behaviour from outside. The defensible mitigations therefore
  live at the file-shape boundary, not at the XML-API boundary.

`defusedxml` is intentionally not added to `[office]`. The audit doc records
this so a future maintainer who reads the spec doesn't try to retrofit it
without checking that the underlying parsers are stdlib-based.

## Mitigations applied

### PDF (`extract_pdf_text`)

1. **File-size pre-check.** Files larger than `GRAPHIFY_PDF_MAX_BYTES`
   (default 100 MB) are refused before any pypdf code runs. PDFs in the
   typical research / docs corpus are well under 50 MB; books exceed this
   only rarely. A malformed env value falls back to the default rather than
   crashing, so misconfiguration cannot DoS the parser.

2. **Virtual-memory ceiling.** Inside an `_AddressSpaceCap` context manager
   the parsing block lowers `RLIMIT_AS` to
   `GRAPHIFY_PDF_MEMORY_CAP_BYTES` (default 2 GB) on Unix, restoring the
   prior limit on exit. A pathological PDF with deeply nested objects /
   decompression bombs / object-stream loops hits a `MemoryError` instead
   of exhausting host RAM. The cap is process-wide for the duration; this
   is acceptable because graphify is a single-purpose CLI doing no
   concurrent work alongside the parse, and 2 GB is far above legitimate
   pypdf working sets.

3. **Windows fallback.** `resource` is a Unix-only module. On Windows the
   context manager is a no-op (documented in the docstring). The file-size
   pre-check still applies.

4. **Catch-all bail.** The existing `try / except Exception: return ""`
   wrapper is retained and extended to also catch `MemoryError` from the
   address-space cap. Any failure produces an empty string, which the
   caller treats as "no extractable text" — same behaviour as the
   pre-hardening version.

### Office (`docx_to_markdown`, `xlsx_to_markdown`)

1. **Pre-flight zip inspection (`_office_zip_is_safe`).** Both `.docx` and
   `.xlsx` are zip archives. Before either parser is invoked we open the
   archive with `zipfile.ZipFile`, read the *central directory only* (no
   decompression), and reject:
   - non-zip files (the parsers would raise on these anyway, but rejecting
     here means the heavier `lxml`-using import never happens),
   - archives whose declared total uncompressed size exceeds
     `GRAPHIFY_OFFICE_MAX_UNCOMPRESSED_BYTES` (default 200 MB),
   - archives containing more than 10,000 entries (defends against
     pathological per-entry-cost attacks even under the size cap).

   This is the actually-effective defence against zip-bomb shaped Office
   documents — a 42 KB on-disk file claiming 4 GB uncompressed is rejected
   without inflating any of it. The cap is configurable for users who
   legitimately deal with very large workbooks.

2. **Catch-all bail (existing).** Both functions retain the
   `try / except Exception: return ""` wrapper. After the pre-flight,
   anything that still slips through (e.g. a structurally valid zip with
   internal XML the parser refuses) returns an empty string.

## Adversarial fixtures

`tests/test_office_pdf_hardening.py` (15 tests, full file):

PDF:
- Non-PDF blob with `.pdf` extension → empty.
- Truncated `%PDF-1.4` header → empty.
- Oversized file under tightened `GRAPHIFY_PDF_MAX_BYTES` → empty.
- `_pdf_max_bytes` env-var: default, override, malformed (graceful
  fallback) — three tests.

Office:
- Synthetic zip-bomb shape (3 × 50 KB zero entries, 10 KB cap) → refused
  by `_office_zip_is_safe`.
- Non-zip `.docx` → refused.
- Well-formed small zip → accepted.
- Boundary case at the cap → accepted.
- 10,001-entry archive → refused.
- `docx_to_markdown` and `xlsx_to_markdown` against malformed and
  zip-bomb fixtures → both return `""` without invoking the upstream
  parser. (Test passes whether or not python-docx / openpyxl is
  installed: the safety gate fires first.)

## Out of scope

- **Syntactically valid Office documents with hostile XML inside.** The
  pre-flight cannot inspect the XML payload; that lives behind lxml. Real
  defence here would be running the parser in a separate process with its
  own RLIMIT and seccomp filter, which is a substantial refactor and is
  out of scope for this task.
- **lxml CVEs.** lxml is not currently a direct graphify dependency — it
  arrives transitively through python-docx and openpyxl. The pinned
  upper-bound version ranges of those parents do not constrain lxml's
  version, so an lxml advisory is the parents' problem to manifest. The
  weekly `osv-scanner` run sees the resolved transitive set and would
  flag a vulnerable lxml.

## Status

PDF and Office parser entry points are now defended at the file-shape
boundary. Adversarial fixture tests are in place. `defusedxml` retrofit is
documented as not-applicable (no direct stdlib XML usage; lxml unaffected
by `defuse_stdlib()`). Acceptance criteria for Task 4.9 met.
