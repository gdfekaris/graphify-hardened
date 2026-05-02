"""Tests for graphify/security.py - URL validation, safe fetch, path guards, label sanitisation."""
from __future__ import annotations

import contextlib
import json
import socket
import threading
import urllib.error
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from graphify.security import (
    sanitize_label,
    safe_fetch,
    safe_fetch_text,
    validate_graph_path,
    validate_url,
    _MAX_FETCH_BYTES,
    _MAX_TEXT_BYTES,
    _MAX_TEXT_BYTES_HARD_CAP,
    _resolved_text_max_bytes,
)


# ---------------------------------------------------------------------------
# validate_url
# ---------------------------------------------------------------------------

def test_validate_url_accepts_http():
    assert validate_url("http://example.com/page") == "http://example.com/page"

def test_validate_url_accepts_https():
    assert validate_url("https://arxiv.org/abs/1706.03762") == "https://arxiv.org/abs/1706.03762"

def test_validate_url_rejects_file():
    with pytest.raises(ValueError, match="file"):
        validate_url("file:///etc/passwd")

def test_validate_url_rejects_ftp():
    with pytest.raises(ValueError, match="ftp"):
        validate_url("ftp://files.example.com/data.zip")

def test_validate_url_rejects_data():
    with pytest.raises(ValueError, match="data"):
        validate_url("data:text/html,<script>alert(1)</script>")

def test_validate_url_rejects_empty_scheme():
    with pytest.raises(ValueError):
        validate_url("//no-scheme.example.com")


# ---------------------------------------------------------------------------
# validate_url - GRAPHIFY_FETCH_ALLOWLIST gate
# ---------------------------------------------------------------------------

def test_validate_url_allowlist_permits_listed_host(monkeypatch):
    monkeypatch.setenv("GRAPHIFY_FETCH_ALLOWLIST", "arxiv.org,example.com")
    assert validate_url("https://arxiv.org/abs/1706.03762") == "https://arxiv.org/abs/1706.03762"

def test_validate_url_allowlist_rejects_unlisted_host(monkeypatch):
    monkeypatch.setenv("GRAPHIFY_FETCH_ALLOWLIST", "arxiv.org")
    with pytest.raises(ValueError, match="GRAPHIFY_FETCH_ALLOWLIST"):
        validate_url("https://example.com/foo")

def test_validate_url_allowlist_does_not_bypass_ip_range_check(monkeypatch):
    # Even with the IP literal in the allowlist, the private-IP check fires first.
    monkeypatch.setenv("GRAPHIFY_FETCH_ALLOWLIST", "127.0.0.1")
    with pytest.raises(ValueError, match="private/internal IP"):
        validate_url("http://127.0.0.1/admin")

def test_validate_url_allowlist_unset_preserves_existing_behavior(monkeypatch):
    monkeypatch.delenv("GRAPHIFY_FETCH_ALLOWLIST", raising=False)
    assert validate_url("https://example.com/foo") == "https://example.com/foo"


# ---------------------------------------------------------------------------
# safe_fetch - scheme and redirect guards (mocked network)
# ---------------------------------------------------------------------------

def _make_mock_response(content: bytes, status: int = 200):
    mock = MagicMock()
    mock.__enter__ = lambda s: s
    mock.__exit__ = MagicMock(return_value=False)
    mock.status = status
    mock.code = status
    chunks = [content[i:i+65536] for i in range(0, len(content), 65536)] + [b""]
    mock.read.side_effect = chunks
    return mock


def test_safe_fetch_rejects_file_url():
    with pytest.raises(ValueError, match="file"):
        safe_fetch("file:///etc/passwd")

def test_safe_fetch_rejects_ftp_url():
    with pytest.raises(ValueError, match="ftp"):
        safe_fetch("ftp://example.com/file.zip")

def test_safe_fetch_returns_bytes(tmp_path):
    mock_resp = _make_mock_response(b"hello world")
    with patch("graphify.security._build_opener") as mock_opener_fn:
        mock_opener = MagicMock()
        mock_opener.open.return_value = mock_resp
        mock_opener_fn.return_value = mock_opener
        result = safe_fetch("https://example.com/")
    assert result == b"hello world"

def test_safe_fetch_raises_on_non_2xx():
    mock_resp = _make_mock_response(b"Not Found", status=404)
    with patch("graphify.security._build_opener") as mock_opener_fn:
        mock_opener = MagicMock()
        mock_opener.open.return_value = mock_resp
        mock_opener_fn.return_value = mock_opener
        with pytest.raises(urllib.error.HTTPError):
            safe_fetch("https://example.com/missing")

