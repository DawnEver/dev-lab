"""A member's CONTENT is what ``origin/<integration>`` holds after a fetch -- never its checkout's working tree.

MEASURED 2026-11-10: the dev-lab primary checkout stood 723 commits behind its origin, and ``family check`` named
it as lacking ``AGENTS.md`` and a rendered workflow both long landed. A working tree is whatever a session last left
there (some hold another session's staged work, so nothing here touches one); the member's fact is its integration
branch. :func:`snapshot` fetches through the retried network door (:func:`dev_lab.dev.forge.fetch_origin`), learns
the integration branch from the manifest the forge's default branch (``origin/HEAD``) carries, and reads the paths
and manifest of ``origin/<integration>``. Any step that cannot answer RAISES :class:`OSError`, which the caller
reports as unread -- a member never fetched is never reported as lacking.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePath, PurePosixPath

from dev_lab.dev.checkout import git_out
from dev_lab.dev.forge import fetch_origin
from dev_lab.dev.lanepolicy import policy_from

__all__ = ['Snapshot', 'snapshot']


@dataclass(frozen=True)
class Snapshot:
    """One member's tree at *rev*: every tracked path and the manifest text."""

    rev: str
    paths: frozenset[str]
    manifest: str

    def has(self, path: str) -> bool:
        """Whether *path* (posix, from the root) is a tracked file."""
        return path in self.paths

    def names(self, directory: PurePath | str) -> set[str]:
        """The file names directly inside *directory* (a relative path of either flavour)."""
        wanted = PurePosixPath(*PurePath(directory).parts)
        return {PurePosixPath(p).name for p in self.paths if PurePosixPath(p).parent == wanted}


def _read(root: Path, *args: str) -> str:
    said = git_out(root, *args)
    if said is None:
        msg = f'git {" ".join(args)} could not answer in {root}'
        raise OSError(msg)
    return said


def snapshot(root: Path, *, fetch: Callable[[Path], None] = fetch_origin) -> Snapshot:
    """The member at *root* as ``origin/<integration>`` holds it, after *fetch*.

    Raises:
        OSError: the fetch failed, ``origin/HEAD`` is unset (``git remote set-head origin --auto``), or a read failed.
        ValueError: the default branch's manifest declares no integration branch.

    """
    fetch(root)
    head = _read(root, 'show', 'origin/HEAD:pyproject.toml')
    rev = f'origin/{policy_from(head, f"{root} origin/HEAD:pyproject.toml").integration}'
    listed = _read(root, 'ls-tree', '-r', '-z', '--name-only', rev)
    return Snapshot(rev, frozenset(p for p in listed.split('\0') if p), _read(root, 'show', f'{rev}:pyproject.toml'))
