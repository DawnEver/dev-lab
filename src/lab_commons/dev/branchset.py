"""ONE-BRANCH-PER-SESSION: a repo's long-lived branches are a DECLARED set, and anything else is debt.

User directive 2026-10-04: each working session keeps exactly ONE long-lived branch, work is merged
into it, and every other branch is merged and deleted rather than left behind. The set a repo may
carry is therefore DATA, declared once in ``[tool.lab_commons.branchset]`` of its ``pyproject.toml``
and read by :func:`declared_branchset`::

    [tool.lab_commons.branchset]
    trunk = 'main'                 # no default: a guessed trunk finds nothing and reads clean
    sessions = ['integrate/main']  # one branch per declared session or lane owner; [] when none

Three questions are asked of it, all through local refs (fetch first; the remote is the authority):

* :func:`census` -- which ORIGIN branches are undeclared (debt), which LOCAL branches are undeclared
  and hold nothing origin lacks (debt), and which local ones hold UNPUSHED work (reported, never
  deleted: unpushed work exists nowhere else).
* :func:`merge_candidates` -- every undeclared branch, local and on origin, and whether it may be
  DELETED now: its tip is an ancestor of the trunk or of a session branch. Anything else is merged
  first. ``python -m lab_commons.dev.branchset [--root R]`` prints this list; it deletes nothing.

The assertions consumers run are :mod:`lab_commons.dev.famtests.branchset`.
"""

from __future__ import annotations

import argparse
import dataclasses
import tomllib
from pathlib import Path

from lab_commons.dev.checkout import authority_for, git_out, origin_branches
from lab_commons.log import emit

__all__ = [
    'BranchSet',
    'BranchSetNotDeclared',
    'Candidate',
    'Census',
    'apply_local',
    'census',
    'declared_branchset',
    'main',
    'merge_candidates',
]

_TABLE = '[tool.lab_commons.branchset]'


class BranchSetNotDeclared(ValueError):
    """The repo declares no branch set, or declares one that is not a trunk plus a list of names."""


@dataclasses.dataclass(frozen=True)
class BranchSet:
    """The trunk plus one long-lived branch per declared session or lane owner."""

    trunk: str
    sessions: frozenset[str]

    @property
    def declared(self) -> frozenset[str]:
        """Every branch name the repo may carry long-term."""
        return self.sessions | {self.trunk}


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


def declared_branchset(root: Path) -> BranchSet:
    """The branch set *root* declares in its ``pyproject.toml``.

    Raises:
        BranchSetNotDeclared: no readable manifest, no table, no trunk, or sessions not a list of names.

    """
    manifest = root / 'pyproject.toml'
    try:
        data = tomllib.loads(manifest.read_text(encoding='utf-8'))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        msg = f'{manifest} is not a readable TOML manifest: {exc}'
        raise BranchSetNotDeclared(msg) from exc
    table = data.get('tool', {}).get('lab_commons', {}).get('branchset')
    trunk = table.get('trunk') if isinstance(table, dict) else None
    sessions = table.get('sessions', []) if isinstance(table, dict) else None
    if not isinstance(trunk, str) or not trunk:
        msg = f'{manifest} declares no {_TABLE} trunk; name it -- a guessed trunk reads every checkout clean'
        raise BranchSetNotDeclared(msg)
    if not isinstance(sessions, list) or not all(isinstance(name, str) and name for name in sessions):
        msg = f'{_TABLE} sessions in {manifest} is {sessions!r}; it must be a list of branch names'
        raise BranchSetNotDeclared(msg)
    return BranchSet(trunk, frozenset(sessions))


def _local_branches(root: Path) -> tuple[str, ...] | None:
    out = git_out(root, 'for-each-ref', '--format=%(refname:short)', 'refs/heads/')
    return None if out is None else tuple(sorted(n for n in out.splitlines() if n))


def _unpushed(root: Path, branch: str) -> int | None:
    out = git_out(root, 'rev-list', '--count', f'refs/heads/{branch}', '--not', '--remotes=origin')
    return None if out is None else int(out.strip())


def census(root: Path, branchset: BranchSet) -> Census | None:
    """The undeclared branches of *root*, or ``None`` when git could not answer -- never a clean read."""
    remote = origin_branches(root, protected=frozenset({'HEAD'}))
    local = _local_branches(root)
    if remote is None or local is None:
        return None
    debt: list[str] = []
    unpushed: list[str] = []
    for name in local:
        if name in branchset.declared:
            continue
        ahead = _unpushed(root, name)
        if ahead is None:
            return None
        (unpushed if ahead else debt).append(name)
    return Census(tuple(n for n in remote if n not in branchset.declared), tuple(debt), tuple(unpushed))


