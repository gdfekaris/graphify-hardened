# per-file extraction cache - skip unchanged files on re-run
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Per-entry integrity (Task 4.8)
# ---------------------------------------------------------------------------

def _sidecar_path(entry: Path) -> Path:
    """Return the SHA256 sidecar path for a given cache entry.

    Sidecar lives alongside the entry as ``<hash>.json.sha256``. The
    ``*.json`` glob used by `cached_files` and `clear_cache` does not match
    this suffix, so sidecars do not pollute enumeration.
    """
    return entry.parent / (entry.name + ".sha256")


def _atomic_write(target: Path, data: bytes) -> None:
    """Write *data* to *target* via tmp + ``os.replace`` (Windows fallback)."""
    tmp = target.parent / (target.name + ".tmp")
    try:
        tmp.write_bytes(data)
        try:
            os.replace(tmp, target)
        except PermissionError:
            # Windows: os.replace can fail with WinError 5 if the target is
            # briefly locked. Fall back to copy-then-delete.
            import shutil
            shutil.copy2(tmp, target)
            tmp.unlink(missing_ok=True)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


def _log_integrity_failure(entry: Path, expected: str, actual: str) -> None:
    """Surface a cache_integrity_failure event.

    Routes through the audit logger (Phase 5 / Task 5.3) AND prints to
    stderr — the audit log is for forensic reconstruction, the stderr
    line is for the operator who is watching the build output. Both
    matter; neither is a substitute for the other.
    """
    from .audit import log_security_event
    log_security_event(
        "cache_integrity_failure",
        str(entry),
        "error",
        {"cache_key": entry.stem, "expected_sha": expected, "actual_sha": actual},
    )
    print(
        f"[graphify] cache_integrity_failure: {entry} "
        f"expected={expected[:16]}... actual={actual[:16]}... — re-extracting",
        file=sys.stderr,
    )


