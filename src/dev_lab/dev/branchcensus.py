"""``census``: what a checkout carries beyond its declared branch set (:mod:`dev_lab.dev.branchset`).

Which ORIGIN branches are undeclared (debt), which LOCAL ones are undeclared, and which of those hold commits no
origin ref has -- read through local refs only (fetch first; the remote is the authority). The two ref readers
here are the branch set's too.
"""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING

from dev_lab.dev.checkout import git_out, origin_branches

if TYPE_CHECKING:
    from pathlib import Path

    from dev_lab.dev.branchset import BranchSet

__all__ = ['Census', 'census', 'short_refs', 'unpushed_count']


@dataclasses.dataclass(frozen=True)
class Census:
    """What a checkout carries beyond its declared set. Every field is sorted branch names."""

    undeclared_origin: tuple[str, ...]
    local_debt: tuple[str, ...]
    unpushed: tuple[str, ...]


def short_refs(root: Path, prefix: str) -> tuple[str, ...] | None:
    """The sorted short names of the refs under *prefix*, or ``None`` when git could not answer."""
    out = git_out(root, 'for-each-ref', '--format=%(refname:short)', prefix)
    return None if out is None else tuple(sorted(n for n in out.splitlines() if n))


def unpushed_count(root: Path, branch: str) -> int | None:
    """How many commits local *branch* holds that no origin ref has, or ``None`` when git could not answer."""
    out = git_out(root, 'rev-list', '--count', f'refs/heads/{branch}', '--not', '--remotes=origin')
    return None if out is None else int(out.strip())


def census(root: Path, branchset: BranchSet) -> Census | None:
    """The undeclared branches of *root*, or ``None`` when git could not answer -- never a clean read."""
    remote = origin_branches(root, protected=frozenset({'HEAD'}))
    local = short_refs(root, 'refs/heads/')
    if remote is None or local is None:
        return None
    debt: list[str] = []
    unpushed: list[str] = []
    for name in local:
        if branchset.admits(name):
            continue
        ahead = unpushed_count(root, name)
        if ahead is None:
            return None
        (unpushed if ahead else debt).append(name)
    return Census(tuple(n for n in remote if not branchset.admits(n)), tuple(debt), tuple(unpushed))
