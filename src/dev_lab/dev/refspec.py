"""Git's pre-push refspec lines, parsed once for every pre-push row that reads them.

Git writes ``<local ref> <local sha> <remote ref> <remote sha>`` per ref on the hook's stdin; the family runner
(:mod:`dev_lab.dev.githooks.runner`) pipes it to every pre-push row. A deletion carries the all-zero object name as
its local sha, a creation as its remote sha.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Iterable

__all__ = ['PushedRef', 'pushed_refs']

_ZERO: Final = '0' * 40
_FIELDS: Final = 4
_BRANCHES: Final = 'refs/heads/'


@dataclass(frozen=True)
class PushedRef:
    """One ref a push would update, as the hook was told about it."""

    remote_ref: str
    deleted: bool = False
    #: The commit the push would put on *remote_ref* (the all-zero name for a deletion).
    local_sha: str = ''
    #: Whether the push CREATES *remote_ref* (the remote holds no commit for it yet).
    created: bool = False

    @property
    def branch(self) -> str | None:
        """The branch name when this ref is a branch, else ``None``."""
        return self.remote_ref[len(_BRANCHES) :] if self.remote_ref.startswith(_BRANCHES) else None


def pushed_refs(lines: Iterable[str] = ()) -> tuple[PushedRef, ...]:
    """What this push would move: one entry per well-formed refspec line; a malformed line is skipped."""
    return tuple(
        PushedRef(remote, deleted=local == _ZERO, local_sha=local, created=remote_sha == _ZERO)
        for _local_ref, local, remote, remote_sha in (line.split() for line in lines if len(line.split()) == _FIELDS)
    )
