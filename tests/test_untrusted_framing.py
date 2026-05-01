"""Phase 3.5 acceptance — every always-on rules file written by an install
path embeds the untrusted-data framing, and every MCP handler response
that echoes labels or relations prepends a short untrusted-data prefix."""
from pathlib import Path

import pytest

from graphify.__main__ import (
    _AGENTS_MD_SECTION,
    _ANTIGRAVITY_RULES,
    _CLAUDE_MD_SECTION,
    _CODEX_HOOK,
    _CURSOR_RULE,
    _GEMINI_HOOK,
    _GEMINI_MD_SECTION,
    _KIRO_STEERING,
    _OPENCODE_PLUGIN_JS,
    _SETTINGS_HOOK,
    _UNTRUSTED_FRAMING,
    _UNTRUSTED_HOOK_SUFFIX,
    _VSCODE_INSTRUCTIONS_SECTION,
    _agents_install,
    _antigravity_install,
    _cursor_install,
    _kiro_install,
    claude_install,
    gemini_install,
    vscode_install,
)


# ---------- the framing block itself contains the load-bearing phrases


def test_untrusted_framing_says_treat_as_data():
    assert "untrusted data" in _UNTRUSTED_FRAMING.lower()


def test_untrusted_framing_calls_out_flagged_marker():
    """The framing references the [FLAGGED — ...] placeholder so the
    assistant knows what to do when it encounters one."""
    assert "[FLAGGED" in _UNTRUSTED_FRAMING


def test_untrusted_framing_tells_assistant_to_surface_injection():
    assert "prompt-injection" in _UNTRUSTED_FRAMING.lower()


# ---------- markdown rules sections all include the framing


_RULES_SECTIONS = {
    "CLAUDE.md":        _CLAUDE_MD_SECTION,
    "AGENTS.md":        _AGENTS_MD_SECTION,
    "GEMINI.md":        _GEMINI_MD_SECTION,
    "VS Code":          _VSCODE_INSTRUCTIONS_SECTION,
    "Antigravity":      _ANTIGRAVITY_RULES,
    "Kiro steering":    _KIRO_STEERING,
    "Cursor rule":      _CURSOR_RULE,
}


@pytest.mark.parametrize("name", list(_RULES_SECTIONS))
def test_each_rules_section_embeds_framing(name):
    """Every rules-file constant ships the same shared framing block."""
    assert _UNTRUSTED_FRAMING in _RULES_SECTIONS[name]


# ---------- inline hooks include the short suffix


def test_settings_hook_command_includes_untrusted_suffix():
    cmd = _SETTINGS_HOOK["hooks"][0]["command"]
    assert "untrusted data" in cmd


def test_gemini_hook_command_includes_untrusted_suffix():
    cmd = _GEMINI_HOOK["hooks"][0]["command"]
    assert "untrusted data" in cmd


