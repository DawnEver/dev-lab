"""ONE-BRANCH-PER-SESSION: a repo's long-lived branches are a DECLARED set, and anything else is debt.

User directive 2026-10-04: each working session keeps exactly ONE long-lived branch, work is merged
into it, and every other branch is merged and deleted rather than left behind. The set a repo may
carry is therefore DATA, declared once in ``[tool.dev_lab.branchset]`` of its ``pyproject.toml``
and read by :func:`declared_branchset`::

    [tool.dev_lab.branchset]
    trunk = 'main'                 # no default: a guessed trunk finds nothing and reads clean
    sessions = ['integrate/main']  # one branch per declared session or lane owner; [] when none
    ephemeral = ['pr/*']           # the DEFAULT, so omit it; PR-head globs, deleted once the PR goes; [] opts out
    task_heads = 'pr/<task>/<feature>'  # the DEFAULT: the head an agent session bound to a task pushes; '' opts out
    prune_merged = true            # the ``prune`` role's executor DELETES merged idle origin branches (idempotent)
    max_idle_hours = 24            # how long a branch's tip sits idle before it is pruned (merged) or STALE (unmerged)
    max_ahead = 10                 # how many unlanded commits a branch may hold before it is OVER_AHEAD

Three questions are asked of it, all through local refs (fetch first; the remote is the authority):

* :func:`census` -- which ORIGIN branches are undeclared (debt), which LOCAL branches are undeclared
  and hold nothing origin lacks (debt), and which local ones hold UNPUSHED work (reported, never
  deleted: unpushed work exists nowhere else).
* :func:`merge_candidates` -- every undeclared branch, local and on origin, and every branch PARKED as an
  ``archive/*`` tag (MERGE-OR-DELETE: a tag nobody reads is not a place to keep work), and whether it may be
  DELETED now: its tip is an ancestor of the trunk or of a session branch. Anything else is merged
  first. ``python -m dev_lab.dev.branchset [--root R]`` prints this list; it deletes nothing.
* :func:`dev_lab.dev.branchfate.discard` -- ``--discard <branch> --approved "<the user's words>"``: the door for
  ONE UNLANDED lane the user approved dropping (user ruling 2026-11-13): its worktree and local branch, pinned to
  the sha it saw. Origin is never touched.

The live set is judged by the forge alone (:mod:`dev_lab.dev.forgeheadgate`), never a test. ``prune_merged`` (default
``false``) lets the forge prune merged origin branches (:mod:`dev_lab.dev.branchprune`); an agent never deletes a remote
ref by hand, only through :data:`ORIGIN_DOOR` (LOSSLESS-DELETE), which ``--apply`` names on every landed origin row.
"""

from __future__ import annotations

import argparse
import dataclasses
import fnmatch
import subprocess
import tomllib
from collections.abc import Callable
from pathlib import Path
from typing import Final

from lab_commons.hpc.declared import pyproject_at
from lab_commons.hpc.retired import RETIRED
from lab_commons.log import emit

from dev_lab.dev.branchfate import discard, settle
from dev_lab.dev.checkout import authority_for, git_out, origin_branches
from dev_lab.dev.family import declared_table
from dev_lab.dev.reclaim import QUIET_S, reclaim
from dev_lab.dev.venvpath import running_interpreter

__all__ = [
    'ARCHIVE_PREFIX',
    'EPHEMERAL_OFF',
    'FAMILY_EPHEMERAL',
    'FAMILY_TASK_HEADS',
    'ORIGIN_DOOR',
    'BranchSet',
    'BranchSetKeyRetired',
    'BranchSetNotDeclared',
    'Candidate',
    'Census',
    'KitOlderThanCheckout',
    'apply_local',
    'branchset_at',
    'branchset_from',
    'census',
    'checked_out',
    'declared_branchset',
    'holders',
    'main',
    'merge_candidates',
]

