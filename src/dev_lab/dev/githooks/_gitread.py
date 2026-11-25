"""What a git hook READS from git: the pre-push lines, the staged and pushed paths, the working-tree diff.

Split out of :mod:`dev_lab.dev.githooks.runner` (2026-11-25, MODULE-SIZE-ALARM) along its own seam: that module
selects and runs the hooks of a stage; this one only asks git what the stage is about.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final

import lab_commons.launch as _door

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = ['ZERO_SHA', 'PushLine', 'git', 'parse_push_lines', 'pushed_paths', 'staged_paths', 'worktree_diff']

#: The object name git writes for the absent side of a ref: a deleted ref, or one the remote lacks.
ZERO_SHA: Final = '0' * 40

#: The fields of one pre-push line: local ref, local sha, remote ref, remote sha.
_PUSH_FIELDS: Final = 4

_GIT: Final = shutil.which('git') or 'git'
_GIT_TIMEOUT_S: Final = 120


@dataclass(frozen=True)
class PushLine:
    """One ref a push updates, as git's pre-push protocol states it."""

    local_ref: str
    local_sha: str
    remote_ref: str
    remote_sha: str

    @property
    def deleted(self) -> bool:
        """The push deletes *remote_ref*: git writes the zero sha on the local side."""
        return self.local_sha == ZERO_SHA

    @property
    def line(self) -> str:
        """The line as git wrote it."""
        return f'{self.local_ref} {self.local_sha} {self.remote_ref} {self.remote_sha}'


def parse_push_lines(text: str) -> tuple[PushLine, ...]:
    """Git's pre-push stdin, one :class:`PushLine` per four-field line; anything else is not a ref line."""
    return tuple(
        PushLine(*fields) for fields in (line.split() for line in text.splitlines()) if len(fields) == _PUSH_FIELDS
    )


def git(root: Path, *args: str) -> str:
    return _door.run(
        [_GIT, '-C', str(root), *args],
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
        check=True,
        timeout=_GIT_TIMEOUT_S,
    ).stdout


def staged_paths(root: Path) -> tuple[str, ...]:
    """The paths a commit would add or change -- deletions name no file a hook could read.

    During a merge (``MERGE_HEAD``), a path counts only when it differs from HEAD AND from every merged head: what
    the merge itself writes, never what one side already held.
    """
    found = _diff_names(root, '--cached')
    for parent in _merge_heads(root):
        theirs = set(_diff_names(root, '--cached', parent))
        found = tuple(path for path in found if path in theirs)
    return found


def _diff_names(root: Path, *args: str) -> tuple[str, ...]:
    out = git(root, 'diff', *args, '--name-only', '--diff-filter=ACMR', '-z')
    return tuple(path for path in out.split('\0') if path)


def _merge_heads(root: Path) -> tuple[str, ...]:
    """The heads an in-progress merge brings in (git's ``MERGE_HEAD`` file, one per line); none outside a merge."""
    path = Path(git(root, 'rev-parse', '--git-path', 'MERGE_HEAD').strip())
    path = path if path.is_absolute() else root / path
    return tuple(path.read_text(encoding='utf-8').split()) if path.is_file() else ()


def pushed_paths(root: Path, lines: Sequence[PushLine], remote: str) -> tuple[str, ...]:
    """The paths the pushed commits change: commits the remote lacks, a merge counting only its own content.

    ``--cc`` (dense combined diff) names a merge's path only when it differs from every parent, so a merge of the
    integration branch into a lane carries none of integration's files. The remote's old sha and its
    remote-tracking refs bound the walk: a commit already published is not this push's.
    """
    found: dict[str, None] = {}
    for line in lines:
        if line.deleted:
            continue
        known = [line.remote_sha] if line.remote_sha != ZERO_SHA and _has_commit(root, line.remote_sha) else []
        exclude = [f'--remotes={remote}'] if remote else []
        out = git(
            root, 'log', '--cc', '--name-only', '--diff-filter=ACMR', '-z', '--format=', line.local_sha, '--not',
            *known, *exclude,
        )  # fmt: skip
        found.update(dict.fromkeys(path.strip() for path in out.split('\0') if path.strip()))
    return tuple(found)


def _has_commit(root: Path, sha: str) -> bool:
    done = _door.run(
        [_GIT, '-C', str(root), 'cat-file', '-e', f'{sha}^{{commit}}'],
        capture_output=True,
        check=False,
        timeout=_GIT_TIMEOUT_S,
    )
    return done.returncode == 0


def worktree_diff(root: Path) -> str:
    """The working tree's unstaged diff -- what a hook must not change during a commit."""
    return git(root, 'diff', '--no-color', '--binary')
