"""Tests for graphify/cache.py."""
import ast
import pytest
from pathlib import Path
from graphify.cache import file_hash, cache_dir, load_cached, save_cached, cached_files, clear_cache, _body_content


# ---------------------------------------------------------------------------
# Deserialization-safety regression (Task 4.7)
# ---------------------------------------------------------------------------

# These modules can deserialize attacker-controlled bytes into arbitrary code
# execution (pickle/dill/cloudpickle/joblib/shelve all use the pickle wire
# format; marshal is documented as unsafe for untrusted input). The cache,
# and the rest of graphify, must not depend on any of them. AST-scanning the
# package's own source is more reliable than checking sys.modules — pytest's
# own machinery imports pickle indirectly, so a sys.modules check would have
# false positives.
_UNSAFE_DESERIALIZERS = {"pickle", "cPickle", "dill", "marshal", "shelve",
                         "joblib", "cloudpickle"}


def _imported_modules(py_file: Path) -> set[str]:
    """Return the set of top-level module names imported by *py_file*."""
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


def test_cache_module_does_not_import_unsafe_deserializers():
    """Direct regression for the spec: graphify.cache must be JSON-only."""
    cache_py = Path(__file__).resolve().parent.parent / "graphify" / "cache.py"
    imports = _imported_modules(cache_py)
    bad = imports & _UNSAFE_DESERIALIZERS
    assert not bad, f"graphify/cache.py imports unsafe deserializer(s): {sorted(bad)}"


def test_no_unsafe_deserializers_anywhere_in_graphify():
    """Scan the whole package — a pickle import outside cache.py would still
    be a code-execution vector if it touches user-controlled bytes."""
    pkg = Path(__file__).resolve().parent.parent / "graphify"
    offenders: dict[str, set[str]] = {}
    for py_file in pkg.rglob("*.py"):
        bad = _imported_modules(py_file) & _UNSAFE_DESERIALIZERS
        if bad:
            offenders[str(py_file.relative_to(pkg))] = bad
    assert not offenders, f"unsafe deserializer imports found: {offenders}"


@pytest.fixture
def tmp_file(tmp_path):
    f = tmp_path / "sample.txt"
    f.write_text("hello world")
    return f


@pytest.fixture
def cache_root(tmp_path):
    return tmp_path


def test_file_hash_consistent(tmp_file):
    """Same file gives same hash on repeated calls."""
    h1 = file_hash(tmp_file)
    h2 = file_hash(tmp_file)
    assert h1 == h2
    assert isinstance(h1, str)
    assert len(h1) == 64  # SHA256 hex digest length


def test_file_hash_changes(tmp_path):
    """Different file contents give different hashes."""
    f1 = tmp_path / "a.txt"
    f2 = tmp_path / "b.txt"
    f1.write_text("content one")
    f2.write_text("content two")
    assert file_hash(f1) != file_hash(f2)


def test_cache_roundtrip(tmp_file, cache_root):
    """Save then load returns the same result dict."""
    result = {"nodes": [{"id": "n1", "label": "Node1"}], "edges": []}
    save_cached(tmp_file, result, root=cache_root)
    loaded = load_cached(tmp_file, root=cache_root)
    assert loaded == result


def test_cache_miss_on_change(tmp_file, cache_root):
    """After file content changes, load_cached returns None."""
    result = {"nodes": [], "edges": [{"source": "a", "target": "b"}]}
    save_cached(tmp_file, result, root=cache_root)
    # Modify the file
    tmp_file.write_text("completely different content")
    assert load_cached(tmp_file, root=cache_root) is None


def test_cached_files(tmp_path, cache_root):
    """cached_files returns the set of cached hashes."""
    f1 = tmp_path / "file1.py"
    f2 = tmp_path / "file2.py"
    f1.write_text("alpha")
    f2.write_text("beta")

    save_cached(f1, {"nodes": [], "edges": []}, root=cache_root)
    save_cached(f2, {"nodes": [], "edges": []}, root=cache_root)

    hashes = cached_files(cache_root)
    assert file_hash(f1, cache_root) in hashes
    assert file_hash(f2, cache_root) in hashes