_TABLE = '[tool.dev_lab.branchset]'
_KEYS = frozenset({'trunk', 'sessions', 'ephemeral', 'prune_merged', 'max_idle_hours', 'max_ahead', 'task_heads'})
#: RETIRED-NAMES-REGISTERED: a key this module renamed, refused by name with its replacement (D46, 2026-11-19).
_RENAMED: Final = {'grace_hours': 'renamed max_idle_hours (one idle bound for prune and STALE, D46)'}

#: The family's PR-head namespace (user ruling 2026-10-19, made the default 2026-10-23): ruled ONCE here, so a
#: manifest that omits ``ephemeral`` carries it and one that means none writes ``ephemeral = []``.
FAMILY_EPHEMERAL: Final[tuple[str, ...]] = ('pr/*',)
#: The shape of a pushed PR head (user ruling D25, 2026-11-17): branch names follow the task, one feature per PR.
#: Only the namespace before ``<task>`` is a choice; ``<task>/<feature>`` is the shape itself.
FAMILY_TASK_HEADS: Final = 'pr/<task>/<feature>'
_TASK_TAIL: Final = '<task>/<feature>'
#: What a manifest that turned the namespace off is told, by every assertion that reads it.
EPHEMERAL_OFF: Final = '[tool.dev_lab.branchset] ephemeral = [] turns off the family pr/* namespace -- delete the line'

#: The ref shape a branch is PARKED under instead of being merged or deleted. MERGE-OR-DELETE (user ruling
#: 2026-10-11): "you drop it into an archive tag and nobody ever looks at it" -- such a tag is debt exactly
#: like an undeclared branch: merged -> deleted, unmerged -> merged. A release tag is never this shape.
ARCHIVE_PREFIX = 'archive/'


class BranchSetNotDeclared(ValueError):
    """The repo declares no branch set, or declares one that is not a trunk plus a list of names."""


class BranchSetKeyRetired(BranchSetNotDeclared):
    """The checkout declares a RETIRED key: named with its replacement (RETIRED-NAMES-REGISTERED), never "unknown"."""


class KitOlderThanCheckout(BranchSetNotDeclared):
    """The checkout declares a key this INSTALLED kit does not know: the kit is older than the checkout.

    Not a malformed declaration -- a newer one. Measured 2026-10-16: a pre-push run by a venv built before
    the pushed sha's schema refused as an unreadable branch set, sending its reader to fix a manifest
    that was right; the remedy is to rebuild the venv.
    """


@dataclasses.dataclass(frozen=True)
class BranchSet:
    """The trunk plus one long-lived branch per declared session or lane owner."""

    trunk: str
    sessions: frozenset[str]
    #: Whether the ``prune`` role's executor deletes merged, idle origin branches; off, it only lists them.
    prune_merged: bool = False
    #: How long a branch tip sits idle before it is pruned (merged) or STALE (unmerged).
    max_idle_hours: float = 24.0
    #: How many commits a branch may hold that integration lacks before it is OVER_AHEAD; ``None``: unjudged.
    max_ahead: int | None = None
    #: Glob namespaces (``pr/*``) of SHORT-LIVED branches: pushable undeclared, each the head of one pull
    #: request, deleted by the forge once no open PR has it as head (:mod:`dev_lab.dev.branchprune`).
    ephemeral: tuple[str, ...] = ()
    #: The head shape an agent session bound to a task pushes (:data:`FAMILY_TASK_HEADS`); ``''``: not judged.
    task_heads: str = FAMILY_TASK_HEADS

    @property
    def task_namespace(self) -> str:
        """The namespace every task's heads live under (``pr/``), or ``''`` when task heads are not judged."""
        return self.task_heads.removesuffix(_TASK_TAIL)

    def task_head(self, slug: str, feature: str) -> str:
        """The head task *slug* publishes *feature* on."""
        return self.task_heads.replace('<task>', slug).replace('<feature>', feature)

    def carries_task(self, name: str, slug: str) -> bool:
        """Whether *name* is one of task *slug*'s heads -- never the bare ``pr/<slug>``."""
        prefix = self.task_head(slug, '')
        return name.startswith(prefix) and len(name) > len(prefix)

    @property
    def declared(self) -> frozenset[str]:
        """Every branch name the repo may carry long-term."""
        return self.sessions | {self.trunk}

    def is_ephemeral(self, name: str) -> bool:
        """Whether *name* lies in a declared ephemeral namespace (and is not a long-lived branch)."""
        return name not in self.declared and any(fnmatch.fnmatchcase(name, glob) for glob in self.ephemeral)

    def admits(self, name: str) -> bool:
        """Whether *name* may sit on origin: a declared long-lived branch or one in an ephemeral namespace."""
        return name in self.declared or self.is_ephemeral(name)


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
        text = manifest.read_text(encoding='utf-8')
    except OSError as exc:
        msg = f'{manifest} is not a readable TOML manifest: {exc}'
        raise BranchSetNotDeclared(msg) from exc
    return branchset_from(text, str(manifest))


