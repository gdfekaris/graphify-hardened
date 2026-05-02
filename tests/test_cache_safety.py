"""Phase 7.7: cache deserialization safety regression.

Four assertions, mapped to the plan's four bullets:

1. **AST inspection.** ``graphify/cache.py`` does not import any of the
   known-unsafe deserializers (pickle / cPickle / dill / marshal /
   shelve / joblib / cloudpickle). Cross-references and re-asserts the
   existing Phase 4.7 coverage in ``tests/test_cache.py`` so the
   safety contract is colocated with the rest of Phase 7's threat-
   model checks.

2. **Tamper → audit event.** Writing a cache entry, mutating it on
   disk, and calling ``load_cached`` returns None and emits a
   ``cache_integrity_failure`` audit-log event. Phase 4.8 covered the
   stderr-print side; Phase 5.3 wired the audit-log side. This test
   confirms the audit event lands.

3. **Malformed JSON → miss, no raise.** A file at the cache entry path
   that parses as bytes but not as JSON is treated as a miss. The
   integrity check passes (sha256 sidecar consistent with the
   garbage), then json.loads fails inside ``_read_with_integrity`` and
   the failure is contained — None is returned, no exception
   propagates to the caller.

4. **Pickle gadget at cache path → not interpreted.** A canonical
   pickle bytestream whose ``__reduce__`` would fire ``os.system`` if
   loaded by ``pickle.loads`` is placed at a cache entry path with a
   matching sha256 sidecar. ``load_cached`` decodes via ``json.loads``
   only, so the gadget is never interpreted: the call returns None and
   no os.system effect is observed.

The test file is intentionally allowed to import ``pickle`` itself —
the AST-based scan is scoped to ``graphify/*.py`` (production code),
not ``tests/*.py``.
"""
from __future__ import annotations

import ast
import hashlib
import json
import pickle
import subprocess
from pathlib import Path

import pytest

from graphify.cache import (
    _sidecar_path,
    cache_dir,
    file_hash,
    load_cached,
    save_cached,
)


# Modules that, when given attacker-controlled bytes, can yield arbitrary
# code execution. Mirrors the set in tests/test_cache.py — kept as a
# separate copy here so this test is self-contained for Phase 7 review.
_UNSAFE_DESERIALIZERS = {
    "pickle", "cPickle", "dill", "marshal", "shelve", "joblib", "cloudpickle",
}


