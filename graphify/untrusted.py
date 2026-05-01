# Helpers for `graphify --untrusted-corpus` mode (Phase 3 Task 3.6).
#
# In this mode the build pipeline never invokes an LLM and never reads the
# *contents* of any non-code corpus file. Code goes through the existing
# tree-sitter extractor (which reads source identifiers but cannot reach
# any natural-language injection target). Every other file becomes a
# metadata-only node — path, size, SHA256, file_type — so the operator
# still sees that the file exists in the graph without giving an attacker
# a re-emission surface for adversarial prose.
#
# This is the right first-pass mode for a freshly cloned third-party repo:
# the user can opt back into LLM extraction once they have read the
# contents themselves and trust the corpus.
from __future__ import annotations

import hashlib
import re
from pathlib import Path

from graphify.detect import (
    CODE_EXTENSIONS,
    DOC_EXTENSIONS,
    IMAGE_EXTENSIONS,
    PAPER_EXTENSIONS,
)

MODE_KEY = "mode"
MODE_UNTRUSTED = "untrusted-corpus"

# How many bytes to read at a time when computing SHA256 — keeps memory
# bounded for very large files in the corpus (e.g. ML model weights).
_HASH_CHUNK = 1024 * 1024


def file_sha256(path: Path) -> str:
    """Return the hex-encoded SHA256 of a file's bytes."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(_HASH_CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def _file_type_for(path: Path) -> str | None:
    ext = path.suffix.lower()
    if ext in CODE_EXTENSIONS:
        return "code"
    if ext in DOC_EXTENSIONS:
        return "document"
    if ext in PAPER_EXTENSIONS:
        return "paper"
    if ext in IMAGE_EXTENSIONS:
        return "image"
    return None


def _safe_id(rel_path: str) -> str:
    """Turn a relative path into a node id matching the rest of the
    extractor's id conventions ([a-z0-9_])."""
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "_", rel_path).strip("_").lower()
    return cleaned or "file"


def metadata_node_for_file(path: Path, root: Path) -> dict | None:
    """Return a metadata-only node for a non-code corpus file.

    Returns None if the file is missing or its extension is not one
    graphify recognises (we deliberately keep the scope tight — exotic
    file types should not silently leak into the graph).
    """
    if not path.exists() or not path.is_file():
        return None
    file_type = _file_type_for(path)
    if file_type is None or file_type == "code":
        # Code files go through the AST extractor instead. Anything
        # outside the recognised set is dropped here on purpose.
        return None
    try:
        rel = str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        rel = str(path)
    try:
        size = path.stat().st_size
        sha = file_sha256(path)
    except OSError:
        return None
    return {
        "id": _safe_id(rel),
        "label": path.name,  # filename only — never opens the file
        "file_type": file_type,
        "source_file": rel,
        "size_bytes": size,
        "sha256": sha,
    }


def is_untrusted_corpus_graph(graph_data: dict) -> bool:
    """True if a loaded graph.json was produced in untrusted-corpus mode."""
    graph_attrs = graph_data.get("graph") or {}
    if isinstance(graph_attrs, dict):
        return graph_attrs.get(MODE_KEY) == MODE_UNTRUSTED
    if isinstance(graph_attrs, list):
        # Some networkx versions serialise graph attrs as a list of pairs.
        for item in graph_attrs:
            if isinstance(item, (list, tuple)) and len(item) == 2 and item[0] == MODE_KEY:
                return item[1] == MODE_UNTRUSTED
    return False