def branchset_at(root: Path, rev: str) -> BranchSet:
    """The branch set commit or tree *rev* of *root* declares -- never the working tree's."""
    try:
        text = pyproject_at(root, rev)
    except (OSError, subprocess.CalledProcessError) as exc:
        msg = f'{rev}:pyproject.toml is not readable in {root}: {exc}'
        raise BranchSetNotDeclared(msg) from exc
    return branchset_from(text, f'{rev}:pyproject.toml')


def branchset_from(text: str, manifest: str) -> BranchSet:
    """The branch set *text* declares; *manifest* names where it came from in every refusal."""
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        msg = f'{manifest} is not a readable TOML manifest: {exc}'
        raise BranchSetNotDeclared(msg) from exc
    table = declared_table(data, 'branchset')
    trunk = table.get('trunk') if isinstance(table, dict) else None
    sessions = table.get('sessions', []) if isinstance(table, dict) else None
    if not isinstance(trunk, str) or not trunk:
        msg = f'{manifest} declares no {_TABLE} trunk; name it -- a guessed trunk reads every checkout clean'
        raise BranchSetNotDeclared(msg)
    if not isinstance(sessions, list) or not all(isinstance(name, str) and name for name in sessions):
        msg = f'{_TABLE} sessions in {manifest} is {sessions!r}; it must be a list of branch names'
        raise BranchSetNotDeclared(msg)
    if retired := [
        f'{key} is retired: {RETIRED[f"branchset.{key}"]}' for key in table if f'branchset.{key}' in RETIRED
    ] + [f'{key} is retired: {_RENAMED[key]}' for key in table if key in _RENAMED]:
        msg = f'{_TABLE} in {manifest}: ' + '; '.join(retired)
        raise BranchSetKeyRetired(msg)
    unknown = sorted(set(table) - _KEYS)
    if unknown:
        msg = (
            f'your kit is older than this checkout: {_TABLE} in {manifest} has key(s) {unknown} this '
            f'installed lab-commons does not know (it knows {sorted(_KEYS)}); rebuild the venv '
            f'({running_interpreter()} -m dev_lab.dev.dep --bootstrap <checkout>)'
        )
        raise KitOlderThanCheckout(msg)
    ephemeral = table.get('ephemeral', list(FAMILY_EPHEMERAL))
    if not isinstance(ephemeral, list) or not all(isinstance(glob, str) and glob for glob in ephemeral):
        msg = f'{_TABLE} ephemeral in {manifest} is {ephemeral!r}; it must be a list of branch globs (pr/*)'
        raise BranchSetNotDeclared(msg)
    heads = table.get('task_heads', FAMILY_TASK_HEADS)
    if not isinstance(heads, str) or (heads and (not heads.endswith(_TASK_TAIL) or heads == _TASK_TAIL)):
        msg = (
            f'{_TABLE} task_heads in {manifest} is {heads!r}; it must be <namespace>{_TASK_TAIL} '
            f"(the default {FAMILY_TASK_HEADS!r}), or '' to judge no task head"
        )
        raise BranchSetNotDeclared(msg)
    prune, idle, ahead = _bounds(table, manifest)
    return BranchSet(
        trunk,
        frozenset(sessions),
        prune_merged=prune,
        max_idle_hours=idle,
        max_ahead=ahead,
        ephemeral=tuple(ephemeral),
        task_heads=heads,
    )


