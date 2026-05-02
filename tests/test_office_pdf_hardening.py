"""Adversarial-fixture tests for PDF and Office parser hardening (Task 4.9)."""
from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

from graphify.detect import (
    _office_zip_is_safe,
    _pdf_max_bytes,
    docx_to_markdown,
    extract_pdf_text,
    xlsx_to_markdown,
)


# ---------------------------------------------------------------------------
# PDF hardening
# ---------------------------------------------------------------------------

def test_extract_pdf_text_malformed_returns_empty(tmp_path):
    """A non-PDF blob with the .pdf extension must not raise — bail to ''."""
    bad = tmp_path / "garbage.pdf"
    bad.write_bytes(b"this is not a PDF file")
    assert extract_pdf_text(bad) == ""


def test_extract_pdf_text_truncated_returns_empty(tmp_path):
    """A PDF that starts with the magic bytes but is otherwise truncated."""
    truncated = tmp_path / "truncated.pdf"
    truncated.write_bytes(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj")  # cut off mid-object
    assert extract_pdf_text(truncated) == ""


def test_extract_pdf_text_oversized_refused(tmp_path, monkeypatch):
    """File larger than GRAPHIFY_PDF_MAX_BYTES is refused before parsing."""
    monkeypatch.setenv("GRAPHIFY_PDF_MAX_BYTES", "100")
    big = tmp_path / "big.pdf"
    big.write_bytes(b"%PDF-" + b"x" * 1000)
    assert extract_pdf_text(big) == ""


def test_pdf_max_bytes_default_when_env_unset(monkeypatch):
    monkeypatch.delenv("GRAPHIFY_PDF_MAX_BYTES", raising=False)
    assert _pdf_max_bytes() == 100 * 1024 * 1024


def test_pdf_max_bytes_env_override(monkeypatch):
    monkeypatch.setenv("GRAPHIFY_PDF_MAX_BYTES", "5000000")
    assert _pdf_max_bytes() == 5_000_000


def test_pdf_max_bytes_malformed_falls_back_to_default(monkeypatch):
    """A malformed env value must not crash the parser; fall back to default."""
    monkeypatch.setenv("GRAPHIFY_PDF_MAX_BYTES", "five-megabytes")
    assert _pdf_max_bytes() == 100 * 1024 * 1024


# ---------------------------------------------------------------------------
# Office (docx/xlsx) hardening — pre-flight zip inspection
# ---------------------------------------------------------------------------

def _write_zip_with_entries(path: Path, entries: list[tuple[str, bytes]]) -> None:
    """Helper: build a zipfile with the given (name, body) pairs."""
    with zipfile.ZipFile(str(path), "w", zipfile.ZIP_DEFLATED) as zf:
        for name, body in entries:
            zf.writestr(name, body)


def test_office_zip_safe_accepts_well_formed(tmp_path):
    """A small valid zip (regardless of being a real .docx) passes the gate."""
    p = tmp_path / "fake.docx"
    _write_zip_with_entries(p, [("[Content_Types].xml", b"<xml/>")])
    assert _office_zip_is_safe(p) is True


def test_office_zip_safe_rejects_non_zip(tmp_path):
    """A file with .docx extension that isn't actually a zip is refused."""
    p = tmp_path / "not_actually_a_zip.docx"
    p.write_bytes(b"this is plain text, not a zip")
    assert _office_zip_is_safe(p) is False


def test_office_zip_safe_rejects_zip_bomb(tmp_path, monkeypatch):
    """An archive whose declared uncompressed total exceeds the cap is refused."""
    monkeypatch.setenv("GRAPHIFY_OFFICE_MAX_UNCOMPRESSED_BYTES", "10000")  # 10 KB cap
    p = tmp_path / "bomb.docx"
    # Three 50 KB entries of zero bytes — compresses to a few hundred bytes
    # but reports 150 KB uncompressed in the central directory, well over the
    # 10 KB cap. Mirrors the shape of a real zip bomb without needing GBs.
    _write_zip_with_entries(p, [
        ("a.bin", b"\x00" * 50_000),
        ("b.bin", b"\x00" * 50_000),
        ("c.bin", b"\x00" * 50_000),
    ])
    assert _office_zip_is_safe(p) is False


def test_office_zip_safe_accepts_under_cap(tmp_path, monkeypatch):
    """Right at the cap boundary — strict less-than-or-equal is fine."""
    monkeypatch.setenv("GRAPHIFY_OFFICE_MAX_UNCOMPRESSED_BYTES", "200000")  # 200 KB
    p = tmp_path / "small.docx"
    _write_zip_with_entries(p, [("a.bin", b"\x00" * 50_000)])
    assert _office_zip_is_safe(p) is True


def test_docx_to_markdown_malformed_returns_empty(tmp_path):
    """Non-zip .docx → pre-flight refuses → returns '' without importing docx."""
    p = tmp_path / "bad.docx"
    p.write_bytes(b"definitely not a zip")
    assert docx_to_markdown(p) == ""


def test_xlsx_to_markdown_malformed_returns_empty(tmp_path):
    p = tmp_path / "bad.xlsx"
    p.write_bytes(b"not a zip")
    assert xlsx_to_markdown(p) == ""


def test_docx_to_markdown_zip_bomb_returns_empty(tmp_path, monkeypatch):
    """Zip-bomb-shaped .docx is refused at the pre-flight, before python-docx
    is invoked. The test passes whether or not python-docx is installed —
    the safety gate fires first."""
    monkeypatch.setenv("GRAPHIFY_OFFICE_MAX_UNCOMPRESSED_BYTES", "10000")
    p = tmp_path / "bomb.docx"
    _write_zip_with_entries(p, [
        ("[Content_Types].xml", b"<xml/>"),
        ("payload.bin", b"\x00" * 50_000),
    ])
    assert docx_to_markdown(p) == ""


def test_xlsx_to_markdown_zip_bomb_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("GRAPHIFY_OFFICE_MAX_UNCOMPRESSED_BYTES", "10000")
    p = tmp_path / "bomb.xlsx"
    _write_zip_with_entries(p, [
        ("[Content_Types].xml", b"<xml/>"),
        ("payload.bin", b"\x00" * 50_000),
    ])
    assert xlsx_to_markdown(p) == ""


def test_office_zip_safe_rejects_too_many_entries(tmp_path):
    """Pathological archive with absurd entry count is refused even under
    the size cap (defends against zip-symlink / per-entry-cost attacks)."""
    p = tmp_path / "many.docx"
    with zipfile.ZipFile(str(p), "w", zipfile.ZIP_DEFLATED) as zf:
        for i in range(10_001):
            zf.writestr(f"e{i}.txt", b"x")
    assert _office_zip_is_safe(p) is False