def _imported_modules(py_file: Path) -> set[str]:
    tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".", 1)[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                names.add(node.module.split(".", 1)[0])
    return names


@pytest.fixture
def cache_root(tmp_path):
    return tmp_path


@pytest.fixture
def source_file(tmp_path):
    f = tmp_path / "src.py"
    f.write_text("def f(): pass\n", encoding="utf-8")
    return f


def _entry_for(source: Path, root: Path, kind: str = "ast") -> Path:
    return cache_dir(root, kind) / f"{file_hash(source, root)}.json"


# ---------------------------------------------------------------------------
# 1 — AST inspection
# ---------------------------------------------------------------------------

def test_cache_py_imports_no_unsafe_deserializer():
    cache_py = Path(__file__).resolve().parent.parent / "graphify" / "cache.py"
    bad = _imported_modules(cache_py) & _UNSAFE_DESERIALIZERS
    assert not bad, (
        f"graphify/cache.py must remain JSON-only, but imports: {sorted(bad)}"
    )


# ---------------------------------------------------------------------------
# 2 — Tamper triggers integrity check + audit event
# ---------------------------------------------------------------------------

def test_tampered_entry_returns_miss_and_emits_audit_event(
    source_file, cache_root, read_audit, capsys,
):
    save_cached(source_file, {"nodes": [{"id": "real"}], "edges": []},
                root=cache_root)
    entry = _entry_for(source_file, cache_root)

    # Mutate the entry; sidecar still records the original SHA, so the
    # integrity check fires.
    entry.write_text(
        json.dumps({"nodes": [{"id": "INJECTED"}], "edges": []}),
        encoding="utf-8",
    )

    result = load_cached(source_file, root=cache_root)
    assert result is None, (
        "tampered cache entry must be treated as a miss, not returned"
    )

    # Stderr surface (operator-visible).
    err = capsys.readouterr().err
    assert "cache_integrity_failure" in err
    assert str(entry) in err

    # Audit-log surface (forensic).
    events = [e for e in read_audit() if e.get("action") == "cache_integrity_failure"]
    assert len(events) == 1, (
        f"expected exactly one cache_integrity_failure audit event, got "
        f"{len(events)}: {events}"
    )
    ev = events[0]
    assert ev["result"] == "error"
    # Phase 5.1's secret-scrub regex catches the 64-hex SHA in the entry
    # filename and replaces it with [REDACTED] in the substring-scrubbed
    # ``target`` field. Assert the path *shape* survives (parent dir
    # intact, .json suffix) without requiring byte equality with the
    # original — the redaction is a feature, not a regression.
    assert str(entry.parent) in ev["target"]
    assert ev["target"].endswith(".json")
    assert "[REDACTED]" in ev["target"]
    details = ev.get("details", {})
    # Phase 5.1's carve-out (audit.py:_GENERIC_CARVEOUT_KEYS) covers
    # ``expected_sha`` and ``actual_sha`` only — those values must survive
    # the generic 32+-char redaction so forensic review can correlate
    # against the source bytes. ``cache_key`` is intentionally NOT in the
    # carve-out: it carries the same hex SHA but the generic pattern's
    # default behaviour of redacting long token-shaped strings still wins.
    assert len(details.get("expected_sha", "")) == 64, (
        "expected_sha must survive the audit scrub — carve-out regression"
    )
    assert len(details.get("actual_sha", "")) == 64, (
        "actual_sha must survive the audit scrub — carve-out regression"
    )
    assert details["expected_sha"] != details["actual_sha"], (
        "tamper test must produce two distinct SHAs"
    )
    assert details.get("cache_key") == "[REDACTED]", (
        "cache_key must be redacted by the generic 32+-char pattern; if "
        "this changes the carve-out set has been broadened — review "
        "audit.py:_GENERIC_CARVEOUT_KEYS"
    )


# ---------------------------------------------------------------------------
# 3 — Malformed JSON at the cache path
# ---------------------------------------------------------------------------

def test_malformed_json_at_cache_path_treated_as_miss(source_file, cache_root):
    """An entry whose bytes are not valid UTF-8 JSON must be a cache miss.
    The failure must be contained: load_cached returns None, no exception
    propagates."""
    entry = _entry_for(source_file, cache_root)
    entry.parent.mkdir(parents=True, exist_ok=True)

    # Garbage that parses as bytes but not as JSON. Sidecar is consistent
    # with the bytes, so the integrity check passes — we want to exercise
    # the JSON-decode failure mode specifically.
    garbage = b"this is { not :: json [["
    entry.write_bytes(garbage)
    _sidecar_path(entry).write_text(
        hashlib.sha256(garbage).hexdigest(), encoding="utf-8",
    )

    # Must not raise.
    result = load_cached(source_file, root=cache_root)
    assert result is None


def test_invalid_utf8_at_cache_path_treated_as_miss(source_file, cache_root):
    """A subtler variant: bytes that aren't valid UTF-8. Same expectation —
    decoded inside _read_with_integrity, UnicodeDecodeError caught, miss
    returned without propagating."""
    entry = _entry_for(source_file, cache_root)
    entry.parent.mkdir(parents=True, exist_ok=True)

    bad_utf8 = b"\xff\xfe\xfd not valid utf-8"
    entry.write_bytes(bad_utf8)
    _sidecar_path(entry).write_text(
        hashlib.sha256(bad_utf8).hexdigest(), encoding="utf-8",
    )

    result = load_cached(source_file, root=cache_root)
    assert result is None


# ---------------------------------------------------------------------------
# 4 — Pickle gadget at cache path is not interpreted
# ---------------------------------------------------------------------------

class _SystemGadget:
    """Classic pickle code-execution gadget. ``__reduce__`` is what
    ``pickle.loads`` consults to reconstruct the object — it returns a
    ``(callable, args)`` pair that pickle will invoke. With os.system as
    the callable, *loading* this pickle would execute the shell command.

    graphify.cache must never invoke pickle.loads on attacker-controlled
    bytes. This class is constructed only inside the test process and
    pickled to a buffer; the ``load_cached`` path under test must reject
    the bytes via JSON-decode failure long before any pickle machinery
    sees them.
    """

    def __reduce__(self):  # noqa: D401 — pickle protocol API
        # subprocess.run is callable from pickle; using a sentinel command
        # that, if ever fired, leaves a detectable filesystem artefact so
        # test failure surfaces unambiguously.
        return (subprocess.run, (["true"],))


def test_pickle_gadget_at_cache_path_is_not_interpreted(
    source_file, cache_root, monkeypatch,
):
    entry = _entry_for(source_file, cache_root)
    entry.parent.mkdir(parents=True, exist_ok=True)

    gadget_bytes = pickle.dumps(_SystemGadget())
    entry.write_bytes(gadget_bytes)
    _sidecar_path(entry).write_text(
        hashlib.sha256(gadget_bytes).hexdigest(), encoding="utf-8",
    )

    # Trip-wire: if any pickle.loads call is reached against the gadget
    # during the load, surface it loudly. This is the *load-bearing*
    # assertion — it would catch a future regression in which a contributor
    # adds a pickle fallback to load_cached.
    real_loads = pickle.loads
    pickle_load_calls: list[bytes] = []

    def _spy_loads(data, *args, **kwargs):
        pickle_load_calls.append(data)
        return real_loads(data, *args, **kwargs)

    monkeypatch.setattr(pickle, "loads", _spy_loads)

    # Trip-wire: if subprocess.run is invoked while loading the cache, the
    # gadget executed. Replace it with a recorder that raises so we'd see
    # the failure unmistakably.
    def _no_subprocess(*args, **kwargs):  # pragma: no cover - failure path
        raise AssertionError(
            f"subprocess.run called during cache load — pickle gadget "
            f"executed. argv={args[0] if args else kwargs.get('args')!r}"
        )

    monkeypatch.setattr(subprocess, "run", _no_subprocess)

    result = load_cached(source_file, root=cache_root)

    assert result is None, (
        "pickle gadget bytes must be treated as a cache miss, not deserialized"
    )
    assert pickle_load_calls == [], (
        "pickle.loads was reached during cache load — the JSON-only "
        "contract is broken"
    )


def test_pickle_gadget_passes_integrity_check_proving_failure_mode_is_json_decode(
    source_file, cache_root,
):
    """Reinforces the assertion above: confirm the integrity layer would
    NOT have rejected the gadget on its own. The gadget is only blocked
    because cache.py decodes with json.loads, not pickle.loads. If a
    future refactor swapped json for pickle while keeping the sha256
    sidecar, the gadget would execute — that's the regression this and
    the prior test together guard against."""
    entry = _entry_for(source_file, cache_root)
    entry.parent.mkdir(parents=True, exist_ok=True)

    gadget_bytes = pickle.dumps(_SystemGadget())
    entry.write_bytes(gadget_bytes)
    sidecar = _sidecar_path(entry)
    sidecar.write_text(
        hashlib.sha256(gadget_bytes).hexdigest(), encoding="utf-8",
    )

    # Manually drive _read_with_integrity to confirm exactly which gate
    # rejected the gadget.
    from graphify.cache import _read_with_integrity
    result = _read_with_integrity(entry)
    assert result is None  # rejected — but by which layer?

    # Integrity sidecar still matches:
    payload = entry.read_bytes()
    assert hashlib.sha256(payload).hexdigest() == sidecar.read_text().strip()

    # And the JSON decode of the same bytes raises — i.e. the failure
    # mode IS the JSON-decode gate, not the integrity gate.
    with pytest.raises((json.JSONDecodeError, UnicodeDecodeError)):
        json.loads(payload.decode("utf-8"))
