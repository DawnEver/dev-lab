"""ONE REVISION BOTH WAYS: a sibling a repo builds as a Python package AND as a Rust crate is one commit in both.

A repo that installs a family lab from ``uv.lock`` and links the same lab's crate from a ``Cargo.toml`` git
dependency carries the commit twice; with ``Cargo.lock`` untracked, the manifest's ``rev`` is the one
restatement. A relock that moves ``uv.lock`` and not the ``rev`` builds Python against one engine and Rust
against another, and nothing else notices. Lifted from a consumer's own test of its numerics engine
(2026-11-25); a repo opts in by calling the body from its own suite, every repo fact a keyword::

    from dev_lab.dev.famtests.cratepin import assert_the_crate_builds_the_locked_revision

    def test_rust_builds_the_engine_revision_python_resolves() -> None:
        assert_the_crate_builds_the_locked_revision(
            ROOT, manifest='rust/Cargo.toml', crate='numerics', package='numerics-lab'
        )

The lock is read by :func:`dev_lab.dev.lockpins.pinned_git`, the one reading of a git pin in ``uv.lock``.
"""

from __future__ import annotations

import re
import tomllib
from typing import TYPE_CHECKING, Final

from dev_lab.dev.lockpins import pinned_git

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ['CratePinDrift', 'assert_the_crate_builds_the_locked_revision', 'pin_problems']

#: The Cargo tables a git dependency may be pinned in: the workspace's shared table, or a crate's own.
_TABLES: Final = (('workspace', 'dependencies'), ('dependencies',))
_FULL_SHA: Final = re.compile(r'[0-9a-f]{40}')


class CratePinDrift(AssertionError):
    """The crate's ``rev`` and ``uv.lock`` name different commits of one sibling, or one of them names none."""


def pin_problems(root: Path, *, manifest: str, crate: str, package: str) -> tuple[str, ...]:
    """Every way *root*'s *manifest* dependency *crate* is not the commit ``uv.lock`` pins *package* at."""
    lock, cargo = root / 'uv.lock', root / manifest
    missing = [f'{path.relative_to(root).as_posix()} is absent' for path in (lock, cargo) if not path.is_file()]
    if missing:
        return tuple(f'{line}: the opt-in says this repo builds {package} both ways' for line in missing)
    problems: list[str] = []
    locked = pinned_git(lock.read_text(encoding='utf-8')).get(package.lower().replace('_', '-'))
    if locked is None:
        problems.append(f'uv.lock pins no {package} commit from git: lock it from its git URL')
    entry = _dependency(tomllib.loads(cargo.read_text(encoding='utf-8')), crate)
    if entry is None:
        problems.append(f'{manifest} declares no {crate} dependency in [workspace.dependencies] or [dependencies]')
    elif not isinstance(entry, dict) or 'git' not in entry:
        problems.append(f'{manifest} {crate} = {entry!r} is not a git dependency: pin it as {{ git, rev }}')
    elif 'rev' not in entry:
        problems.append(f'{manifest} {crate} pins no rev (a branch or tag moves): set rev = "<commit>"')
    elif not _FULL_SHA.fullmatch(str(entry['rev'])):
        problems.append(f'{manifest} {crate} rev {entry["rev"]!r} is not a full 40-hex commit')
    elif locked is not None and entry['rev'] != locked:
        problems.append(
            f'{manifest} builds {crate} at {entry["rev"]} and uv.lock resolves {package} at {locked}: '
            f'set rev = "{locked}" in {manifest}'
        )
    return tuple(problems)


def assert_the_crate_builds_the_locked_revision(root: Path, *, manifest: str, crate: str, package: str) -> None:
    """Raise :class:`CratePinDrift` naming every problem :func:`pin_problems` finds in *root*."""
    problems = pin_problems(root, manifest=manifest, crate=crate, package=package)
    if problems:
        raise CratePinDrift('\n'.join(problems))


def _dependency(document: dict[str, object], crate: str) -> object:
    for path in _TABLES:
        node: object = document
        for step in path:
            node = node.get(step, {}) if isinstance(node, dict) else {}
        if isinstance(node, dict) and crate in node:
            return node[crate]
    return None
