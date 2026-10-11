"""THE HOOKS A REPO DECLARES ARE THE HOOKS GIT HAS -- the assertion half, shared.

A hook table is a DECLARATION; installing its shims is a separate act on a separate machine; nothing
links the two. MEASURED 2026-09-16 in three repos at once: each declared a full set of hooks and each
had ZERO in the directory git actually consults, so every commit through every one of them had run
none of them while the tree read as guarded.

Every function below is an assertion over :func:`lab_commons.dev.hook_install.hook_installation` and
its siblings; nothing here re-implements the mechanism.

THE EXACT-SET PIN IS THE PROPERTY. *declared_stages* is compared for EQUALITY, both directions red,
and it is a NAMED SET rather than a count: a stage added to the table and never installed, or deleted
and still pinned, must name itself.

WHAT THIS PROVES, EXACTLY: the current lab_commons shim in every declared slot of the directory git
consults. It is strictly weaker than "these hooks pass".

IT NEVER REPAIRS. A hooks directory is shared by every worktree of a checkout, so an install is a
mutation another party learns about by accident; the remedy is reported
(:data:`lab_commons.dev.hook_install.INSTALL_COMMAND`).
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from lab_commons.dev.hook_install import (
    FOREIGN,
    INSTALL_COMMAND,
    PROTECTED,
    hook_installation,
    hooks_dir,
    install,
)

__all__ = [
    'assert_a_foreign_hook_is_not_installed',
    'assert_declared_hooks_are_installed',
    'assert_hooks_dir_is_the_one_git_consults',
    'assert_stages_are_declared',
    'assert_the_guard_can_go_both_ways',
]

_GIT = shutil.which('git') or 'git'
_GIT_TIMEOUT_S = 60


def assert_stages_are_declared(*, root: Path, declared_stages: frozenset[str]) -> None:
    """The instrument's floor and the two-sided pin: the merged table's stages ARE *declared_stages*."""
    live = {stage.stage for stage in hook_installation(root).stages}
    if not live:
        msg = f'{root} declares no hook stage; this guard is watching nothing, so its silence is not a pass'
        raise AssertionError(msg)
    if live != set(declared_stages):
        msg = (
            f'the declared stages of {root} are {sorted(live)}, not {sorted(declared_stages)}. Added and not '
            f'pinned: {sorted(live - set(declared_stages))}; pinned and no longer declared: '
            f'{sorted(set(declared_stages) - live)}.'
        )
        raise AssertionError(msg)


def assert_declared_hooks_are_installed(*, root: Path) -> None:
    """THE PROPERTY. Green means the commits and pushes through this checkout run the declared hooks."""
    report = hook_installation(root)
    if report.verdict == PROTECTED:
        return
    listing = '\n  '.join(f'{stage.stage:<12} {stage.status:<22} {stage.detail}' for stage in report.failing)
    msg = (
        f'{len(report.failing)} of {len(report.stages)} declared stage(s) are not live in '
        f'{report.hooks_dir}:\n  {listing}\n\n'
        f'Every commit through this checkout ran none of them. The hooks directory is shared by every '
        f'worktree on this box, so installing is a deliberate act:\n  {INSTALL_COMMAND}\n'
    )
    raise AssertionError(msg)


def assert_hooks_dir_is_the_one_git_consults(*, root: Path) -> None:
    """Cross-check the resolved directory against GIT'S OWN answer, never against a rebuilt path."""
    resolved = hooks_dir(root)
    if not resolved.is_dir():
        msg = f'{resolved} is not a directory, so nothing git consults for hooks exists in {root}'
        raise AssertionError(msg)
    named = subprocess.run(
        [_GIT, '-C', str(root), 'rev-parse', '--git-path', 'hooks'],
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
        check=True,
        timeout=_GIT_TIMEOUT_S,
    ).stdout.strip()
    if resolved.resolve() not in {Path(named).resolve(), (root / named).resolve()}:
        msg = f'{resolved} is not the directory git names ({named}); this guard is inspecting the wrong place'
        raise AssertionError(msg)


def _fixture_checkout(*, root: Path, scratch: Path) -> Path:
    """A REAL repository carrying THIS repository's own ``pyproject.toml``, with nothing installed."""
    checkout = scratch / 'checkout'
    checkout.mkdir(parents=True, exist_ok=True)
    subprocess.run([_GIT, 'init', '-q', str(checkout)], check=True, capture_output=True, timeout=_GIT_TIMEOUT_S)
    pyproject = root / 'pyproject.toml'
    if pyproject.is_file():
        (checkout / 'pyproject.toml').write_text(pyproject.read_text(encoding='utf-8'), encoding='utf-8')
    return checkout


def assert_the_guard_can_go_both_ways(*, root: Path, scratch: Path) -> None:
    """THE PLANTED CONTROL: absent, then installed, in a real repository, through the real functions."""
    checkout = _fixture_checkout(root=root, scratch=scratch)
    absent = hook_installation(checkout)
    if not absent.stages or absent.verdict == PROTECTED:
        msg = f'a fresh repository with the table of {root} reported {absent.verdict}; this control cannot fail'
        raise AssertionError(msg)
    installed = install(checkout)
    if installed.verdict != PROTECTED:
        msg = f'installing the shims left {installed.verdict}; the guard cannot reach its own green'
        raise AssertionError(msg)


def assert_a_foreign_hook_is_not_installed(*, root: Path, scratch: Path) -> None:
    """Somebody else's hook in EVERY declared slot is its own finding, never a stale shim of ours."""
    checkout = _fixture_checkout(root=root, scratch=scratch)
    directory = hooks_dir(checkout)
    directory.mkdir(parents=True, exist_ok=True)
    planted = [stage.stage for stage in hook_installation(checkout).stages]
    if not planted:
        msg = 'the fixture declares no stage, so this plants nothing'
        raise AssertionError(msg)
    for stage in planted:
        (directory / stage).write_text('#!/bin/sh\necho mine\n', encoding='utf-8')
    statuses = {stage.status for stage in hook_installation(checkout).stages}
    if statuses != {FOREIGN}:
        msg = f'a hand-written hook in every declared slot reported {sorted(statuses)}, not {{{FOREIGN!r}}}'
        raise AssertionError(msg)
