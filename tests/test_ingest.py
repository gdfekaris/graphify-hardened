"""Tests for graphify.ingest.save_query_result and content-type validation."""
from __future__ import annotations
import re
from pathlib import Path
from unittest.mock import patch

import pytest

from graphify.ingest import (
    _ALLOWED_CONTENT_TYPES,
    _check_content_type,
    ingest,
    save_query_result,
)


def test_file_created(tmp_path):
    out = save_query_result("what is attention?", "Attention is...", tmp_path / "memory")
    assert out.exists()


def test_filename_format(tmp_path):
    mem = tmp_path / "memory"
    out = save_query_result("what connects A to B?", "They share...", mem)
    assert out.name.startswith("query_")
    assert out.suffix == ".md"


def test_frontmatter_question(tmp_path):
    mem = tmp_path / "memory"
    question = "what is attention?"
    out = save_query_result(question, "Attention is softmax.", mem)
    content = out.read_text()
    assert "question:" in content
    assert "attention" in content.lower()


def test_frontmatter_type(tmp_path):
    mem = tmp_path / "memory"
    out = save_query_result("q", "a", mem, query_type="path_query")
    content = out.read_text()
    assert 'type: "path_query"' in content


def test_source_nodes_included(tmp_path):
    mem = tmp_path / "memory"
    nodes = ["AttentionLayer", "SoftmaxFunc"]
    out = save_query_result("q", "a", mem, source_nodes=nodes)
    content = out.read_text()
    assert "AttentionLayer" in content
    assert "SoftmaxFunc" in content


def test_source_nodes_capped_at_10(tmp_path):
    mem = tmp_path / "memory"
    nodes = [f"Node{i}" for i in range(20)]
    out = save_query_result("q", "a", mem, source_nodes=nodes)
    content = out.read_text()
    # Only first 10 should appear in frontmatter source_nodes line
    fm_line = [l for l in content.splitlines() if l.startswith("source_nodes:")][0]
    assert fm_line.count('"Node') == 10


def test_memory_dir_created(tmp_path):
    mem = tmp_path / "deep" / "memory"
    assert not mem.exists()
    save_query_result("q", "a", mem)
    assert mem.exists()


def test_answer_in_body(tmp_path):
    mem = tmp_path / "memory"
    answer = "The answer is forty-two."
    out = save_query_result("what is the answer?", answer, mem)
    content = out.read_text()
    assert answer in content


# ---------------------------------------------------------------------------
# Content-type validation (Task 4.3)
# ---------------------------------------------------------------------------

def test_check_content_type_strips_parameters():
    # "text/html; charset=utf-8" should match the "text/html" prefix.
    _check_content_type("text/html; charset=utf-8", ("text/html",), "https://example.com/")

def test_check_content_type_image_prefix_matches_subtypes():
    _check_content_type("image/png", ("image/",), "https://example.com/x.png")
    _check_content_type("image/jpeg", ("image/",), "https://example.com/x.jpg")

def test_check_content_type_raises_on_mismatch():
    with pytest.raises(ValueError, match="content-type"):
        _check_content_type("text/html", ("application/pdf",), "https://example.com/x.pdf")

def test_check_content_type_warns_when_strict_disabled(monkeypatch):
    monkeypatch.setenv("GRAPHIFY_CONTENT_TYPE_STRICT", "0")
    with pytest.warns(RuntimeWarning, match="content-type"):
        _check_content_type("text/html", ("application/pdf",), "https://example.com/x.pdf")

def test_check_content_type_strict_default_when_env_unset(monkeypatch):
    monkeypatch.delenv("GRAPHIFY_CONTENT_TYPE_STRICT", raising=False)
    with pytest.raises(ValueError):
        _check_content_type("text/html", ("application/pdf",), "https://example.com/x.pdf")


def test_ingest_pdf_accepts_application_pdf(tmp_path, monkeypatch):
    monkeypatch.delenv("GRAPHIFY_CONTENT_TYPE_STRICT", raising=False)
    with patch(
        "graphify.ingest.safe_fetch_with_headers",
        return_value=(b"%PDF-1.4 fake bytes", {"content-type": "application/pdf"}),
    ):
        out = ingest("https://example.com/paper.pdf", tmp_path)
    assert out.exists()
    assert out.suffix == ".pdf"
    assert out.read_bytes() == b"%PDF-1.4 fake bytes"

def test_ingest_pdf_rejects_html_response(tmp_path, monkeypatch):
    monkeypatch.delenv("GRAPHIFY_CONTENT_TYPE_STRICT", raising=False)
    with patch(
        "graphify.ingest.safe_fetch_with_headers",
        return_value=(b"<html>oops</html>", {"content-type": "text/html"}),
    ):
        with pytest.raises(ValueError, match="content-type"):
            ingest("https://example.com/paper.pdf", tmp_path)

def test_ingest_pdf_warns_under_strict_disabled(tmp_path, monkeypatch):
    monkeypatch.setenv("GRAPHIFY_CONTENT_TYPE_STRICT", "0")
    with patch(
        "graphify.ingest.safe_fetch_with_headers",
        return_value=(b"<html>oops</html>", {"content-type": "text/html"}),
    ):
        with pytest.warns(RuntimeWarning, match="content-type"):
            out = ingest("https://example.com/paper.pdf", tmp_path)
    assert out.exists()  # downgrade to warn → file is still written

def test_ingest_image_accepts_image_subtype(tmp_path, monkeypatch):
    monkeypatch.delenv("GRAPHIFY_CONTENT_TYPE_STRICT", raising=False)
    with patch(
        "graphify.ingest.safe_fetch_with_headers",
        return_value=(b"\x89PNG\r\n\x1a\n", {"content-type": "image/png"}),
    ):
        out = ingest("https://example.com/diagram.png", tmp_path)
    assert out.exists()
    assert out.suffix == ".png"

def test_ingest_image_rejects_non_image_response(tmp_path, monkeypatch):
    monkeypatch.delenv("GRAPHIFY_CONTENT_TYPE_STRICT", raising=False)
    with patch(
        "graphify.ingest.safe_fetch_with_headers",
        return_value=(b"<html>oops</html>", {"content-type": "text/html"}),
    ):
        with pytest.raises(ValueError, match="content-type"):
            ingest("https://example.com/diagram.png", tmp_path)

def test_ingest_webpage_charset_suffix_accepted(tmp_path, monkeypatch):
    monkeypatch.delenv("GRAPHIFY_CONTENT_TYPE_STRICT", raising=False)
    html = b"<html><head><title>hi</title></head><body>hello</body></html>"
    with patch(
        "graphify.ingest.safe_fetch_text_with_headers",
        return_value=(html.decode(), {"content-type": "text/html; charset=utf-8"}),
    ):
        out = ingest("https://example.com/page", tmp_path)
    assert out.exists()
    assert out.suffix == ".md"

def test_ingest_webpage_rejects_pdf_response(tmp_path, monkeypatch):
    monkeypatch.delenv("GRAPHIFY_CONTENT_TYPE_STRICT", raising=False)
    with patch(
        "graphify.ingest.safe_fetch_text_with_headers",
        return_value=("%PDF binary masquerading as text", {"content-type": "application/pdf"}),
    ):
        with pytest.raises(ValueError, match="content-type"):
            ingest("https://example.com/page", tmp_path)

def test_allowed_content_types_table_has_expected_keys():
    # Regression guard: every URL type that ingest() routes to a fetch path
    # should have an entry in the allowlist.
    for key in ("tweet", "arxiv", "webpage", "pdf", "image"):
        assert key in _ALLOWED_CONTENT_TYPES