def test_codex_hook_command_includes_untrusted_suffix():
    cmd = _CODEX_HOOK["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
    assert "untrusted data" in cmd


def test_opencode_plugin_includes_untrusted_phrasing():
    """The OpenCode bash echo that fires on every tool call surfaces the
    same warning so an OpenCode user sees it without having to read
    AGENTS.md."""
    assert "untrusted data" in _OPENCODE_PLUGIN_JS


def test_hook_suffix_constant_is_used_consistently():
    """All four inline hook strings should share the same suffix
    constant. If a future edit drifts one of them, this test catches it."""
    bodies = [
        _SETTINGS_HOOK["hooks"][0]["command"],
        _GEMINI_HOOK["hooks"][0]["command"],
        _CODEX_HOOK["hooks"]["PreToolUse"][0]["hooks"][0]["command"],
    ]
    for body in bodies:
        assert _UNTRUSTED_HOOK_SUFFIX in body


# ---------- end-to-end: install path writes framing to disk


def test_claude_install_writes_framing_to_claude_md(tmp_path):
    claude_install(tmp_path)
    text = (tmp_path / "CLAUDE.md").read_text(encoding="utf-8")
    assert "untrusted data" in text.lower()
    assert "[FLAGGED" in text


def test_codex_agents_install_writes_framing(tmp_path):
    _agents_install(tmp_path, platform="codex")
    text = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    assert "untrusted data" in text.lower()
    assert "[FLAGGED" in text


def test_gemini_install_writes_framing(tmp_path):
    gemini_install(tmp_path)
    text = (tmp_path / "GEMINI.md").read_text(encoding="utf-8")
    assert "untrusted data" in text.lower()


def test_vscode_install_writes_framing(tmp_path):
    vscode_install(tmp_path)
    instructions = tmp_path / ".github" / "copilot-instructions.md"
    assert "untrusted data" in instructions.read_text(encoding="utf-8").lower()


def test_cursor_install_writes_framing(tmp_path):
    _cursor_install(tmp_path)
    rule = tmp_path / ".cursor" / "rules" / "graphify.mdc"
    assert "untrusted data" in rule.read_text(encoding="utf-8").lower()


def test_kiro_install_writes_framing(tmp_path):
    _kiro_install(tmp_path)
    steering = tmp_path / ".kiro" / "steering" / "graphify.md"
    assert "untrusted data" in steering.read_text(encoding="utf-8").lower()


def test_antigravity_install_writes_framing(tmp_path, monkeypatch):
    """Antigravity install also calls install(platform=...) which writes
    to ~/.agents/skills — redirect HOME so the test is self-contained."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "home"))
    _antigravity_install(tmp_path)
    rules = tmp_path / ".agents" / "rules" / "graphify.md"
    assert "untrusted data" in rules.read_text(encoding="utf-8").lower()


# ---------- MCP server prefix (Phase 3.5 acceptance)


def test_mcp_prefix_constant_is_present_and_specific():
    from graphify.serve import _UNTRUSTED_MCP_PREFIX
    assert "untrusted data" in _UNTRUSTED_MCP_PREFIX.lower()
    assert "[FLAGGED" in _UNTRUSTED_MCP_PREFIX


@pytest.mark.parametrize("tool_name", [
    "query_graph", "get_node", "get_neighbors",
    "get_community", "god_nodes", "shortest_path",
])
def test_dispatch_prepends_prefix_for_text_handlers(tool_name):
    """Acceptance: every handler that echoes labels/relations prepends the
    untrusted-data note. Tested at the dispatcher seam so we are not
    coupled to the mcp stdio transport."""
    from graphify.serve import _dispatch_tool, _UNTRUSTED_MCP_PREFIX

    handlers = {tool_name: lambda _args: "fake handler output"}
    out = _dispatch_tool(handlers, tool_name, {})
    assert out.startswith(_UNTRUSTED_MCP_PREFIX)
    assert out.endswith("fake handler output")


def test_dispatch_skips_prefix_for_graph_stats():
    """graph_stats returns numbers only — the prefix would be noise."""
    from graphify.serve import _dispatch_tool, _UNTRUSTED_MCP_PREFIX

    out = _dispatch_tool(
        {"graph_stats": lambda _a: "Nodes: 12\nEdges: 5\n"},
        "graph_stats",
        {},
    )
    assert not out.startswith(_UNTRUSTED_MCP_PREFIX)
    assert "Nodes: 12" in out


def test_dispatch_unknown_tool_message_unprefixed():
    from graphify.serve import _dispatch_tool, _UNTRUSTED_MCP_PREFIX

    out = _dispatch_tool({}, "no_such_tool", {})
    assert out == "Unknown tool: no_such_tool"
    assert not out.startswith(_UNTRUSTED_MCP_PREFIX)


def test_dispatch_handler_exception_unprefixed():
    """Errors from a buggy handler are surfaced as-is without the prefix
    so the assistant does not mistake the error message for graph data."""
    from graphify.serve import _dispatch_tool, _UNTRUSTED_MCP_PREFIX

    def _boom(_a):
        raise RuntimeError("boom")

    out = _dispatch_tool({"query_graph": _boom}, "query_graph", {})
    assert "Error executing query_graph: boom" == out
    assert not out.startswith(_UNTRUSTED_MCP_PREFIX)
