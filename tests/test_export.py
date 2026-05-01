import json
import tempfile
from pathlib import Path
from graphify.build import build_from_json
from graphify.cluster import cluster
from graphify.export import to_json, to_cypher, to_graphml, to_html, to_canvas

FIXTURES = Path(__file__).parent / "fixtures"

def make_graph():
    return build_from_json(json.loads((FIXTURES / "extraction.json").read_text()))

def test_to_json_creates_file():
    G = make_graph()
    communities = cluster(G)
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "graph.json"
        to_json(G, communities, str(out))
        assert out.exists()

def test_to_json_valid_json():
    G = make_graph()
    communities = cluster(G)
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "graph.json"
        to_json(G, communities, str(out))
        data = json.loads(out.read_text())
        assert "nodes" in data
        assert "links" in data

def test_to_json_nodes_have_community():
    G = make_graph()
    communities = cluster(G)
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "graph.json"
        to_json(G, communities, str(out))
        data = json.loads(out.read_text())
        for node in data["nodes"]:
            assert "community" in node

def test_to_cypher_creates_file():
    G = make_graph()
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "cypher.txt"
        to_cypher(G, str(out))
        assert out.exists()

def test_to_cypher_contains_merge_statements():
    G = make_graph()
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "cypher.txt"
        to_cypher(G, str(out))
        content = out.read_text()
        assert "MERGE" in content

def test_to_graphml_creates_file():
    G = make_graph()
    communities = cluster(G)
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "graph.graphml"
        to_graphml(G, communities, str(out))
        assert out.exists()

def test_to_graphml_valid_xml():
    G = make_graph()
    communities = cluster(G)
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "graph.graphml"
        to_graphml(G, communities, str(out))
        content = out.read_text()
        assert "<graphml" in content
        assert "<node" in content

def test_to_graphml_has_community_attribute():
    G = make_graph()
    communities = cluster(G)
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "graph.graphml"
        to_graphml(G, communities, str(out))
        content = out.read_text()
        assert "community" in content

def test_to_html_creates_file():
    G = make_graph()
    communities = cluster(G)
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "graph.html"
        to_html(G, communities, str(out))
        assert out.exists()

def test_to_html_contains_visjs():
    G = make_graph()
    communities = cluster(G)
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "graph.html"
        to_html(G, communities, str(out))
        content = out.read_text()
        assert "vis-network" in content

def test_to_html_contains_search():
    G = make_graph()
    communities = cluster(G)
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "graph.html"
        to_html(G, communities, str(out))
        content = out.read_text()
        assert "search" in content.lower()

def test_to_html_contains_legend_with_labels():
    G = make_graph()
    communities = cluster(G)
    labels = {cid: f"Group {cid}" for cid in communities}
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "graph.html"
        to_html(G, communities, str(out), community_labels=labels)
        content = out.read_text()
        assert "Group 0" in content

def test_to_html_contains_nodes_and_edges():
    G = make_graph()
    communities = cluster(G)
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "graph.html"
        to_html(G, communities, str(out))
        content = out.read_text()
        assert "RAW_NODES" in content
        assert "RAW_EDGES" in content


def test_to_html_member_counts_accepted():
    """to_html accepts member_counts without raising."""
    G = make_graph()
    communities = cluster(G)
    member_counts = {cid: len(members) for cid, members in communities.items()}
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "graph.html"
        to_html(G, communities, str(out), member_counts=member_counts)
        assert out.exists()