def test_clear_cache(tmp_file, cache_root):
    """clear_cache removes all .json files from graphify-out/cache/ (all subdirs)."""
    save_cached(tmp_file, {"nodes": [], "edges": []}, root=cache_root)
    # Since v0.5.3 entries go into cache/ast/, not the flat cache/ dir
    cache_base = cache_root / "graphify-out" / "cache"
    assert len(list(cache_base.rglob("*.json"))) > 0
    clear_cache(cache_root)
    assert len(list(cache_base.rglob("*.json"))) == 0


# ---------------------------------------------------------------------------
# Per-entry SHA256 integrity (Task 4.8)
# ---------------------------------------------------------------------------

def _entry_path_for(tmp_file, cache_root, kind="ast"):
    """Helper: resolve the cache-entry path for a given source file."""
    h = file_hash(tmp_file, cache_root)
    return cache_dir(cache_root, kind) / f"{h}.json"


def test_save_writes_sidecar(tmp_file, cache_root):
    save_cached(tmp_file, {"nodes": [], "edges": []}, root=cache_root)
    entry = _entry_path_for(tmp_file, cache_root)
    sidecar = entry.parent / (entry.name + ".sha256")
    assert entry.exists()
    assert sidecar.exists()
    # Sidecar content must equal SHA256 of the entry's bytes.
    import hashlib as _hl
    expected = _hl.sha256(entry.read_bytes()).hexdigest()
    assert sidecar.read_text(encoding="utf-8").strip() == expected


def test_load_returns_miss_when_sidecar_missing(tmp_file, cache_root):
    save_cached(tmp_file, {"nodes": [{"id": "x"}], "edges": []}, root=cache_root)
    entry = _entry_path_for(tmp_file, cache_root)
    sidecar = entry.parent / (entry.name + ".sha256")
    sidecar.unlink()
    assert load_cached(tmp_file, root=cache_root) is None


def test_load_returns_miss_and_logs_when_entry_tampered(tmp_file, cache_root, capsys):
    save_cached(tmp_file, {"nodes": [{"id": "x"}], "edges": []}, root=cache_root)
    entry = _entry_path_for(tmp_file, cache_root)
    # Tamper with the entry — sidecar still records the original hash.
    entry.write_text('{"nodes":[{"id":"INJECTED"}],"edges":[]}', encoding="utf-8")

    result = load_cached(tmp_file, root=cache_root)
    assert result is None  # tampered → miss, not the injected payload

    err = capsys.readouterr().err
    assert "cache_integrity_failure" in err
    assert str(entry) in err


def test_load_returns_miss_when_sidecar_tampered(tmp_file, cache_root, capsys):
    save_cached(tmp_file, {"nodes": [], "edges": []}, root=cache_root)
    entry = _entry_path_for(tmp_file, cache_root)
    sidecar = entry.parent / (entry.name + ".sha256")
    sidecar.write_text("0" * 64, encoding="utf-8")
    assert load_cached(tmp_file, root=cache_root) is None
    assert "cache_integrity_failure" in capsys.readouterr().err