def _bounds(table: dict, manifest: str) -> tuple[bool, float, int | None]:
    """``prune_merged``, ``max_idle_hours`` and ``max_ahead`` of *table*, each refused by name when malformed."""
    prune = table.get('prune_merged', False)
    idle = table.get('max_idle_hours', 24.0)
    ahead = table.get('max_ahead')
    if not isinstance(prune, bool):
        msg = f'{_TABLE} prune_merged in {manifest} is {prune!r}; it must be true or false'
        raise BranchSetNotDeclared(msg)
    if isinstance(idle, bool) or not isinstance(idle, int | float) or idle < 0:
        msg = f'{_TABLE} max_idle_hours in {manifest} is {idle!r}; it must be a non-negative number of hours'
        raise BranchSetNotDeclared(msg)
    if ahead is not None and (isinstance(ahead, bool) or not isinstance(ahead, int) or ahead < 0):
        msg = f'{_TABLE} max_ahead in {manifest} is {ahead!r}; it must be a non-negative whole number of commits'
        raise BranchSetNotDeclared(msg)
    return prune, float(idle), ahead


def _short_refs(root: Path, prefix: str) -> tuple[str, ...] | None:
    """The sorted short names of the refs under *prefix*, or ``None`` when git could not answer."""
    out = git_out(root, 'for-each-ref', '--format=%(refname:short)', prefix)
    return None if out is None else tuple(sorted(n for n in out.splitlines() if n))


def _unpushed(root: Path, branch: str) -> int | None:
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
        ahead = _unpushed(root, name)
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


def apply_local(
    root: Path,
    branchset: BranchSet,
    *,
    occupied: Callable[[Path], bool] | None = None,
    limit: int | None = None,
    quiet_s: float = QUIET_S,
) -> tuple[str, ...] | None:
    """THE LOCAL CLEANUP DOOR: delete every deletable LOCAL candidate; one line per branch. ``None``: unread.

    User ruling 2026-10-04: local cleanup is a door, but a push or a REMOTE deletion is never automatic.
    So an origin candidate is only LISTED: a landed one with :data:`ORIGIN_DOOR`, the LOSSLESS-DELETE door an agent
    runs (ruling 2026-10-21; it lives in :mod:`dev_lab.dev.branchdelete`, which imports this module, so the door is
    named rather than called), an unlanded one with ``(merge first)``. Each local delete follows a
    FRESH ``merge-base --is-ancestor`` and is pinned to the sha that check saw (``update-ref -d <ref>
    <sha>``), so a branch that moved in between is kept, never lost. A declared branch, a branch with
    commits origin lacks, and a branch checked out in ANY worktree (clean or not -- ruling 2026-10-04:
    a tree is committed or cleared first) are never touched -- so every RECLAIMABLE worktree goes FIRST
    (:func:`dev_lab.dev.reclaim.reclaim`: clean, landed on a holder, unlocked, unoccupied), which is what
    frees its branch for the delete below; every kept tree is listed with its reason. *limit* bounds the trees
    removed per run and *quiet_s* how long a tree's index must be still; a tree's run outputs move home, verified,
    before it goes (:func:`dev_lab.dev.reclaim.reclaim`). LAST, TWO-FATES (:func:`dev_lab.dev.branchfate.settle`,
    ruling 2026-11-15): every local branch and tree still standing is kept for a named live owner, cleaned when
    merged and holding nothing unlanded, or listed with its doors (D31: never parked).
    """
    held_by = holders(root, branchset)
    trees = reclaim(root, held_by, occupied=occupied, limit=limit, quiet_s=quiet_s)
    rows = merge_candidates(root, branchset)
    if rows is None or trees is None:
        return None
    busy = checked_out(root)
    out: list[str] = list(trees)
    for row in rows:
        if row.where == 'origin':
            hint = f'(agent: {ORIGIN_DOOR} {row.name})' if row.deletable else '(merge first)'
            out.append(f'listed   origin  {row.name}  {hint}')
            continue
        if row.where == 'tag':
            out.append(_drop_tag(root, row, held_by))
            continue
        ref = f'refs/heads/{row.name}'
        sha = (git_out(root, 'rev-parse', '--verify', '--quiet', ref) or '').strip()
        if not row.deletable or row.name in branchset.declared or not sha:
            out.append(f'kept     local   {row.name}  (not held by a declared branch)')
        elif row.name in busy or _unpushed(root, row.name) != 0:
            out.append(f'kept     local   {row.name}  (checked out in a worktree, or holds commits origin lacks)')
        elif not any(git_out(root, 'merge-base', '--is-ancestor', sha, h) is not None for h in held_by):
            out.append(f'kept     local   {row.name}  (ancestry re-check failed)')
        else:
            done = git_out(root, 'update-ref', '-d', ref, sha) is not None
            out.append(f'{"deleted " if done else "FAILED  "} local   {row.name}  ({sha[:10]})')
    fates = settle(root, held_by, branchset.declared, occupied=occupied, quiet_s=quiet_s, limit=limit)
    return None if fates is None else (*out, *fates)