def test_safe_fetch_raises_on_size_exceeded():
    # Build a response larger than max_bytes
    big_chunk = b"x" * 65_537
    mock_resp = MagicMock()
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    mock_resp.status = 200
    mock_resp.code = 200
    # Return the chunk twice so total > max_bytes=65536
    mock_resp.read.side_effect = [big_chunk, big_chunk, b""]

    with patch("graphify.security._build_opener") as mock_opener_fn:
        mock_opener = MagicMock()
        mock_opener.open.return_value = mock_resp
        mock_opener_fn.return_value = mock_opener
        with pytest.raises(OSError, match="size limit"):
            safe_fetch("https://example.com/huge", max_bytes=65_536)


# ---------------------------------------------------------------------------
# safe_fetch_text
# ---------------------------------------------------------------------------

def test_safe_fetch_text_decodes_utf8():
    content = "héllo wörld".encode("utf-8")
    mock_resp = _make_mock_response(content)
    with patch("graphify.security._build_opener") as mock_opener_fn:
        mock_opener = MagicMock()
        mock_opener.open.return_value = mock_resp
        mock_opener_fn.return_value = mock_opener
        result = safe_fetch_text("https://example.com/")
    assert result == "héllo wörld"

def test_safe_fetch_text_replaces_bad_bytes():
    bad = b"hello \xff world"
    mock_resp = _make_mock_response(bad)
    with patch("graphify.security._build_opener") as mock_opener_fn:
        mock_opener = MagicMock()
        mock_opener.open.return_value = mock_resp
        mock_opener_fn.return_value = mock_opener
        result = safe_fetch_text("https://example.com/")
    assert "hello" in result
    assert "world" in result
    assert "\xff" not in result


# ---------------------------------------------------------------------------
# safe_fetch_text - default cap and GRAPHIFY_MAX_TEXT_BYTES override
# ---------------------------------------------------------------------------

def test_safe_fetch_text_default_cap_is_2_mb():
    assert _MAX_TEXT_BYTES == 2_097_152

def test_resolved_text_max_bytes_unset_returns_default(monkeypatch):
    monkeypatch.delenv("GRAPHIFY_MAX_TEXT_BYTES", raising=False)
    assert _resolved_text_max_bytes() == _MAX_TEXT_BYTES

def test_resolved_text_max_bytes_env_override(monkeypatch):
    monkeypatch.setenv("GRAPHIFY_MAX_TEXT_BYTES", "1048576")  # 1 MB
    assert _resolved_text_max_bytes() == 1_048_576

def test_resolved_text_max_bytes_clamps_to_50_mb(monkeypatch):
    monkeypatch.setenv("GRAPHIFY_MAX_TEXT_BYTES", "104857600")  # 100 MB
    assert _resolved_text_max_bytes() == _MAX_TEXT_BYTES_HARD_CAP == 52_428_800

def test_resolved_text_max_bytes_rejects_malformed(monkeypatch):
    monkeypatch.setenv("GRAPHIFY_MAX_TEXT_BYTES", "ten-megabytes")
    with pytest.raises(ValueError, match="positive integer"):
        _resolved_text_max_bytes()

def test_resolved_text_max_bytes_rejects_non_positive(monkeypatch):
    monkeypatch.setenv("GRAPHIFY_MAX_TEXT_BYTES", "0")
    with pytest.raises(ValueError, match="positive integer"):
        _resolved_text_max_bytes()


# ---------------------------------------------------------------------------
# validate_graph_path
# ---------------------------------------------------------------------------

def test_validate_graph_path_allows_inside_base(tmp_path):
    base = tmp_path / "graphify-out"
    base.mkdir()
    graph = base / "graph.json"
    graph.write_text("{}")
    result = validate_graph_path(str(graph), base=base)
    assert result == graph.resolve()

def test_validate_graph_path_blocks_traversal(tmp_path):
    base = tmp_path / "graphify-out"
    base.mkdir()
    evil = tmp_path / "graphify-out" / ".." / "etc_passwd"
    with pytest.raises(ValueError, match="escapes"):
        validate_graph_path(str(evil), base=base)

def test_validate_graph_path_requires_base_exists(tmp_path):
    base = tmp_path / "graphify-out"  # not created
    with pytest.raises(ValueError, match="does not exist"):
        validate_graph_path(str(base / "graph.json"), base=base)