def test_load_returns_miss_when_both_tampered_consistently(tmp_file, cache_root):
    # Attacker who knows the scheme rewrites entry AND sidecar consistently.
    # The integrity check catches mismatches against the sidecar, not against
    # any external authority — so this scenario is *not* prevented by the
    # check. The scheme defends against partial tampering (entry without
    # matching sidecar update). Document the limitation as a regression test:
    # a fully-consistent rewrite IS accepted, by design.
    save_cached(tmp_file, {"nodes": [], "edges": []}, root=cache_root)
    entry = _entry_path_for(tmp_file, cache_root)
    sidecar = entry.parent / (entry.name + ".sha256")
    import hashlib as _hl
    forged_payload = '{"nodes":[{"id":"INJECTED"}],"edges":[]}'
    entry.write_text(forged_payload, encoding="utf-8")
    sidecar.write_text(_hl.sha256(forged_payload.encode()).hexdigest(), encoding="utf-8")
    # The check returns the forged result. Future hardening (e.g. signing
    # the sidecar with a build-time key) is out of scope for Task 4.8.
    assert load_cached(tmp_file, root=cache_root) == {
        "nodes": [{"id": "INJECTED"}], "edges": []
    }


def test_legacy_flat_entry_requires_sidecar(tmp_file, cache_root, capsys):
    # Simulate a pre-fork legacy entry: write to graphify-out/cache/<hash>.json
    # without any sidecar. load_cached must treat it as a miss without
    # logging tampering (the absence is normal, not suspicious).
    h = file_hash(tmp_file, cache_root)
    legacy_dir = cache_root / "graphify-out" / "cache"
    legacy_dir.mkdir(parents=True, exist_ok=True)
    (legacy_dir / f"{h}.json").write_text(
        '{"nodes":[{"id":"legacy"}],"edges":[]}', encoding="utf-8",
    )
    assert load_cached(tmp_file, root=cache_root) is None
    assert "cache_integrity_failure" not in capsys.readouterr().err


def test_clear_cache_removes_sidecars(tmp_file, cache_root):
    save_cached(tmp_file, {"nodes": [], "edges": []}, root=cache_root)
    cache_base = cache_root / "graphify-out" / "cache"
    assert any(p.suffix == ".sha256" for p in cache_base.rglob("*"))
    clear_cache(cache_root)
    assert not list(cache_base.rglob("*.sha256"))


def test_md_frontmatter_only_change_same_hash(tmp_path):
    """Changing only frontmatter fields in a .md file does not change the hash."""
    f = tmp_path / "doc.md"
    f.write_text("---\nreviewed: 2026-01-01\n---\n\n# Title\n\nBody text.")
    h1 = file_hash(f)
    f.write_text("---\nreviewed: 2026-04-09\n---\n\n# Title\n\nBody text.")
    h2 = file_hash(f)
    assert h1 == h2


def test_md_body_change_different_hash(tmp_path):
    """Changing the body of a .md file produces a different hash."""
    f = tmp_path / "doc.md"
    f.write_text("---\nreviewed: 2026-01-01\n---\n\n# Title\n\nOriginal body.")
    h1 = file_hash(f)
    f.write_text("---\nreviewed: 2026-01-01\n---\n\n# Title\n\nChanged body.")
    h2 = file_hash(f)
    assert h1 != h2


def test_md_no_frontmatter_hashed_normally(tmp_path):
    """A .md file with no frontmatter is hashed by its full content."""
    f = tmp_path / "doc.md"
    f.write_text("# Just a heading\n\nNo frontmatter here.")
    h1 = file_hash(f)
    f.write_text("# Just a heading\n\nDifferent content.")
    h2 = file_hash(f)
    assert h1 != h2


def test_non_md_file_hashed_fully(tmp_path):
    """Non-.md files are still hashed by their full content."""
    f = tmp_path / "script.py"
    f.write_text("# comment\nx = 1")
    h1 = file_hash(f)
    f.write_text("# changed comment\nx = 1")
    h2 = file_hash(f)
    assert h1 != h2


def test_body_content_strips_frontmatter():
    """_body_content correctly strips YAML frontmatter."""
    content = b"---\ntitle: Test\n---\n\nActual body."
    assert _body_content(content) == b"\n\nActual body."


def test_body_content_no_frontmatter():
    """_body_content returns content unchanged when no frontmatter present."""
    content = b"No frontmatter here."
    assert _body_content(content) == content
