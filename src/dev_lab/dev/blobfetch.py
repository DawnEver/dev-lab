"""Fetch the blobs a partial clone is missing in one request per chunk, before git reads them.

A blobless clone (every Gitea job's checkout, ``ci_base.toml`` ``lean``) fetches a missing blob lazily on first
read, ONE round trip per object: a consumer repo's merge.yml audit (``cat-file --batch`` over thousands of test
files) ran past its 120 s timeout on 2026-11-03, and an unauthenticated reader failed outright (2026-11-01).
Asking for them first makes the read local. A clone that is not partial asks for nothing.
"""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING, Final

import lab_commons.launch as _door

from dev_lab.dev.reviewgitauth import git_env

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

__all__ = ['fetch_blobs', 'git', 'is_partial', 'missing']

_GIT_TIMEOUT_S: Final = 120
_FETCH_CHUNK: Final = 500  # object ids per fetch argv, under every platform's command-line limit


def git(root: Path, *args: str, ok: Iterable[int] = (0,)) -> tuple[int, str]:
    """``git *args`` in *root*: its exit code (one of *ok*) and stdout; :class:`OSError` on any other or a timeout."""
    try:
        done = _door.run(
            ['git', *args], cwd=root, capture_output=True, text=True, encoding='utf-8', errors='replace',
            timeout=_GIT_TIMEOUT_S, check=False, env=git_env(),
        )  # fmt: skip
    except subprocess.TimeoutExpired as error:
        msg = f'git {" ".join(args[:6])} timed out after {_GIT_TIMEOUT_S} s'
        raise OSError(msg) from error
    if done.returncode not in tuple(ok):
        msg = f'git {" ".join(args)} failed: {done.stderr.strip()[:300]}'
        raise OSError(msg)
    return done.returncode, done.stdout


def is_partial(root: Path) -> bool:
    """Whether *root* is a partial clone: its ``origin`` is a promisor that lazily serves missing objects."""
    return git(root, 'config', '--get', 'remote.origin.promisor', ok=(0, 1))[1].strip() == 'true'


def missing(root: Path, revs: Iterable[str]) -> set[str]:
    """The objects reachable from *revs* (commits or trees, no history walked) that *root* does not hold.

    ``rev-list --missing=print`` never fetches lazily and needs only git 2.17 (``GIT_NO_LAZY_FETCH`` needs 2.45, and
    a runner host has 2.43). A blob only *root* holds -- a hand-resolved merge's -- is present, so never asked for.
    """
    out = git(root, 'rev-list', '--objects', '--no-walk', '--missing=print', '--end-of-options', *revs)[1]
    return {line[1:].split()[0] for line in out.splitlines() if line.startswith('?')}


def fetch_blobs(root: Path, oids: Iterable[str]) -> int:
    """Fetch *oids* from ``origin`` into *root*, one request per chunk; how many were asked for.

    The caller checks :func:`is_partial` first: a full clone has no promisor to ask.
    """
    ordered = sorted(set(oids))
    for start in range(0, len(ordered), _FETCH_CHUNK):
        git(root, '-c', 'fetch.negotiationAlgorithm=noop', 'fetch', '-q', '--no-tags', '--no-write-fetch-head',
            '--recurse-submodules=no', 'origin', *ordered[start:start + _FETCH_CHUNK])  # fmt: skip
    return len(ordered)