def test_validate_graph_path_raises_if_file_missing(tmp_path):
    base = tmp_path / "graphify-out"
    base.mkdir()
    with pytest.raises(FileNotFoundError):
        validate_graph_path(str(base / "missing.json"), base=base)


# ---------------------------------------------------------------------------
# sanitize_label
# ---------------------------------------------------------------------------

def test_sanitize_label_passthrough_html_chars():
    # sanitize_label does NOT HTML-escape — callers that inject into HTML must
    # wrap with html.escape() themselves (e.g. the title in to_html())
    assert sanitize_label("<script>") == "<script>"
    assert sanitize_label("foo & bar") == "foo & bar"

def test_sanitize_label_strips_control_chars():
    result = sanitize_label("hello\x00\x1fworld")
    assert "\x00" not in result
    assert "\x1f" not in result
    assert "helloworld" in result

def test_sanitize_label_caps_at_256():
    long_label = "a" * 300
    assert len(sanitize_label(long_label)) <= 256

def test_sanitize_label_safe_passthrough():
    assert sanitize_label("MyClass") == "MyClass"
    assert sanitize_label("extract_python") == "extract_python"


# ---------------------------------------------------------------------------
# SSRF redirect-chain regression tests (Phase 7.1)
#
# These exercise _NoFileRedirectHandler against a real local HTTP server so
# the redirect-time validate_url() call is hit end-to-end. The fixture binds
# to 127.0.0.1:<ephemeral>, so safe_fetch's normal entry-URL guards
# (validate_url's loopback check, and _ssrf_guarded_socket) are bypassed for
# the test-server origin only — redirect targets still go through the real
# validation. Deleting _NoFileRedirectHandler causes every test below to
# fail (urllib's default redirect handler does not re-validate http->http
# redirects, so the safe_fetch call raises a different exception type or
# none at all).
# ---------------------------------------------------------------------------

class _RoutingHandler(BaseHTTPRequestHandler):
    """Serves whatever the per-server route table says for self.path."""

    def do_GET(self):  # noqa: N802 - BaseHTTPRequestHandler API
        entry = self.server.routes.get(self.path)  # type: ignore[attr-defined]
        if entry is None:
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        status, location, body = entry
        self.send_response(status)
        if location is not None:
            self.send_header("Location", location)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def log_message(self, format, *args):  # noqa: A002 - matches stdlib API
        # Silence default stderr access log so pytest output stays clean.
        return


class _RedirectServer:
    """Context-managed HTTP server for redirect-chain tests."""

    def __init__(self) -> None:
        self._httpd: HTTPServer | None = None
        self._thread: threading.Thread | None = None
        self.routes: dict[str, tuple[int, str | None, bytes]] = {}

    def __enter__(self) -> "_RedirectServer":
        self._httpd = HTTPServer(("127.0.0.1", 0), _RoutingHandler)
        # Stash the route table on the server so the handler can reach it
        # (BaseHTTPRequestHandler instances are constructed per-request).
        self._httpd.routes = self.routes  # type: ignore[attr-defined]
        self._thread = threading.Thread(
            target=self._httpd.serve_forever, daemon=True
        )
        self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        assert self._httpd is not None
        self._httpd.shutdown()
        self._httpd.server_close()
        if self._thread is not None:
            self._thread.join(timeout=2)

    @property
    def origin(self) -> str:
        assert self._httpd is not None
        host, port = self._httpd.server_address[:2]
        return f"http://{host}:{port}"

    def add_redirect(self, path: str, location: str, status: int = 302) -> str:
        self.routes[path] = (status, location, b"")
        return self.origin + path

    def add_ok(self, path: str, body: bytes = b"OK") -> str:
        self.routes[path] = (200, None, body)
        return self.origin + path


@contextlib.contextmanager
def _allow_test_origin(origin: str):
    """Let safe_fetch reach a 127.0.0.1 test server while leaving the redirect
    handler's validate_url() call fully active for every other URL.

    Two patches:
    - graphify.security.validate_url -> wrapper that short-circuits ONLY when
      the URL matches the test-server origin (exact origin or origin + '/...').
      Redirect targets to anywhere else (file://, 127.0.0.1:80, 10.0.0.1, the
      cloud-metadata hostnames, etc.) fall through to the real validator.
    - graphify.security._ssrf_guarded_socket -> nullcontext so the actual
      TCP connection to 127.0.0.1:<port> is not blocked by the connect-time
      IP guard. The redirect handler is the security primitive under test
      here; _ssrf_guarded_socket is exercised separately by validate_url's
      direct tests.
    """
    real = validate_url

    def wrapper(url: str) -> str:
        if url == origin or url.startswith(origin + "/"):
            return url
        return real(url)

    with patch("graphify.security.validate_url", wrapper), \
            patch("graphify.security._ssrf_guarded_socket", contextlib.nullcontext):
        yield