def test_to_html_safe_against_adversarial_content():
    """Generated HTML must survive hostile node labels, edge relations,
    and URL-shaped fields without producing executable script breakout,
    unsafe hrefs, missing CSP, or anchors vulnerable to reverse tabnabbing.

    Regression coverage for Phase 2 (Tasks 2.3a, 2.4): vendor-and-inline,
    CSP meta tag, _safe_href scheme allowlist, sanitize_label coverage.
    """
    import re
    import networkx as nx
    from graphify.export import to_html, _safe_href

    G = nx.Graph()
    G.add_node("evil_label", label="<script>alert(1)</script>", source_file="ok.txt", file_type="document")
    G.add_node("evil_jsurl", label="alpha", source_file="javascript:alert(2)", file_type="document")
    G.add_node("evil_dataurl", label="beta", source_file="data:text/html,<x>", file_type="document")
    G.add_node("normal", label="Gamma", source_file="paper.md", file_type="document")
    G.add_edge("evil_label", "normal", relation="<script>alert(3)</script>", confidence="EXTRACTED")
    G.add_edge("evil_jsurl", "evil_dataurl", relation="referenced", confidence="INFERRED")
    G.graph["hyperedges"] = [{"id": "h1", "label": "<script>alert(4)</script>", "nodes": ["evil_label", "normal"]}]
    communities = {0: ["evil_label", "evil_jsurl", "evil_dataurl", "normal"]}
    labels = {0: "<script>alert(5)</script>"}

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "graph.html"
        to_html(G, communities, str(out), community_labels=labels)
        html = out.read_text()

    # 1. No external <script src=...> after vendor-and-inline.
    #    SRI-path alternative: any external script must carry integrity=.
    for m in re.finditer(r'<script\b[^>]*\bsrc\b[^>]*>', html, re.IGNORECASE):
        assert "integrity" in m.group(0).lower(), \
            f"external script must carry integrity= (SRI): {m.group(0)}"
    assert not re.search(r'<script[^>]*\bsrc\s*=', html, re.IGNORECASE), \
        "vendor-and-inline path: generated HTML must not load any external script"

    # 2. No <a target="_blank"> without rel="noopener noreferrer".
    #    (Today there are zero anchors; this enforces the invariant for any future emission.)
    for m in re.finditer(r"<a\b[^>]*\btarget\s*=\s*[\"']_blank[\"'][^>]*>", html, re.IGNORECASE):
        tag = m.group(0).lower()
        assert "noopener" in tag and "noreferrer" in tag, \
            f'target="_blank" anchor must include rel="noopener noreferrer": {m.group(0)}'

    # 3. Adversarial labels are not interpreted as tags. _js_safe replaces
    #    '</' with '<\\/' before interpolation, so the closing </script>
    #    introduced by hostile content cannot terminate the surrounding script.
    for n in (1, 3, 4, 5):
        assert f"alert({n})</script>" not in html, \
            f"adversarial label alert({n}) leaked an unescaped </script> into output"
    # 3b. The HTML parser must see exactly three real <script> elements (the
    #     vendored vis-network bundle, _html_script, _hyperedge_script). A
    #     breakout would terminate one of those early and start a new one,
    #     bumping the parser's tally above three. Counting via the parser
    #     (rather than a regex) ignores literal "<script" substrings that
    #     appear inside the vis-network bundle's source text.
    from html.parser import HTMLParser

    class _ScriptCounter(HTMLParser):
        def __init__(self):
            super().__init__()
            self.count = 0
        def handle_starttag(self, tag, attrs):
            if tag == "script":
                self.count += 1

    counter = _ScriptCounter()
    counter.feed(html)
    assert counter.count == 3, \
        f"expected 3 <script> elements, parser saw {counter.count} — possible breakout"

    # 4. CSP meta tag is present with the hardening directives we rely on.
    csp = re.search(
        r'<meta\s+http-equiv="Content-Security-Policy"\s+content="([^"]+)"',
        html,
    )
    assert csp, "CSP meta tag must be present in generated HTML"
    policy = csp.group(1)
    assert "default-src 'self'" in policy
    assert "connect-src 'none'" in policy
    assert "object-src 'none'" in policy
    assert "base-uri 'none'" in policy
    assert "'unsafe-eval'" not in policy, "policy must not allow unsafe-eval"

    # 5. _safe_href scheme allowlist rejects dangerous URI schemes — including
    #    leading whitespace/control-char smuggling — and passes through safe ones.
    assert _safe_href("javascript:alert(1)") == "#"
    assert _safe_href("JAVASCRIPT:alert(1)") == "#"
    assert _safe_href("\tjavascript:alert(1)") == "#"
    assert _safe_href("\x00javascript:alert(1)") == "#"
    assert _safe_href("data:text/html,<x>") == "#"
    assert _safe_href("vbscript:msgbox") == "#"
    assert _safe_href("https://example.com/a") == "https://example.com/a"
    assert _safe_href("http://example.com/a") == "http://example.com/a"
    assert _safe_href("file:///tmp/x") == "file:///tmp/x"
    assert _safe_href("file:///tmp/x", allow_file=False) == "#"


def test_to_canvas_file_paths_relative_to_vault():
    """Node file paths in canvas must be vault-root-relative (just fname.md), not hardcoded."""
    G = make_graph()
    communities = cluster(G)
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "graph.canvas"
        to_canvas(G, communities, str(out))
        data = json.loads(out.read_text())
        file_nodes = [n for n in data["nodes"] if n.get("type") == "file"]
        assert file_nodes, "canvas should contain file nodes"
        for node in file_nodes:
            assert "/" not in node["file"], f"file path should not contain '/': {node['file']}"
            assert node["file"].endswith(".md")
