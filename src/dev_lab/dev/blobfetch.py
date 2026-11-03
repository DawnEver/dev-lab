"""Fetch named blobs into a partial clone in one request per chunk, before git reads them.

A blobless clone (every Gitea job's checkout, ``ci_base.toml`` ``lean``) fetches a missing blob lazily on first
read, ONE round trip per object: a ``git cat-file --batch`` over thousands of test files ran past its 120 s
timeout (motronics merge.yml tasks 274/276/277, 2026-11-03), and an unauthenticated reader failed outright
(motronics #5397). Asking for them first makes the read local. A clone that is not partial asks for nothing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

import lab_commons.launch as _door

from dev_lab.dev.forge import _GIT
from dev_lab.dev.reviewgitauth import git_env

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

__all__ = ['fetch_blobs']

_FETCH_CHUNK: Final = 500  # object ids per fetch argv, under every platform's command-line limit
_TIMEOUT_S: Final = 600


def _git(root: Path, *args: str, ok: Iterable[int] = (0,)) -> tuple[int, str]:
    done = _door.run([_GIT, '-C', str(root), *args], capture_output=True, text=True, encoding='utf-8',
                     check=False, timeout=_TIMEOUT_S, env=git_env())  # fmt: skip
    if done.returncode not in tuple(ok):
        msg = f'git {" ".join(args[:4])} exited {done.returncode}: {done.stderr.strip()}'
        raise OSError(msg)
    return done.returncode, done.stdout


def fetch_blobs(root: Path, oids: Iterable[str]) -> int:
    """Fetch every blob of *oids* into *root* when it is a partial clone; how many were asked for (0 when not)."""
    if _git(root, 'config', '--get', 'remote.origin.promisor', ok=(0, 1))[1].strip() != 'true':
        return 0
    ordered = sorted(set(oids))
    for start in range(0, len(ordered), _FETCH_CHUNK):
        _git(root, '-c', 'fetch.negotiationAlgorithm=noop', 'fetch', '-q', '--no-tags', '--no-write-fetch-head',
             '--recurse-submodules=no', 'origin', *ordered[start:start + _FETCH_CHUNK])  # fmt: skip
    return len(ordered)
