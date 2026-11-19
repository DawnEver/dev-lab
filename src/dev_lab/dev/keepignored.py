"""KEEP WHAT GIT STOPPED TRACKING BUT THE REPO NOW IGNORES -- a tree move never deletes local state.

When a commit stops tracking a path AND the repo now ignores it (``git rm --cached`` beside a ``.gitignore`` line --
a task ledger moved out of git, a generated file made local), every checkout that merges or checks out that commit
has the file DELETED from its working tree by git: the old head tracked it, the new one does not. The file was
declared local state, so losing it is never the intent.

:func:`restore` runs after the move (rows ``keep-ignored`` at ``post-merge`` and ``post-checkout`` of the family
base; a rebase checks out through ``post-checkout`` too). For every path the PREVIOUS head tracked that the NEW
head does not, that ``git check-ignore`` now matches, and that is absent from the working tree, it writes the
previous head's bytes back (binary-safe, atomically). It never overwrites a file, never restores a path the new
head still tracks, and never restores a path that is not ignored -- that is a real deletion, and stays one.

``python -m dev_lab.dev.keepignored --since <rev>``: ``ORIG_HEAD`` after a merge, ``HEAD@{1}`` after a checkout.
An unresolvable *rev* (a new worktree has no previous head) restores nothing. Exit 0 always: the move is done.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
from pathlib import Path
from subprocess import CompletedProcess
from typing import TYPE_CHECKING, Final

from lab_commons import launch
from lab_commons.log import emit

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = ['main', 'restore']

#: git, resolved once.
_GIT: Final = shutil.which('git') or 'git'


def _git(root: Path, *args: str, stdin: bytes | None = None) -> CompletedProcess[bytes]:
    return launch.run([_GIT, *args], cwd=root, input=stdin, capture_output=True, check=False)


def _tracked(root: Path, rev: str) -> set[str]:
    done = _git(root, 'ls-tree', '-r', '-z', '--name-only', rev)
    return {name for name in done.stdout.decode('utf-8', 'surrogateescape').split('\0') if name}


def _ignored(root: Path, paths: Sequence[str]) -> set[str]:
    if not paths:
        return set()
    done = _git(root, 'check-ignore', '--no-index', '-z', '--stdin', stdin='\0'.join(paths).encode() + b'\0')
    return {name for name in done.stdout.decode('utf-8', 'surrogateescape').split('\0') if name}


def _write_atomically(target: Path, data: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=target.parent, prefix=f'.{target.name}.', suffix='.restore')
    try:
        with os.fdopen(fd, 'wb') as handle:
            handle.write(data)
        Path(temp).replace(target)
    except BaseException:
        Path(temp).unlink(missing_ok=True)
        raise


def restore(root: Path, since: str, *, head: str = 'HEAD') -> list[str]:
    """Write back every path *since* tracked, *head* does not, the repo ignores, and the tree lacks; the paths."""
    if _git(root, 'rev-parse', '--verify', '--quiet', f'{since}^{{commit}}').returncode:
        return []
    dropped = sorted(_tracked(root, since) - _tracked(root, head))
    candidates = [path for path in dropped if not (root / path).exists()]
    restored = []
    for path in sorted(_ignored(root, candidates)):
        blob = _git(root, 'show', f'{since}:{path}')
        if blob.returncode:
            continue
        _write_atomically(root / path, blob.stdout)
        restored.append(path)
    return restored


def main(argv: Sequence[str] | None = None) -> int:
    """Restore after a tree move; exit 0 always (the move is done)."""
    parser = argparse.ArgumentParser(prog='python -m dev_lab.dev.keepignored', description=__doc__)
    parser.add_argument('--since', required=True, help='the head before the move: ORIG_HEAD or HEAD@{1}')
    args = parser.parse_args(argv)
    root = Path(_git(Path.cwd(), 'rev-parse', '--show-toplevel').stdout.decode().strip() or '.')
    for path in restore(root, args.since):
        emit(f'[keep-ignored] kept {path}: no longer tracked, now ignored -- restored from {args.since}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