def test_safe_fetch_follows_legitimate_in_server_redirect():
    # Sanity-check the fixture: a 302 to another path on the same test server
    # is followed and the terminal body is returned.
    with _RedirectServer() as srv:
        srv.add_ok("/final", b"hello")
        url = srv.add_redirect("/start", srv.origin + "/final")
        with _allow_test_origin(srv.origin):
            result = safe_fetch(url)
    assert result == b"hello"


def test_safe_fetch_blocks_redirect_to_file_scheme():
    # Layered defense: stdlib urllib's http_error_302 pre-checks the redirect
    # target's scheme against (http, https, ftp) and raises HTTPError before
    # our _NoFileRedirectHandler.redirect_request is even called for file://.
    # _NoFileRedirectHandler is the second line — it catches non-file but
    # otherwise-acceptable-to-urllib targets that fail validate_url (covered
    # by the IP-range and metadata tests below). What we assert here is that
    # the malicious redirect does not succeed.
    with _RedirectServer() as srv:
        url = srv.add_redirect("/start", "file:///etc/passwd")
        with _allow_test_origin(srv.origin):
            with pytest.raises((ValueError, urllib.error.HTTPError), match="file"):
                safe_fetch(url)


def test_safe_fetch_blocks_redirect_to_loopback_ip():
    # Test server runs on an ephemeral port; the redirect target uses no port
    # (port 80), so the wrapper does NOT short-circuit and real validate_url
    # rejects 127.0.0.1 as loopback.
    with _RedirectServer() as srv:
        url = srv.add_redirect("/start", "http://127.0.0.1/admin")
        with _allow_test_origin(srv.origin):
            with pytest.raises(ValueError, match="private/internal IP"):
                safe_fetch(url)


def test_safe_fetch_blocks_redirect_to_private_ip():
    with _RedirectServer() as srv:
        url = srv.add_redirect("/start", "http://10.0.0.1/")
        with _allow_test_origin(srv.origin):
            with pytest.raises(ValueError, match="private/internal IP"):
                safe_fetch(url)


def test_safe_fetch_blocks_redirect_to_link_local_metadata_ip():
    # 169.254.169.254 is the AWS/Azure/GCP IMDS endpoint by IP.
    with _RedirectServer() as srv:
        url = srv.add_redirect("/start", "http://169.254.169.254/latest/meta-data/")
        with _allow_test_origin(srv.origin):
            with pytest.raises(ValueError, match="private/internal IP"):
                safe_fetch(url)


def test_safe_fetch_blocks_metadata_endpoint_at_end_of_chain():
    # Three-hop chain A -> B -> http://metadata.google.internal/.
    # validate_url's _BLOCKED_HOSTS check fires before any DNS work, so this
    # raises at the redirect-time validate_url() call, not at connect time.
    with _RedirectServer() as srv:
        srv.add_redirect("/a", srv.origin + "/b")
        srv.add_redirect("/b", "http://metadata.google.internal/computeMetadata/v1/")
        url = srv.origin + "/a"
        with _allow_test_origin(srv.origin):
            with pytest.raises(ValueError, match="metadata"):
                safe_fetch(url)


def test_safe_fetch_blocks_redirect_to_dns_rebound_hostname(monkeypatch):
    """A hostname whose DNS resolution returns a private IP is rejected when
    the redirect handler re-runs validate_url on the redirect target. This
    is the redirect-time half of DNS-rebinding defense; the connect-time
    half (validate_url saw a public IP, then getaddrinfo flipped to a
    private IP between validation and connect) is owned by
    _ssrf_guarded_socket and covered by validate_url's own IP-range tests.
    """
    real_getaddrinfo = socket.getaddrinfo

    def stubbed(host, port, *args, **kwargs):
        if host == "rebind.invalid":
            return [(
                socket.AF_INET, socket.SOCK_STREAM, 6, "",
                ("127.0.0.1", port or 0),
            )]
        return real_getaddrinfo(host, port, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", stubbed)

    with _RedirectServer() as srv:
        url = srv.add_redirect("/start", "http://rebind.invalid/final")
        with _allow_test_origin(srv.origin):
            with pytest.raises(ValueError, match="private/internal IP"):
                safe_fetch(url)