def _drop_tag(root: Path, row: Candidate, holders: tuple[str, ...]) -> str:
    """A parked ``archive/*`` tag: deleted when merged (fresh ancestry, pinned sha), else listed to MERGE."""
    ref = f'refs/tags/{row.name}'
    sha = (git_out(root, 'rev-parse', '--verify', '--quiet', f'{ref}^{{commit}}') or '').strip()
    if not row.deletable or not sha:
        return f'kept     tag     {row.name}  (unmerged: merge it into a declared branch, then delete the tag)'
    if not any(git_out(root, 'merge-base', '--is-ancestor', sha, h) is not None for h in holders):
        return f'kept     tag     {row.name}  (ancestry re-check failed)'
    tag_sha = (git_out(root, 'rev-parse', '--verify', '--quiet', ref) or '').strip()
    done = git_out(root, 'update-ref', '-d', ref, tag_sha) is not None
    hint = f'(human, if pushed: git push origin --delete refs/tags/{row.name})'
    return f'{"deleted " if done else "FAILED  "} tag     {row.name}  {hint}'


def main(argv: list[str] | None = None) -> int:
    """List the merge-and-delete candidates; ``--apply`` deletes the deletable LOCAL ones. Exit 2: unread."""
    parser = argparse.ArgumentParser(prog='python -m dev_lab.dev.branchset', description=main.__doc__)
    parser.add_argument('--root', type=Path, default=Path.cwd(), help='the checkout to read (default: cwd)')
    parser.add_argument(
        '--apply',
        action='store_true',
        help='reclaim and delete landed LOCAL work, list unlanded work with its doors; origin gets its door',
    )
    parser.add_argument('--discard', metavar='BRANCH', help='remove ONE unlanded lane: its worktree and local branch')
    parser.add_argument('--approved', default='', help="with --discard: the user's words approving it (required)")
    args = parser.parse_args(argv)
    top = git_out(args.root, 'rev-parse', '--show-toplevel')
    if top is None:
        emit(f'{args.root} is not inside a git checkout; run from the checkout or pass --root <checkout>')
        return 2
    root = Path(top.strip())
    if args.discard:
        code, line = discard(root, declared_branchset(root), args.discard, args.approved)
        emit(line)
        return code
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
