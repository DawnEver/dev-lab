"""The CENSUS of a checkout's branches against its declared set: what is undeclared, what is held, what is checked out.

Read through local refs only (fetch first; the remote is the authority). :mod:`dev_lab.dev.branchset` owns the
declaration and the cleanup door that acts on these reads.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import TYPE_CHECKING, Final

from dev_lab.dev.checkout import authority_for, git_out, origin_branches

if TYPE_CHECKING:
    from dev_lab.dev.branchset import BranchSet

#: The ref shape a branch is PARKED under instead of being merged or deleted. MERGE-OR-DELETE (user ruling
#: 2026-10-11): "you drop it into an archive tag and nobody ever looks at it" -- such a tag is debt exactly
#: like an undeclared branch: merged -> deleted, unmerged -> merged. A release tag is never this shape.
ARCHIVE_PREFIX = 'archive/'


@dataclasses.dataclass(frozen=True)
class Census:
    """What a checkout carries beyond its declared set. Every field is sorted branch names."""

    undeclared_origin: tuple[str, ...]
    local_debt: tuple[str, ...]
    unpushed: tuple[str, ...]


@dataclasses.dataclass(frozen=True)
class Candidate:
    """One undeclared branch and whether it may be deleted without losing a commit."""

    name: str
    where: str
    deletable: bool


def _short_refs(root: Path, prefix: str) -> tuple[str, ...] | None:
    """The sorted short names of the refs under *prefix*, or ``None`` when git could not answer."""
    out = git_out(root, 'for-each-ref', '--format=%(refname:short)', prefix)
    return None if out is None else tuple(sorted(n for n in out.splitlines() if n))


def unpushed_count(root: Path, branch: str) -> int | None:
    out = git_out(root, 'rev-list', '--count', f'refs/heads/{branch}', '--not', '--remotes=origin')
    return None if out is None else int(out.strip())


def census(root: Path, branchset: BranchSet) -> Census | None:
    """The undeclared branches of *root*, or ``None`` when git could not answer -- never a clean read."""
    remote = origin_branches(root, protected=frozenset({'HEAD'}))
    local = _short_refs(root, 'refs/heads/')
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


def holders(root: Path, branchset: BranchSet) -> tuple[str, ...]:
    """The refs whose history makes a tip safe to delete: the trunk's authority and every session."""
    refs = [authority_for(root, branchset.trunk)]
    for session in sorted(branchset.sessions):
        refs += [
            r
            for r in (f'refs/remotes/origin/{session}', f'refs/heads/{session}')
            if git_out(root, 'rev-parse', '--verify', '--quiet', r)
        ]
    return tuple(refs)


ORIGIN_DOOR: Final = 'python -m dev_lab.dev.branchprune delete'
"""The agent's exit for a landed origin branch: LOSSLESS-DELETE re-judges it after a fresh fetch, then lease-deletes."""


def merge_candidates(root: Path, branchset: BranchSet) -> tuple[Candidate, ...] | None:
    """Every undeclared branch (local, origin) and parked tag, and whether its tip is held by a declared one."""
    remote = origin_branches(root, protected=frozenset({'HEAD'}))
    local = _short_refs(root, 'refs/heads/')
    parked = _short_refs(root, f'refs/tags/{ARCHIVE_PREFIX}')
    if remote is None or local is None or parked is None:
        return None
    held_by = holders(root, branchset)
    rows: list[Candidate] = []
    for where, names, prefix in (
        ('local', local, 'refs/heads/'),
        ('origin', remote, 'refs/remotes/origin/'),
        ('tag', parked, 'refs/tags/'),
    ):
        for name in names:
            if name in branchset.declared:
                continue
            held = any(git_out(root, 'merge-base', '--is-ancestor', f'{prefix}{name}', h) is not None for h in held_by)
            rows.append(Candidate(name, where, held))
    return tuple(rows)


def checked_out(root: Path) -> frozenset[str]:
    """The local branches checked out in any worktree of *root*."""
    out = git_out(root, 'for-each-ref', '--format=%(refname:short)|%(worktreepath)', 'refs/heads/')
    rows = (line.partition('|') for line in (out or '').splitlines())
    return frozenset(name for name, _, tree in rows if tree.strip())
