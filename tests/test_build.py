import json
from pathlib import Path
from graphify.build import build_from_json, build

FIXTURES = Path(__file__).parent / "fixtures"

def load_extraction():
    return json.loads((FIXTURES / "extraction.json").read_text())

def test_build_from_json_node_count():
    G = build_from_json(load_extraction())
    assert G.number_of_nodes() == 4

def test_build_from_json_edge_count():
    G = build_from_json(load_extraction())
    assert G.number_of_edges() == 4

def test_nodes_have_label():
    G = build_from_json(load_extraction())
    assert G.nodes["n_transformer"]["label"] == "Transformer"

def test_edges_have_confidence():
    G = build_from_json(load_extraction())
    data = G.edges["n_attention", "n_concept_attn"]
    assert data["confidence"] == "INFERRED"

def test_ambiguous_edge_preserved():
    G = build_from_json(load_extraction())
    data = G.edges["n_layernorm", "n_concept_attn"]
    assert data["confidence"] == "AMBIGUOUS"

def test_legacy_node_source_canonicalized():
    """Legacy 'source' key on nodes is renamed to 'source_file' before graph build."""
    ext = {"nodes": [{"id": "n1", "label": "A", "file_type": "code", "source": "a.py"}],
           "edges": [], "input_tokens": 0, "output_tokens": 0}
    G = build_from_json(ext)
    assert "source_file" in G.nodes["n1"]
    assert G.nodes["n1"]["source_file"] == "a.py"
    assert "source" not in G.nodes["n1"]


def test_legacy_edge_from_to_canonicalized():
    """Legacy 'from'/'to' keys on edges are accepted alongside 'source'/'target'."""
    ext = {"nodes": [{"id": "n1", "label": "A", "file_type": "code", "source_file": "a.py"},
                     {"id": "n2", "label": "B", "file_type": "code", "source_file": "b.py"}],
           "edges": [{"from": "n1", "to": "n2", "relation": "calls",
                      "confidence": "EXTRACTED", "source_file": "a.py", "weight": 1.0}],
           "input_tokens": 0, "output_tokens": 0}
    G = build_from_json(ext)
    assert G.number_of_edges() == 1


def test_build_merges_multiple_extractions():
    ext1 = {"nodes": [{"id": "n1", "label": "A", "file_type": "code", "source_file": "a.py"}],
            "edges": [], "input_tokens": 0, "output_tokens": 0}
    ext2 = {"nodes": [{"id": "n2", "label": "B", "file_type": "document", "source_file": "b.md"}],
            "edges": [{"source": "n1", "target": "n2", "relation": "references",
                       "confidence": "INFERRED", "source_file": "b.md", "weight": 1.0}],
            "input_tokens": 0, "output_tokens": 0}
    G = build([ext1, ext2])
    assert G.number_of_nodes() == 2
    assert G.number_of_edges() == 1


def test_every_node_has_non_empty_provenance():
    """Phase 3.2 acceptance: every node in a freshly-built graph carries
    a non-empty provenance list recording its corpus origin."""
    G = build_from_json(load_extraction())
    for nid, data in G.nodes(data=True):
        assert "provenance" in data, f"node {nid!r} missing provenance"
        assert isinstance(data["provenance"], list), f"node {nid!r} provenance not a list"
        assert data["provenance"], f"node {nid!r} has empty provenance"
        assert all(isinstance(p, str) and p for p in data["provenance"])


def test_provenance_defaults_to_source_file():
    ext = {"nodes": [{"id": "n1", "label": "A", "file_type": "code", "source_file": "a.py"}],
           "edges": [], "input_tokens": 0, "output_tokens": 0}
    G = build_from_json(ext)
    assert G.nodes["n1"]["provenance"] == ["a.py"]


def test_provenance_unions_across_extractions():
    """When the same node id appears in two extractions with different
    source_files, build() unions their provenance instead of letting the
    second silently overwrite the first."""
    ext1 = {"nodes": [{"id": "n1", "label": "Shared", "file_type": "code", "source_file": "a.py"}],
            "edges": [], "input_tokens": 0, "output_tokens": 0}
    ext2 = {"nodes": [{"id": "n1", "label": "Shared", "file_type": "code", "source_file": "b.py"}],
            "edges": [], "input_tokens": 0, "output_tokens": 0}
    G = build([ext1, ext2])
    assert G.nodes["n1"]["provenance"] == ["a.py", "b.py"]


def test_provenance_preserves_explicit_value():
    """If an extraction already carries a provenance list (e.g. a graph
    re-loaded from graph.json), build_from_json preserves it rather than
    overwriting with [source_file]."""
    ext = {
        "nodes": [{
            "id": "n1", "label": "A", "file_type": "code",
            "source_file": "a.py", "provenance": ["a.py", "b.py"],
        }],
        "edges": [], "input_tokens": 0, "output_tokens": 0,
    }
    G = build_from_json(ext)
    assert G.nodes["n1"]["provenance"] == ["a.py", "b.py"]


def test_provenance_falls_back_to_sentinel_when_source_missing():
    """A malformed extraction with no source_file still produces a
    non-empty provenance — the sentinel surfaces the gap to downstream
    consumers (e.g. status reporting) instead of silently dropping it."""
    ext = {
        "nodes": [{"id": "n1", "label": "A", "file_type": "code"}],
        "edges": [], "input_tokens": 0, "output_tokens": 0,
    }
    G = build_from_json(ext)
    prov = G.nodes["n1"]["provenance"]
    assert prov == ["<unknown>"]


def test_deduplicate_by_label_unions_provenance():
    from graphify.build import deduplicate_by_label
    nodes = [
        {"id": "model_attention", "label": "Attention", "file_type": "code", "source_file": "model.py"},
        {"id": "paper_attention", "label": "Attention", "file_type": "document", "source_file": "paper.md"},
    ]
    deduped, _ = deduplicate_by_label(nodes, [])
    assert len(deduped) == 1
    assert sorted(deduped[0]["provenance"]) == ["model.py", "paper.md"]
