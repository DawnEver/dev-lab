"""MEASURE-BEFORE-PORTING: a head that adds a native crate carries its MEASURED reason, or it does not merge.

WHY. "Rewrite it in Rust" implies an order of magnitude; where the Python hot path is already compiled code
(numpy, scipy, matplotlib) a port is a codegen change and measures about 2x -- one family repo priced a port at
10x and measured 2x. Interpreted per-element dispatch is the opposite case. Which one a path is must be MEASURED,
never assumed, and a port worth doing on other grounds (FFI marshaling that disappears, ``rayon`` over an
embarrassingly parallel loop, owning the memory) states those grounds, still with the numbers measured.

THE MECHANISM. A port arrives as a crate: a head that ADDS a ``Cargo.toml`` over its base must carry, in at least
one of its own commits, a :data:`TRAILER` line whose value holds a measured number (``Port-Measured: python
18.7 us/point -> rust 9.08 us/point, 2.1x``). :func:`unmeasured` is asked by the merge decision
(:func:`dev_lab.dev.forgemerge.decide`), so no client can skip it. What it cannot see, stated rather than
implied: a port that adds no crate (a function moved into an existing one) is not detected.

SCOPE (user ruling D151, 2026-11-26). The rule guards a Python-first repo against porting a measured-fast path on
an assumed speedup. A repo whose head declares ``[tool.dev_lab.native]`` (NATIVE-FIRST, :mod:`dev_lab.dev.nativefirst`)
writes a native-owned stage in Rust from its first line: there is no Python twin to measure against, so its heads
are out of scope. The declaration is read at the HEAD, so the commit that adopts it is the one a reviewer sees.
"""

from __future__ import annotations

import re
import shutil
import tomllib
from pathlib import Path, PurePosixPath
from typing import Final

import lab_commons.launch as _door

from dev_lab.dev.family import declared_table

__all__ = ['RULE', 'TRAILER', 'added_crates', 'measured', 'native_first', 'unmeasured']

#: The rule this refuses for.
RULE: Final = 'MEASURE-BEFORE-PORTING'
#: The commit trailer carrying the measured reason.
TRAILER: Final = 'Port-Measured'
#: The manifest whose addition marks a new crate.
_MANIFEST: Final = 'Cargo.toml'
#: A measurement names a number.
_NUMBER: Final = re.compile(r'\d')
_GIT_TIMEOUT_S: Final = 60
#: The manifest whose ``[tool.dev_lab.native]`` table scopes a repo out (D151).
_PYPROJECT: Final = 'pyproject.toml'
_NATIVE_TABLE: Final = 'native'


def _git(root: Path, *args: str) -> str:
    git = shutil.which('git')
    if git is None:
        msg = 'git is not on PATH, so whether the head adds a crate cannot be answered'
        raise ValueError(msg)
    done = _door.run([git, '-C', str(root), *args], capture_output=True, check=False, timeout=_GIT_TIMEOUT_S)
    if done.returncode:
        msg = f'git {args[0]} failed: {done.stderr.decode("utf-8", "replace").strip()}'
        raise ValueError(msg)
    return done.stdout.decode('utf-8', 'surrogateescape')


def added_crates(root: Path, base: str, head: str) -> tuple[str, ...]:
    """The ``Cargo.toml`` files *head* adds over its merge base with *base*, repo-relative POSIX, sorted."""
    names = _git(root, 'diff', '--name-only', '--diff-filter=A', '-z', f'{base}...{head}')
    return tuple(sorted(one for one in names.split('\0') if one and PurePosixPath(one).name == _MANIFEST))


def measured(values: list[str]) -> bool:
    """Whether any :data:`TRAILER` value names a measured number."""
    return any(_NUMBER.search(value) for value in values)


def native_first(root: Path, head: str) -> bool:
    """Whether *head*'s ``pyproject.toml`` declares ``[tool.dev_lab.native]``; a missing manifest declares nothing."""
    listed = _git(root, 'ls-tree', '--name-only', head, '--', _PYPROJECT)
    if not listed.strip():
        return False
    try:
        data = tomllib.loads(_git(root, 'show', f'{head}:{_PYPROJECT}'))
    except tomllib.TOMLDecodeError as broken:
        msg = f'{_PYPROJECT} at {head[:12]} is not TOML ({broken}), so whether it declares native-first is unknown'
        raise ValueError(msg) from broken
    return declared_table(data, _NATIVE_TABLE) is not None


def unmeasured(root: Path, base: str, head: str) -> str | None:
    """Why *head* may not merge for want of a measured port record, or ``None`` (also for a native-first head)."""
    crates = added_crates(root, base, head)
    if not crates or native_first(root, head):
        return None
    log = _git(root, 'log', f'--format=%(trailers:key={TRAILER},valueonly)', f'{base}..{head}')
    if measured([line.strip() for line in log.splitlines() if line.strip()]):
        return None
    return (
        f'{RULE}: it adds the crate(s) {list(crates)} and none of its commits carries a `{TRAILER}:` trailer with '
        f'a measured number. Measure the Python path and the native one on the same input (numpy/scipy hot paths '
        f'are already compiled: expect ~2x, not 10x) and add a commit whose message ends with '
        f'`{TRAILER}: python <t> -> native <t>, <ratio>x` -- or the other measured grounds the port stands on.'
    )
