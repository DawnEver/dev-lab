"""SHARED-CHECKOUT: what exists only on this box, and therefore exists for nobody.

THE RULE, AND WHY IT LOOKED UNCHECKABLE. "A box holds a SHARED, possibly concurrent checkout: there
is NO single-agent mode, the remote IS the only shared medium, pushing is the obligation rather than
the last step of landing, and a verdict cannot be delegated to someone who cannot see the code."
Both siblings declared it absent for the same stated reason -- ``wdg-lab``'s, verbatim: *"the push
obligation is a fact about origin, not about any file in this checkout"*. That reason is true and
the conclusion drawn from it was wrong. A guard does not have to be about a FILE. ``git`` answers
"what is here that origin does not have" exactly, cheaply, and without a network call, and this
module is that question asked three ways:

* :func:`classify` -- every worktree's branch against the trunk, in four classes. It makes UNKNOWING
  maintenance of several branches impossible, which is the state that produced a 107-commit lane
  nobody had pushed while its trunk sat two months stale.
* :func:`survey` -- every ``origin/<branch>``, and how many of its CHANGES are not on the base.
* :func:`debris` -- worktree directories git no longer knows about, and local branches with no
  origin counterpart and no worktree holding them.

MEASURED AGAINST THE REMOTE, NEVER AGAINST A LOCAL POINTER, and this is the trap the shared half
exists to carry. A local trunk ref goes stale the moment another party pushes: MEASURED in
motronics-studio 2026-09-05, a main checkout sat at ``integrate/main`` 0aa61ec5 while origin was at
c043827c, and against that stale ref a fully-integrated lane showed 24 unintegrated commits and was
reported as a second pushable branch -- the audit that exists to stop debt accumulating was itself
manufacturing it. The same trap in the other direction was measured on the origin-branch survey:
``vs local main: 0`` unmerged, ``vs origin/main: 352``.

``git cherry``, NEVER ``merge-base --is-ancestor``, FOR CONTENT. Ancestry answers a question about
commit identity; ``cherry`` compares patch-ids, so a change that was cherry-picked or rebased
upstream is correctly reported as already there. Reading ancestry as content membership is the
measured mistake that nearly cost two merged lanes their directories.

AN UNREADABLE REPOSITORY IS ``None``, NEVER AN EMPTY LIST. That is the vacuous-green shape this
family pays for most often, and it has been paid for here already: a census that returned nothing on
a box with damaged instrumentation reported "no worker process running" whether or not any existed.

Provenance: motronics-studio's ``scripts/lanes/session_branches.py``,
``scripts/lanes/prune_origin_branches.py`` and ``scripts/repo/worktree_debris.py``, migrated
2026-09-16. Every repo-shaped fact in them -- where worktrees live, which branch is the trunk, which
names are protected -- arrives here as an ARGUMENT, because those three differ per repo and the
question does not.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    'DEFAULT_PROTECTED',
    'DEFAULT_WORKTREE_HOME',
    'Debris',
    'OriginBranch',
    'WorktreeBranch',
    'authority_for',
    'classify',
    'debris',
    'git_out',
    'origin_branches',
    'orphan_directories',
    'stale_branches',
    'survey',
    'unmerged_changes',
    'worktrees',
]

#: Resolved once: a bare name is a PATH lookup at every call site, and a PATH that answers
#: differently between a terminal and a detached launcher describes an environment nobody meant.
_GIT = shutil.which('git') or 'git'

#: Every call here reads LOCAL refs -- no network, no hook, no editor -- so a run that has not
#: answered in half a minute is hung rather than slow. A child this waits on forever parks a whole
#: suite at 0% CPU until something far away times out, and the verdict is then evidence about
#: nothing.
_GIT_TIMEOUT_S = 30

#: Branch names that are never debris and never deletion candidates, whatever their merge state.
#: A DEFAULT rather than a law: a repo whose trunk is not called ``main`` passes its own.
DEFAULT_PROTECTED = frozenset({'main', 'HEAD'})

#: Where a repo that runs parallel lanes keeps their worktrees. A DEFAULT for the same reason; a
#: repo that keeps none simply has no orphans to find, which :func:`orphan_directories` reports as
#: an empty list rather than as an unreadable tree.
DEFAULT_WORKTREE_HOME = Path('.claude') / 'worktrees'


@dataclass(frozen=True)
class WorktreeBranch:
    """One worktree, its branch, and the class the integration state puts it in.

    A branch is NOT classified by its NAME. A naming convention is a hint; the test is integration
    state, so a branch whose commits are all in the trunk is ``stale`` whatever it is called, and a
    branch with commits nowhere else is ``fan-out`` whatever it is called.
    """

    path: Path
    branch: str
    kind: str
    note: str


@dataclass(frozen=True)
class OriginBranch:
    """One ``origin/<name>`` and the measurement that decides it."""

    name: str
    unmerged: int

    @property
    def deletable(self) -> bool:
        """Zero CHANGES not already on the base. Patch-id equality, never ancestry."""
        return self.unmerged == 0


@dataclass(frozen=True)
class Debris:
    """What nothing will clean up on its own. ``None`` in a field means it could not be read."""

    orphan_directories: tuple[Path, ...] | None
    stale_branches: tuple[str, ...] | None

    @property
    def readable(self) -> bool:
        """Whether BOTH questions were answered. An unread repo is not a clean one."""
        return self.orphan_directories is not None and self.stale_branches is not None


def git_out(root: Path, *args: str) -> str | None:
    """``git <args>`` in *root*, or ``None`` when git could not answer.

    ``None`` IS NOT THE EMPTY STRING, and every caller in this module depends on the distinction:
    an unreadable repository must never render as a clean one.
    """
    try:
        done = subprocess.run(
            [_GIT, *args], cwd=root, capture_output=True, text=True, check=False, timeout=_GIT_TIMEOUT_S
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return done.stdout if done.returncode == 0 else None


def worktrees(root: Path) -> tuple[tuple[Path, str], ...] | None:
    """``((path, branch-or-'detached'), ...)`` for EVERY worktree, the MAIN checkout first.

    The main worktree is the first entry of ``git worktree list --porcelain`` -- git's own
    definition, independent of where the caller happens to be standing.
    """
    out = git_out(root, 'worktree', 'list', '--porcelain')
    if out is None:
        return None
    found: list[tuple[Path, str]] = []
    path: Path | None = None
    for line in out.splitlines():
        if line.startswith('worktree '):
            path = Path(line.removeprefix('worktree ').strip())
        elif line.startswith('branch ') and path is not None:
            found.append((path, line.removeprefix('branch refs/heads/').strip()))
            path = None
        elif line.startswith('detached') and path is not None:
            found.append((path, 'detached'))
            path = None
    return tuple(found)


def _has_origin(root: Path, branch: str) -> bool:
    """Does origin carry this branch at all?"""
    return git_out(root, 'show-ref', '--verify', '--quiet', f'refs/remotes/origin/{branch}') is not None


def _is_ancestor(root: Path, branch: str, of: str) -> bool:
    """Is *branch* an ancestor of *of*? Identity, not content -- see the module docstring."""
    if branch in ('detached', 'HEAD'):
        return False
    return git_out(root, 'merge-base', '--is-ancestor', branch, of) is not None


def authority_for(root: Path, trunk: str) -> str:
    """``origin/<trunk>`` when origin carries it, else *trunk* -- THE REMOTE IS THE AUTHORITY.

    A verdict must not depend on when somebody last fetched. Falls back to the local name rather
    than raising, because a repo with no origin is a legitimate state -- an offline box, a fresh
    init -- and the audit is still meaningful there; it just answers about the only authority
    available, which is what the caller can act on.
    """
    return f'origin/{trunk}' if _has_origin(root, trunk) else trunk


def unmerged_changes(root: Path, base: str, head: str) -> int | None:
    """How many of *head*'s commits have no patch-id equivalent on *base*, or ``None``.

    ``git cherry`` prints ``+`` for a commit whose CHANGE is not in base and ``-`` for one that is,
    so counting the ``+`` lines answers "is this change already there" for a cherry-picked or
    rebased lane, which ancestry cannot.
    """
    out = git_out(root, 'cherry', base, head)
    return None if out is None else sum(1 for line in out.splitlines() if line.startswith('+'))


def classify(root: Path, *, trunk: str | None = None) -> tuple[WorktreeBranch, ...] | None:
    """Classify every worktree's branch into ``trunk`` / ``primary`` / ``fan-out`` / ``stale``.

    * ``trunk`` -- the main checkout's branch, the one branch a session pushes.
    * ``primary`` -- a non-trunk branch that origin CARRIES and that is not fully integrated: a
      SECOND pushable branch, which is the violation this audit exists to make visible.
    * ``fan-out`` -- commits not on origin and not integrated: temporary, must reconcile or go.
    * ``stale`` -- fully contained in the trunk: safe to delete with its tree.

    *trunk* defaults to the MAIN checkout's current branch. Two names, two questions: the identity
    test ("is this worktree the trunk?") uses the LOCAL name, because the main checkout is on
    ``integrate/main`` and not on ``origin/integrate/main``, while INTEGRATION is measured against
    :func:`authority_for`.
    """
    trees = worktrees(root)
    if trees is None or not trees:
        return None
    name = trunk or trees[0][1]
    authority = authority_for(root, name)
    rows: list[WorktreeBranch] = []
    for path, branch in trees:
        if branch == name:
            rows.append(WorktreeBranch(path, branch, 'trunk', 'the one branch a session pushes'))
            continue
        if branch == 'detached':
            rows.append(WorktreeBranch(path, branch, 'fan-out', 'detached HEAD is not a maintained branch'))
            continue
        unmerged = unmerged_changes(path, authority, 'HEAD')
        if unmerged == 0 and _is_ancestor(root, branch, authority):
            rows.append(WorktreeBranch(path, branch, 'stale', 'all commits are in trunk; delete tree and branch'))
        elif _has_origin(root, branch):
            rows.append(
                WorktreeBranch(path, branch, 'primary', 'pushed to origin -- a SECOND pushable branch for one session')
            )
        else:
            rows.append(
                WorktreeBranch(
                    path,
                    branch,
                    'fan-out',
                    f'{"an unreadable number of" if unmerged is None else unmerged} commit(s) not in '
                    f'{authority}; reconcile or delete',
                )
            )
    return tuple(rows)


def origin_branches(root: Path, *, protected: frozenset[str] = DEFAULT_PROTECTED) -> tuple[str, ...] | None:
    """Every ``origin/<name>`` except the protected ones, with the remote prefix stripped."""
    listed = git_out(root, 'for-each-ref', '--format=%(refname:strip=3)', 'refs/remotes/origin')
    if listed is None:
        return None
    return tuple(sorted({n for n in listed.splitlines() if n and n not in protected}))


def survey(root: Path, base: str, *, protected: frozenset[str] = DEFAULT_PROTECTED) -> tuple[OriginBranch, ...] | None:
    """Every origin branch and how many of its CHANGES are not on *base*.

    *base* has no default ON PURPOSE. The branch a lane integrates into is a fact about the lane,
    and defaulting it would compare against a branch the work never targeted -- reporting a lane
    fully merged when nothing of it is. Pass ``origin/main``, not ``main``: the measured gap
    between those two spellings on one box was 0 against 352.
    """
    names = origin_branches(root, protected=protected)
    if names is None:
        return None
    rows = []
    for name in names:
        count = unmerged_changes(root, base, f'origin/{name}')
        if count is None:
            return None
        rows.append(OriginBranch(name, count))
    return tuple(rows)


def orphan_directories(root: Path, *, home: Path = DEFAULT_WORKTREE_HOME) -> tuple[Path, ...] | None:
    """Directories under *home* that git no longer calls worktrees.

    Nested ONE level, because a lane may be named ``feat/<slug>`` and land two directories down: a
    directory whose CHILD is a registered worktree is not itself an orphan.
    """
    listed = git_out(root, 'worktree', 'list', '--porcelain')
    if listed is None:
        return None
    registered = {
        Path(line[len('worktree ') :].strip()).resolve() for line in listed.splitlines() if line.startswith('worktree ')
    }
    base = (root / home).resolve()
    if not base.is_dir():
        return ()
    orphans: list[Path] = []
    for entry in sorted(base.iterdir()):
        if not entry.is_dir() or entry.resolve() in registered:
            continue
        if any(child.resolve() in registered for child in entry.iterdir() if child.is_dir()):
            continue
        orphans.append(entry.resolve())
    return tuple(orphans)


def stale_branches(root: Path, *, protected: frozenset[str] = DEFAULT_PROTECTED) -> tuple[str, ...] | None:
    """Local branches with no ``origin/`` counterpart, no upstream, and no worktree holding them.

    A branch checked out SOMEWHERE is live by definition, however odd its name, and deleting a
    checked-out branch is how an agent loses work it has not pushed.
    """
    listed = git_out(root, 'for-each-ref', '--format=%(refname:short)|%(upstream)|%(worktreepath)', 'refs/heads/')
    remotes = git_out(root, 'for-each-ref', '--format=%(refname:short)', 'refs/remotes/origin/')
    if listed is None or remotes is None:
        return None
    published = {name.split('/', 1)[1] for name in remotes.split() if '/' in name}
    stale: list[str] = []
    for row in listed.splitlines():
        name, _, rest = row.partition('|')
        upstream, _, worktree = rest.partition('|')
        if not name or name in protected or worktree.strip() or upstream.strip() or name in published:
            continue
        stale.append(name)
    return tuple(stale)


def debris(root: Path, *, home: Path = DEFAULT_WORKTREE_HOME, protected: frozenset[str] = DEFAULT_PROTECTED) -> Debris:
    """The whole census as data, so a caller can render it or assert on it."""
    return Debris(
        orphan_directories=orphan_directories(root, home=home),
        stale_branches=stale_branches(root, protected=protected),
    )
