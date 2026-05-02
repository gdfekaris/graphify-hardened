"""Phase 7.2: lockfile drift regression.

Catches the case where pyproject.toml and uv.lock have fallen out of
sync — typically because a contributor bumped a version range in
pyproject.toml but did not re-run `uv lock`, or added a new dep without
re-running it.

Two assertions:
1. Every requirement declared in pyproject.toml's [project.dependencies]
   or in any of the kept optional-dependency groups has at least one
   matching entry in uv.lock.
2. *Every* resolved version of a declared package in uv.lock satisfies
   the declared specifier. This is `all`, not `any` — uv resolves
   Python-version-conditional pins as multiple [[package]] entries in
   the lock (e.g. networkx 3.4.2 for Python<3.11 and 3.6.1 for >=3.11),
   and a stale lock can leave one of those versions outside an updated
   pyproject range. Both must satisfy.

A note on extras: only the kept extras (per FORK.md / pyproject.toml)
are walked. The synthetic `all` extra is a union shortcut and would
duplicate the per-extra walk.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:  # pragma: no cover - 3.10 dev environments
    import tomli as tomllib  # type: ignore[no-redef]

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version

REPO_ROOT = Path(__file__).resolve().parent.parent

# Kept extras per FORK.md (Phase 0.4) and pyproject.toml. Update both places
# in lockstep if an extra is added or dropped — the audit doc and this test
# are the two enforcement surfaces for that decision.
_KEPT_EXTRAS = ("mcp", "pdf", "watch", "svg", "leiden", "office")


def _load_pyproject() -> dict:
    return tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())


def _load_lock() -> dict[str, set[str]]:
    """Return {canonical_name: {version, ...}} from uv.lock.

    uv.lock can carry multiple [[package]] blocks for one name when the
    resolution branches by Python-version marker (see the networkx pair
    in this repo). Returning a set lets the drift check assert that
    *every* resolved version satisfies the declared specifier.
    """
    data = tomllib.loads((REPO_ROOT / "uv.lock").read_text())
    versions: dict[str, set[str]] = {}
    for pkg in data.get("package", []):
        name = canonicalize_name(pkg["name"])
        versions.setdefault(name, set()).add(pkg["version"])
    return versions


def _declared_requirements() -> list[Requirement]:
    pyproject = _load_pyproject()
    project = pyproject["project"]
    raw: list[str] = list(project.get("dependencies", []))
    extras = project.get("optional-dependencies", {})
    for extra in _KEPT_EXTRAS:
        if extra not in extras:
            raise AssertionError(
                f"Kept extra {extra!r} declared in test but missing from "
                f"pyproject.toml. Reconcile _KEPT_EXTRAS with pyproject."
            )
        raw.extend(extras[extra])
    return [Requirement(spec) for spec in raw]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_every_declared_dep_is_in_lockfile():
    lock = _load_lock()
    missing: list[str] = []
    for req in _declared_requirements():
        if canonicalize_name(req.name) not in lock:
            missing.append(req.name)
    assert not missing, (
        f"Declared in pyproject.toml but absent from uv.lock: {missing}. "
        f"Run `uv lock` to refresh the lockfile."
    )


def test_resolved_versions_satisfy_declared_specifiers():
    lock = _load_lock()
    failures: list[tuple[str, str, str]] = []
    for req in _declared_requirements():
        resolved = lock.get(canonicalize_name(req.name))
        if resolved is None:
            # Covered by the other test; don't double-report.
            continue
        if not req.specifier:
            # No version pin — any resolved version is fine.
            continue
        for version in resolved:
            if not req.specifier.contains(Version(version), prereleases=True):
                failures.append((req.name, str(req.specifier), version))
    assert not failures, (
        f"uv.lock has resolved versions outside their declared pyproject.toml "
        f"specifier (likely a stale lockfile — run `uv lock`): {failures}"
    )


def test_kept_extras_match_pyproject_optional_dependency_groups():
    """Sanity check: _KEPT_EXTRAS in this test file must match exactly the
    set of optional-dependency groups in pyproject.toml, modulo the
    synthetic `all` aggregator.

    If a future task drops or adds an extra, this asserts the test file
    is updated in lockstep so the drift check actually walks the new
    set. Without this guard a silently-renamed extra would skip the
    drift check for its packages.
    """
    extras = set(_load_pyproject()["project"].get("optional-dependencies", {}))
    extras.discard("all")
    assert extras == set(_KEPT_EXTRAS), (
        f"_KEPT_EXTRAS={sorted(_KEPT_EXTRAS)} does not match pyproject.toml "
        f"optional-dependencies={sorted(extras)}. Update _KEPT_EXTRAS or "
        f"pyproject in lockstep."
    )
