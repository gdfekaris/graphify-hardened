"""Unit tests for the install-plan framework."""
from __future__ import annotations

from pathlib import Path

import pytest

from graphify.install_plan import (
    Action,
    ActionResult,
    apply_plan,
    modified_paths,
    render_action,
    render_plan,
    status_for,
)


def test_status_for_create(tmp_path):
    a = Action(tmp_path / "new.txt", "hello")
    assert status_for(a) == "created"


def test_status_for_no_op(tmp_path):
    p = tmp_path / "exists.txt"
    p.write_text("hello", encoding="utf-8")
    a = Action(p, "hello")
    assert status_for(a) == "no_op"


def test_status_for_modify(tmp_path):
    p = tmp_path / "exists.txt"
    p.write_text("hello", encoding="utf-8")
    a = Action(p, "world")
    assert status_for(a) == "modified"


def test_status_for_binary_treated_as_modify(tmp_path):
    p = tmp_path / "binary.bin"
    p.write_bytes(b"\xff\xfe\x00\x01")
    a = Action(p, "text")
    assert status_for(a) == "modified"


def test_render_action_create(tmp_path):
    a = Action(tmp_path / "new.txt", "hello world")
    out = render_action(a)
    assert "CREATE" in out
    assert "11 bytes" in out  # len("hello world")
    assert str(tmp_path / "new.txt") in out


def test_render_action_no_op(tmp_path):
    p = tmp_path / "exists.txt"
    p.write_text("same", encoding="utf-8")
    a = Action(p, "same")
    out = render_action(a)
    assert "NO-OP" in out


def test_render_action_modify_includes_unified_diff(tmp_path):
    p = tmp_path / "exists.txt"
    p.write_text("alpha\nbeta\ngamma\n", encoding="utf-8")
    a = Action(p, "alpha\ndelta\ngamma\n")
    out = render_action(a)
    assert "MODIFY" in out
    assert "-beta" in out
    assert "+delta" in out
    assert "@@ " in out  # unified diff hunk header


def test_render_plan_empty():
    assert "(nothing to do)" in render_plan([])


def test_render_plan_with_header():
    out = render_plan([], header="=== Plan: claude install ===")
    assert "=== Plan: claude install ===" in out
    assert "(nothing to do)" in out


def test_apply_plan_creates_file(tmp_path):
    p = tmp_path / "subdir" / "new.txt"
    actions = [Action(p, "hello")]
    results = apply_plan(actions)
    assert p.read_text(encoding="utf-8") == "hello"
    assert results[0].status == "created"
    # Parent directory was created.
    assert p.parent.is_dir()


def test_apply_plan_modifies_file(tmp_path):
    p = tmp_path / "exists.txt"
    p.write_text("old", encoding="utf-8")
    results = apply_plan([Action(p, "new")])
    assert p.read_text(encoding="utf-8") == "new"
    assert results[0].status == "modified"


def test_apply_plan_no_op_does_not_touch_file(tmp_path):
    p = tmp_path / "exists.txt"
    p.write_text("same", encoding="utf-8")
    mtime_before = p.stat().st_mtime_ns
    results = apply_plan([Action(p, "same")])
    assert results[0].status == "no_op"
    assert p.stat().st_mtime_ns == mtime_before


def test_apply_plan_preserves_action_order(tmp_path):
    a = tmp_path / "a.txt"
    b = tmp_path / "b.txt"
    apply_plan([Action(a, "1"), Action(b, "2")])
    assert a.read_text() == "1"
    assert b.read_text() == "2"


def test_modified_paths_excludes_no_ops(tmp_path):
    existing = tmp_path / "same.txt"
    existing.write_text("same", encoding="utf-8")
    new = tmp_path / "new.txt"
    results = apply_plan([Action(existing, "same"), Action(new, "fresh")])
    paths = modified_paths(results)
    assert paths == [new]


def test_apply_plan_is_idempotent(tmp_path):
    p = tmp_path / "f.txt"
    actions = [Action(p, "content")]
    apply_plan(actions)
    mtime = p.stat().st_mtime_ns
    apply_plan(actions)
    assert p.stat().st_mtime_ns == mtime  # second run was no-op


def test_render_plan_lists_each_action(tmp_path):
    a = Action(tmp_path / "one.txt", "1")
    b = Action(tmp_path / "two.txt", "2")
    out = render_plan([a, b])
    assert "one.txt" in out
    assert "two.txt" in out


def test_action_is_frozen():
    a = Action(Path("/tmp/x"), "y")
    with pytest.raises((AttributeError, Exception)):
        a.path = Path("/tmp/z")  # type: ignore[misc]
