# Deserialization audit (Phase 4 / Task 4.7)

**Scope:** every reader path in the cache layer and any other module in
`graphify/` that loads data produced by a previous run, a teammate, a CI
artifact, or an attacker who can write to `graphify-out/cache/`. Reviewed at
commit `abe2c65`.

## Inventory

```
$ grep -rn 'pickle\|cPickle\|dill\|marshal\|shelve\|joblib\|cloudpickle' graphify/ tests/
(no output)
```

Zero hits. None of the unsafe-deserialization primitives (`pickle`,
`cPickle`, `dill`, `marshal`, `shelve`, `joblib`, `cloudpickle`) appear
anywhere in the `graphify/` package or its test suite. The grep is also
encoded as a regression test:
`tests/test_cache.py::test_no_unsafe_deserializers_anywhere_in_graphify`,
which AST-scans every `.py` file in the package on each run.

## Cache read paths

`graphify/cache.py` is the only module that reads back persisted artefacts
keyed by file hash. The relevant paths:

| Function | File format | Reader call |
|---|---|---|
| `load_cached` (current layout) | JSON | `json.loads(entry.read_text(...))` (line 74) |
| `load_cached` (legacy flat layout, AST kind only) | JSON | `json.loads(legacy.read_text(...))` (line 82) |
| `cached_files` | enumerates filenames only — no read | `*.json` glob (lines 125, 130) |
| `clear_cache` | filename-only | unlink of `*.json` (lines 139, 145) |
| `check_semantic_cache` | delegates to `load_cached` | — |

Both `load_cached` branches use `json.loads`, with `(json.JSONDecodeError,
OSError)` collapsed to a cache miss (None) — so a malformed or partial cache
entry cannot crash the build, it just forces re-extraction. The legacy
fallback path is hash-keyed identically, so a cache poisoner cannot smuggle
a payload through it that the namespaced reader would reject.

## Cache write paths

`save_cached` (line 105) writes via `json.dumps(result)` to a temp file and
atomically renames into place. Windows fallback uses `shutil.copy2` plus
`unlink`. No format alternative is in the code — JSON-only.

## Other persistence paths

For completeness, paths outside `cache.py` that serialize/deserialize data
graphify reads back across runs:

- `graphify/build.py`, `graphify/export.py`: NetworkX graph IO via
  `node_link_data` / `node_link_graph` over JSON. No pickle.
- `graphify/serve.py` (MCP): JSON over stdio. No pickle.
- `graphify/ingest.py` and the YAML-frontmatter Markdown fixtures: text
  formats, parsed with stdlib parsers, not deserializers.
- `.flagged.json` (Task 3.4 quarantine log): JSON Lines, append-only.

## Regression test

```python
# tests/test_cache.py
_UNSAFE_DESERIALIZERS = {"pickle", "cPickle", "dill", "marshal", "shelve",
                         "joblib", "cloudpickle"}

def test_no_unsafe_deserializers_anywhere_in_graphify():
    pkg = Path(__file__).resolve().parent.parent / "graphify"
    offenders: dict[str, set[str]] = {}
    for py_file in pkg.rglob("*.py"):
        bad = _imported_modules(py_file) & _UNSAFE_DESERIALIZERS
        if bad:
            offenders[str(py_file.relative_to(pkg))] = bad
    assert not offenders, f"unsafe deserializer imports found: {offenders}"
```

The plan suggested a simpler form (`'pickle' not in sys.modules` after
importing `graphify.cache`), but `pytest` itself imports `pickle` indirectly
on every Python it supports, so that form would have produced false
positives. The AST scan is deterministic and specific to graphify's own
source.

## Findings

- **No pickle, no marshal, no dill, no shelve, no joblib, no cloudpickle**
  in the package or its tests.
- **Cache layer is JSON-only**, with malformed entries downgraded to a
  cache miss rather than an exception that would surface attacker-friendly
  details.
- **Regression test in place** (two: one specific to `cache.py`, one
  package-wide) so that any future commit reintroducing pickle (or its
  variants) will fail CI.

## Status

Clean. No fix-up commit required. Task 4.8 (per-entry SHA256 integrity
check) is the next step and is required to close out the cache surface — a
JSON-only reader still trusts the bytes it reads.
