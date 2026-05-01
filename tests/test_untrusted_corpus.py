"""Phase 3 Task 3.6 — `--untrusted-corpus` mode.

Acceptance criteria from IMPLEMENTATION_PLAN.md:
- --untrusted-corpus produces a graph with code nodes and file-metadata
  nodes only.
- No node has a `rationale` field populated.
- The `mode` field in graph.json metadata is `untrusted-corpus`.
"""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest


# ---------- helpers


def _make_corpus(root: Path) -> None:
    """Build a tiny fixture corpus: one .py code file plus one .md doc
    plus one binary-ish image file. Just enough to exercise both paths."""
    (root / "src").mkdir(parents=True, exist_ok=True)
    (root / "src" / "math_lib.py").write_text(
        'def add(a, b):\n    """Add two numbers."""\n    return a + b\n',
        encoding="utf-8",
    )
    (root / "docs").mkdir(parents=True, exist_ok=True)
    (root / "docs" / "README.md").write_text("# Read me\n", encoding="utf-8")
    (root / "docs" / "diagram.png").write_bytes(b"\x89PNG\r\n\x1a\nfake-image-bytes")


# ---------- metadata_node_for_file


def test_metadata_node_records_path_size_sha256(tmp_path):
    from graphify.untrusted import metadata_node_for_file

    f = tmp_path / "doc.md"
    payload = b"# Hello\n"
    f.write_bytes(payload)
    node = metadata_node_for_file(f, tmp_path)

    assert node is not None
    assert node["label"] == "doc.md"
    assert node["file_type"] == "document"
    assert node["source_file"] == "doc.md"
    assert node["size_bytes"] == len(payload)
    assert node["sha256"] == hashlib.sha256(payload).hexdigest()


def test_metadata_node_skips_code_files(tmp_path):
    """Code files go through the AST extractor, not the metadata path."""
    from graphify.untrusted import metadata_node_for_file

    f = tmp_path / "x.py"
    f.write_text("x = 1\n", encoding="utf-8")
    assert metadata_node_for_file(f, tmp_path) is None


def test_metadata_node_skips_unknown_extension(tmp_path):
    from graphify.untrusted import metadata_node_for_file

    f = tmp_path / "weird.xyz"
    f.write_text("hello", encoding="utf-8")
    assert metadata_node_for_file(f, tmp_path) is None


def test_metadata_node_does_not_read_file_contents(tmp_path, monkeypatch):
    """Acceptance: 'No labels, no rationale, no summaries derived from
    content.' We assert this by interposing on read_text — the metadata
    path must never call it."""
    from graphify.untrusted import metadata_node_for_file

    f = tmp_path / "doc.md"
    f.write_text("# do not read me", encoding="utf-8")

    original_read_text = Path.read_text
    calls: list[str] = []

    def _spy(self, *args, **kwargs):
        calls.append(str(self))
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", _spy)
    node = metadata_node_for_file(f, tmp_path)

    assert node is not None
    assert str(f) not in calls, (
        "metadata_node_for_file must not read the file contents — only "
        "open in binary for the SHA256."
    )


# ---------- _rebuild_untrusted end-to-end


def test_rebuild_untrusted_produces_code_and_metadata_nodes_only(tmp_path):
    """Acceptance: graph contains code nodes (from AST) and metadata-only
    nodes (for non-code), and nothing else."""
    from graphify.watch import _rebuild_untrusted

    _make_corpus(tmp_path)
    assert _rebuild_untrusted(tmp_path) is True

    graph_path = tmp_path / "graphify-out" / "graph.json"
    assert graph_path.exists()
    data = json.loads(graph_path.read_text(encoding="utf-8"))

    file_types = {n.get("file_type") for n in data["nodes"]}
    # Code AST will produce "code" nodes; the .md and .png produce
    # "document" and "image" metadata nodes. Nothing else may appear.
    assert file_types <= {"code", "document", "image"}
    assert "document" in file_types
    assert "image" in file_types


def test_rebuild_untrusted_no_rationale_nodes(tmp_path):
    """Acceptance: 'No node has a `rationale` field populated.'

    rationale appears as a `file_type: rationale` node inserted by
    extract.py:_extract_python_rationale during a normal AST run. The
    untrusted path must not produce those (their `label` is the docstring
    text, which is corpus-content)."""
    from graphify.watch import _rebuild_untrusted

    _make_corpus(tmp_path)
    assert _rebuild_untrusted(tmp_path) is True

    data = json.loads((tmp_path / "graphify-out" / "graph.json").read_text())
    rationale_nodes = [n for n in data["nodes"] if n.get("file_type") == "rationale"]
    assert rationale_nodes == [], (
        "untrusted-corpus mode must not produce rationale nodes — those "
        "carry verbatim docstring text, which is corpus-derived content."
    )


def test_rebuild_untrusted_records_mode_in_graph_json(tmp_path):
    """Acceptance: 'The mode field in graph.json metadata is
    untrusted-corpus.'"""
    from graphify.untrusted import MODE_UNTRUSTED, is_untrusted_corpus_graph
    from graphify.watch import _rebuild_untrusted

    _make_corpus(tmp_path)
    assert _rebuild_untrusted(tmp_path) is True

    data = json.loads((tmp_path / "graphify-out" / "graph.json").read_text())
    assert is_untrusted_corpus_graph(data)
    assert (data.get("graph") or {}).get("mode") == MODE_UNTRUSTED