def _read_with_integrity(entry: Path) -> dict | None:
    """Read a cache entry and verify its SHA256 sidecar.

    Returns None when the entry is absent, the sidecar is absent (treated
    as a pre-integrity entry or partial write — not logged), the hashes
    disagree (logged as tampering), or the JSON cannot be parsed.
    """
    if not entry.exists():
        return None
    sidecar = _sidecar_path(entry)
    if not sidecar.exists():
        return None
    try:
        payload = entry.read_bytes()
        expected = sidecar.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    actual = hashlib.sha256(payload).hexdigest()
    if actual != expected:
        _log_integrity_failure(entry, expected, actual)
        return None
    try:
        return json.loads(payload.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None


def _body_content(content: bytes) -> bytes:
    """Strip YAML frontmatter from Markdown content, returning only the body."""
    text = content.decode(errors="replace")
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            return text[end + 4:].encode()
    return content


def file_hash(path: Path, root: Path = Path(".")) -> str:
    """SHA256 of file contents + path relative to root.

    Using a relative path (not absolute) makes cache entries portable across
    machines and checkout directories, so shared caches and CI work correctly.
    Falls back to the resolved absolute path if the file is outside root.

    For Markdown files (.md), only the body below the YAML frontmatter is hashed,
    so metadata-only changes (e.g. reviewed, status, tags) do not invalidate the cache.
    """
    p = Path(path)
    if not p.is_file():
        raise IsADirectoryError(f"file_hash requires a file, got: {p}")
    raw = p.read_bytes()
    content = _body_content(raw) if p.suffix.lower() == ".md" else raw
    h = hashlib.sha256()
    h.update(content)
    h.update(b"\x00")
    try:
        rel = p.resolve().relative_to(Path(root).resolve())
        h.update(str(rel).encode())
    except ValueError:
        h.update(str(p.resolve()).encode())
    return h.hexdigest()


def cache_dir(root: Path = Path("."), kind: str = "ast") -> Path:
    """Returns graphify-out/cache/{kind}/ - creates it if needed.

    kind is "ast" or "semantic". Separate subdirectories prevent semantic cache
    entries from overwriting AST cache entries for the same source_file (#582).
    """
    d = Path(root).resolve() / "graphify-out" / "cache" / kind
    d.mkdir(parents=True, exist_ok=True)
    return d


def load_cached(path: Path, root: Path = Path("."), kind: str = "ast") -> dict | None:
    """Return cached extraction for this file if hash matches, else None.

    Cache key: SHA256 of file contents.
    Cache value: stored as graphify-out/cache/{kind}/{hash}.json with a
    sibling ``<hash>.json.sha256`` containing the SHA256 of the JSON
    payload. Reads recompute the payload hash and treat any mismatch as a
    cache miss (with a logged integrity event), so a cache file modified
    outside graphify cannot poison downstream extraction.

    For kind="ast", also checks the legacy flat cache/ directory so users
    upgrading from pre-0.5.3 don't lose their existing AST cache entries.
    Legacy entries that lack a sidecar are silently treated as a miss and
    will be re-extracted with integrity records on the next save.
    Returns None if no cache entry, no sidecar, or the file has changed.
    """
    try:
        h = file_hash(path, root)
    except OSError:
        return None
    candidates = [cache_dir(root, kind) / f"{h}.json"]
    if kind == "ast":
        # Migration fallback: legacy flat cache/<hash>.json from pre-0.5.3.
        candidates.append(
            Path(root).resolve() / "graphify-out" / "cache" / f"{h}.json"
        )
    for entry in candidates:
        result = _read_with_integrity(entry)
        if result is not None:
            return result
    return None


def save_cached(path: Path, result: dict, root: Path = Path("."), kind: str = "ast") -> None:
    """Save extraction result for this file.

    Stores as graphify-out/cache/{kind}/{hash}.json where hash = SHA256 of
    the source file contents. result should be a dict with 'nodes' and
    'edges' lists. A sibling ``<hash>.json.sha256`` is written containing
    the SHA256 of the JSON payload, used by `load_cached` to detect
    out-of-band tampering.

    No-ops if `path` is not a regular file. Subagent-produced semantic fragments
    occasionally carry a directory path in `source_file`; skipping them prevents
    IsADirectoryError from aborting the whole batch.
    """
    p = Path(path)
    if not p.is_file():
        return
    h = file_hash(p, root)
    entry = cache_dir(root, kind) / f"{h}.json"
    payload = json.dumps(result).encode("utf-8")
    checksum = hashlib.sha256(payload).hexdigest()
    # Order: entry first, then sidecar. A crash between the two leaves an
    # entry with no sidecar, which `load_cached` correctly treats as a
    # cache miss (re-extract). The reverse order would leave a dangling
    # sidecar, which is also harmless but wastes disk.
    _atomic_write(entry, payload)
    _atomic_write(_sidecar_path(entry), checksum.encode("utf-8"))


def cached_files(root: Path = Path(".")) -> set[str]:
    """Return set of file hashes that have a valid cache entry (any kind)."""
    base = Path(root).resolve() / "graphify-out" / "cache"
    hashes: set[str] = set()
    # Legacy flat entries
    if base.is_dir():
        hashes.update(p.stem for p in base.glob("*.json"))
    # Namespaced entries
    for kind in ("ast", "semantic"):
        d = base / kind
        if d.is_dir():
            hashes.update(p.stem for p in d.glob("*.json"))
    return hashes


def clear_cache(root: Path = Path(".")) -> None:
    """Delete all cache entries (ast/, semantic/, legacy flat) and sidecars."""
    base = Path(root).resolve() / "graphify-out" / "cache"
    # Legacy flat entries + sidecars
    if base.is_dir():
        for pattern in ("*.json", "*.json.sha256"):
            for f in base.glob(pattern):
                f.unlink()
    # Namespaced entries + sidecars
    for kind in ("ast", "semantic"):
        d = base / kind
        if d.is_dir():
            for pattern in ("*.json", "*.json.sha256"):
                for f in d.glob(pattern):
                    f.unlink()


def check_semantic_cache(
    files: list[str],
    root: Path = Path("."),
) -> tuple[list[dict], list[dict], list[dict], list[str]]:
    """Check semantic extraction cache for a list of absolute file paths.

    Returns (cached_nodes, cached_edges, cached_hyperedges, uncached_files).
    Uncached files need Claude extraction; cached files are merged directly.
    """
    cached_nodes: list[dict] = []
    cached_edges: list[dict] = []
    cached_hyperedges: list[dict] = []
    uncached: list[str] = []

    for fpath in files:
        result = load_cached(Path(fpath), root, kind="semantic")
        if result is not None:
            cached_nodes.extend(result.get("nodes", []))
            cached_edges.extend(result.get("edges", []))
            cached_hyperedges.extend(result.get("hyperedges", []))
        else:
            uncached.append(fpath)

    return cached_nodes, cached_edges, cached_hyperedges, uncached


def save_semantic_cache(
    nodes: list[dict],
    edges: list[dict],
    hyperedges: list[dict] | None = None,
    root: Path = Path("."),
) -> int:
    """Save semantic extraction results to cache, keyed by source_file.

    Groups nodes and edges by source_file, then saves one cache entry per file
    under cache/semantic/ (separate from AST entries in cache/ast/) to prevent
    hash-key collisions (#582).
    Returns the number of files cached.
    """
    from collections import defaultdict

    by_file: dict[str, dict] = defaultdict(lambda: {"nodes": [], "edges": [], "hyperedges": []})
    for n in nodes:
        src = n.get("source_file", "")
        if src:
            by_file[src]["nodes"].append(n)
    for e in edges:
        src = e.get("source_file", "")
        if src:
            by_file[src]["edges"].append(e)
    for h in (hyperedges or []):
        src = h.get("source_file", "")
        if src:
            by_file[src]["hyperedges"].append(h)

    saved = 0
    for fpath, result in by_file.items():
        p = Path(fpath)
        if not p.is_absolute():
            p = Path(root) / p
        if p.is_file():
            save_cached(p, result, root, kind="semantic")
            saved += 1
    return saved
