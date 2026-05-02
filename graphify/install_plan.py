"""Install-plan framework — split install logic into a pure planner and an
applier so ``--dry-run`` can render exactly what would happen without
mutating the filesystem.

Each platform's install function returns a list of :class:`Action` objects.
``apply_plan`` executes the list and returns one :class:`ActionResult` per
action so the caller can decide what to print and which audit events to
emit. ``render_plan`` produces a human-readable preview (unified diffs for
files that already exist; byte counts for new files).

This module is intentionally minimal: every install action across every
platform is a UTF-8 file write. There are no chmod, copy, or delete
actions — the git-hook installer (which does need chmod) is reached via
``graphify hook install`` and is out of scope for the install-command
``--dry-run`` flag (Task 6.2).
"""
from __future__ import annotations

import difflib
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


@dataclass(frozen=True)
class Action:
    """Plan-time description of a single file mutation.

    The ``after`` content is fully computed by the planner; the ``before``
    content is read from disk at render/apply time so the plan reflects
    the current state of the filesystem at the moment the user inspects
    or executes it.
    """

    path: Path
    after: str


ActionStatus = Literal["created", "modified", "no_op"]


@dataclass(frozen=True)
class ActionResult:
    action: Action
    status: ActionStatus


def _read_before(path: Path) -> str | None:
    """Return the existing file content as text, or None if the file does
    not exist or cannot be decoded as UTF-8 (binary / unreadable)."""
    if not path.exists():
        return None
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def status_for(action: Action) -> ActionStatus:
    """Classify what executing ``action`` against the current filesystem
    would do: create a new file, modify an existing file, or leave it
    unchanged."""
    if not action.path.exists():
        return "created"
    before = _read_before(action.path)
    if before is None:
        return "modified"  # binary / unreadable — we'd overwrite
    return "no_op" if before == action.after else "modified"


def render_action(action: Action) -> str:
    """Return a human-readable preview of a single action: header line +
    optional unified diff."""
    st = status_for(action)
    if st == "no_op":
        return f"  NO-OP   {action.path}"
    if st == "created":
        nbytes = len(action.after.encode("utf-8"))
        return f"  CREATE  {action.path}\n          new file ({nbytes} bytes)"
    before = _read_before(action.path) or ""
    diff = "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            action.after.splitlines(keepends=True),
            fromfile=f"a/{action.path}",
            tofile=f"b/{action.path}",
            n=2,
        )
    )
    if not diff:
        # Reachable when before is the empty string but after is also empty
        # (no-op caught above) or when the file is undecodable — in the
        # latter case _read_before returned None and we fell through to "".
        diff = "  (binary or undecodable file — would be overwritten)\n"
    return f"  MODIFY  {action.path}\n{diff}"


def render_plan(actions: list[Action], *, header: str = "") -> str:
    """Render an entire plan. Empty plans produce a `(nothing to do)`
    placeholder so the caller does not need to special-case empty output."""
    parts: list[str] = []
    if header:
        parts.append(header)
    if not actions:
        parts.append("  (nothing to do)")
    else:
        for a in actions:
            parts.append(render_action(a))
    return "\n".join(parts)


def apply_plan(actions: list[Action]) -> list[ActionResult]:
    """Execute the plan in order. Returns one :class:`ActionResult` per
    action. Idempotent: an action whose ``after`` already matches the
    on-disk content is reported as ``no_op`` and the file is not touched
    (so mtimes are preserved and audit logs do not grow on re-runs).
    """
    results: list[ActionResult] = []
    for a in actions:
        st = status_for(a)
        if st == "no_op":
            results.append(ActionResult(a, st))
            continue
        a.path.parent.mkdir(parents=True, exist_ok=True)
        a.path.write_text(a.after, encoding="utf-8")
        results.append(ActionResult(a, st))
    return results


def modified_paths(results: list[ActionResult]) -> list[Path]:
    """Convenience: the subset of action paths that were actually written
    (created or modified). No-ops are excluded.

    Use this list as input to ``_audit_install`` / ``_audit_hook_install``
    so audit events do not grow on idempotent re-runs.
    """
    return [r.action.path for r in results if r.status != "no_op"]