def _holders(root: Path, branchset: BranchSet) -> tuple[str, ...]:
    """The refs whose history makes a tip safe to delete: the trunk's authority and every session."""
    refs = [authority_for(root, branchset.trunk)]
    for session in sorted(branchset.sessions):
        refs += [
            r
            for r in (f'refs/remotes/origin/{session}', f'refs/heads/{session}')
            if git_out(root, 'rev-parse', '--verify', '--quiet', r)
        ]
    return tuple(refs)


def merge_candidates(root: Path, branchset: BranchSet) -> tuple[Candidate, ...] | None:
    """Every undeclared branch, local then origin, and whether its tip is already held by a declared one."""
    remote = origin_branches(root, protected=frozenset({'HEAD'}))
    local = _local_branches(root)
    if remote is None or local is None:
        return None
    holders = _holders(root, branchset)
    rows: list[Candidate] = []
    for where, names, prefix in (('local', local, 'refs/heads/'), ('origin', remote, 'refs/remotes/origin/')):
        for name in names:
            if name in branchset.declared:
                continue
            held = any(git_out(root, 'merge-base', '--is-ancestor', f'{prefix}{name}', h) is not None for h in holders)
            rows.append(Candidate(name, where, held))
    return tuple(rows)


def _checked_out(root: Path) -> frozenset[str]:
    out = git_out(root, 'for-each-ref', '--format=%(refname:short)|%(worktreepath)', 'refs/heads/')
    rows = (line.partition('|') for line in (out or '').splitlines())
    return frozenset(name for name, _, tree in rows if tree.strip())


def apply_local(root: Path, branchset: BranchSet) -> tuple[str, ...] | None:
    """THE LOCAL CLEANUP DOOR: delete every deletable LOCAL candidate; one line per branch. ``None``: unread.

    User ruling 2026-10-04: local cleanup is a door, but a push or a REMOTE deletion is never automatic.
    So an origin candidate is only LISTED, with the command a human runs. Each local delete follows a
    FRESH ``merge-base --is-ancestor`` and is pinned to the sha that check saw (``update-ref -d <ref>
    <sha>``), so a branch that moved in between is kept, never lost. A declared branch, a branch with
    commits origin lacks, and a branch checked out in ANY worktree (clean or not -- ruling 2026-10-04:
    a tree is committed or cleared first) are never touched.
    """
    rows = merge_candidates(root, branchset)
    if rows is None:
        return None
    holders = _holders(root, branchset)
    busy = _checked_out(root)
    out: list[str] = []
    for row in rows:
        if row.where == 'origin':
            hint = f'(human: git push origin --delete {row.name})' if row.deletable else '(merge first)'
            out.append(f'listed   origin  {row.name}  {hint}')
            continue
        ref = f'refs/heads/{row.name}'
        sha = (git_out(root, 'rev-parse', '--verify', '--quiet', ref) or '').strip()
        if not row.deletable or row.name in branchset.declared or not sha:
            out.append(f'kept     local   {row.name}  (not held by a declared branch)')
        elif row.name in busy or _unpushed(root, row.name) != 0:
            out.append(
                f'kept     local   {row.name}  (checked out in a worktree, or holds commits origin lacks)'
            )
        elif not any(git_out(root, 'merge-base', '--is-ancestor', sha, h) is not None for h in holders):
            out.append(f'kept     local   {row.name}  (ancestry re-check failed)')
        else:
            done = git_out(root, 'update-ref', '-d', ref, sha) is not None
            out.append(f'{"deleted " if done else "FAILED  "} local   {row.name}  ({sha[:10]})')
    return tuple(out)


def main(argv: list[str] | None = None) -> int:
    """List the merge-and-delete candidates; ``--apply`` deletes the deletable LOCAL ones. Exit 2: unread."""
    parser = argparse.ArgumentParser(prog='python -m lab_commons.dev.branchset', description=main.__doc__)
    parser.add_argument('--root', type=Path, default=Path.cwd(), help='the checkout to read (default: cwd)')
    parser.add_argument('--apply', action='store_true', help='delete deletable LOCAL branches; origin is listed only')
    args = parser.parse_args(argv)
    root = args.root
    if args.apply:
        lines = apply_local(root, declared_branchset(root))
        if lines is None:
            emit(f'git could not read the branches of {root}; nothing was deleted')
            return 2
        for line in lines:
            emit(line)
        return 1 if any(line.startswith('FAILED') for line in lines) else 0
    rows = merge_candidates(root, declared_branchset(root))
    if rows is None:
        emit(f'git could not read the branches of {root}; an unread repo is not a clean one')
        return 2
    for row in rows:
        emit(f'{"delete" if row.deletable else "merge "}  {row.where:<7} {row.name}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