def test_rebuild_untrusted_does_not_invoke_llm(tmp_path, monkeypatch):
    """The plan: 'zero LLM-generated text from the corpus.' Smoke-check
    by failing if any of the LLM entrypoints is reached."""
    from graphify import llm as llm_mod

    def _boom(*_args, **_kwargs):
        raise AssertionError("LLM call attempted in untrusted-corpus mode")

    monkeypatch.setattr(llm_mod, "extract_files_direct", _boom)
    monkeypatch.setattr(llm_mod, "extract_corpus_parallel", _boom)

    from graphify.watch import _rebuild_untrusted
    _make_corpus(tmp_path)
    assert _rebuild_untrusted(tmp_path) is True


def test_rebuild_untrusted_marks_report_with_mode_banner(tmp_path):
    """Operators reading the rendered report should see the mode."""
    from graphify.watch import _rebuild_untrusted

    _make_corpus(tmp_path)
    assert _rebuild_untrusted(tmp_path) is True

    report = (tmp_path / "graphify-out" / "GRAPH_REPORT.md").read_text(encoding="utf-8")
    assert "untrusted-corpus mode" in report


# ---------- CLI: graphify update --untrusted-corpus


def _run_cli(*args, cwd: Path) -> subprocess.CompletedProcess:
    """Invoke `python -m graphify <args>` in cwd. Returns CompletedProcess."""
    return subprocess.run(
        [sys.executable, "-m", "graphify", *args],
        cwd=cwd, capture_output=True, text=True, env={**__import__("os").environ, "GRAPHIFY_NO_TIPS": "1"},
    )


def test_cli_update_untrusted_corpus_writes_mode(tmp_path):
    _make_corpus(tmp_path)
    result = _run_cli("update", str(tmp_path), "--untrusted-corpus", cwd=tmp_path)
    assert result.returncode == 0, result.stderr

    data = json.loads((tmp_path / "graphify-out" / "graph.json").read_text())
    from graphify.untrusted import is_untrusted_corpus_graph
    assert is_untrusted_corpus_graph(data)


# ---------- CLI: graphify add gating


def _seed_untrusted_graph(root: Path) -> None:
    """Drop a minimal graph.json marked as untrusted-corpus into root."""
    out = root / "graphify-out"
    out.mkdir(parents=True, exist_ok=True)
    (out / "graph.json").write_text(json.dumps({
        "directed": False, "multigraph": False,
        "graph": {"mode": "untrusted-corpus"},
        "nodes": [], "links": [], "hyperedges": [],
    }), encoding="utf-8")


def test_cli_add_refuses_when_graph_is_untrusted(tmp_path):
    _seed_untrusted_graph(tmp_path)
    result = _run_cli("add", "https://example.com/whatever", cwd=tmp_path)
    assert result.returncode == 1
    assert "untrusted-corpus" in result.stderr
    # Did not actually attempt the fetch.
    assert not (tmp_path / "raw").exists()


def test_cli_add_force_overrides_untrusted_gate(tmp_path, monkeypatch):
    """--force lets the user opt back in. We don't actually need the
    fetch to succeed — we only need to confirm the gate let it through.
    Use an obviously-bogus URL and assert the failure mode is the fetch
    failing, not the untrusted-corpus refusal."""
    _seed_untrusted_graph(tmp_path)
    result = _run_cli(
        "add", "https://this-host-will-not-resolve.invalid/x",
        "--force",
        cwd=tmp_path,
    )
    # Either the fetch fails with a network error or a security error —
    # but it must not be the untrusted-corpus refusal.
    combined = (result.stdout + result.stderr).lower()
    assert "untrusted-corpus" not in combined


def test_cli_add_works_normally_without_untrusted_marker(tmp_path):
    """No graph.json or no mode marker → the gate stays open."""
    # Bogus URL so the fetch fails fast — we only care that we got past
    # the untrusted-corpus check.
    result = _run_cli("add", "https://this-host-will-not-resolve.invalid/x", cwd=tmp_path)
    combined = (result.stdout + result.stderr).lower()
    assert "untrusted-corpus" not in combined


# ---------- to_json mode persistence


def test_to_json_persists_mode_under_graph_attrs(tmp_path):
    import networkx as nx
    from graphify.export import to_json

    G = nx.Graph()
    G.add_node("n1", label="A", source_file="a.py")
    out = tmp_path / "graph.json"
    assert to_json(G, {0: ["n1"]}, str(out), mode="untrusted-corpus") is True
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["graph"]["mode"] == "untrusted-corpus"


def test_to_json_omits_mode_when_unset(tmp_path):
    import networkx as nx
    from graphify.export import to_json

    G = nx.Graph()
    G.add_node("n1", label="A", source_file="a.py")
    out = tmp_path / "graph.json"
    assert to_json(G, {0: ["n1"]}, str(out)) is True
    data = json.loads(out.read_text(encoding="utf-8"))
    graph_attrs = data.get("graph") or {}
    assert "mode" not in graph_attrs
