"""``forge sync``: bring the CURRENT child branch up to date with its upstream set -- by merge, never rebase.

THE PRINCIPLE (``DOWNSTREAM-SYNCS-INTEGRATION``, user ruling 2026-10-11). A child branch (a lane, a
``feat/*``, a PR head) merges ONLY the integration branch. It never pulls another child's work in
sideways: that work reaches it once, through integration, after the integrator merged it. The owner
may opt in to watch specific additional refs, and the opt-in lives in ONE place, local to the
checkout and native to git -- the multi-valued ``branch.<child>.labSyncFrom`` config -- managed by
``--watch``/``--unwatch``/``--list``. No file, nothing committed: it is one person's choice about one
checkout. A ref outside that set is REFUSED by name (:func:`refused`).

THE ORDER. Integration first, then each watched ref in the order it was watched. Every ref is
trial-merged in the object store first (:mod:`dev_lab.dev.trialmerge`); its behind count and
conflicts are reported BEFORE anything is merged, and if any ref would conflict nothing is merged at
all -- the owner resolves by running the named ``git merge`` themself. The tree is never left half-merged
by this command.

THEN THE LOCK (user ruling 2026-11-07). A clean sync then relocks every floated sibling (dev-lab, lab-commons, ...)
to its line's current head through the dependency door (:func:`relock_floating`) and commits
the lock in the same sync (:func:`relock`) together with every generated file the new pin renders -- each
renderer the repo's files call for (:data:`dev_lab.dev.famfiles.RENDERERS`), run with the tree's re-synced
environment (:func:`dev_lab.dev.relock.rerender`) -- so ONE push of the result is current for the ``pr-current``
judgment (:mod:`dev_lab.dev.prcurrent`), which names a ``pr/*`` head that lacks integration's tip or lags a sibling.

THE OWNER'S CHECKOUT, THE OWNER'S PUSH. Run by the owner's agent in develop mode on a clean tree.
It merges locally and stops: the owner runs their tests and pushes. It never pushes, and it refuses on
the trunk, on the integration branch and on a detached HEAD, where a sync has no meaning.

EVERY REFUSAL TEACHES (principle ``every-wall-teaches``). Each refusal and stop is ``<RULE-ID>: <cause>``, its door on
the next line and a ``details:`` pointer last, recorded through :func:`dev_lab.dev.walls.refused_text` -- so the
ledger names the rule and that a door was named (measured 2026-11-17: a one-line refusal was a wall with no rule and
no door). The rules: :data:`UPSTREAM_SET`, :data:`STARTS_FROM_A_COMMIT`, :data:`STOPS_ON_A_CONFLICT`,
:data:`STEP_FAILED` (``docs-src/dev/refusals.md``), and the task gate's own.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import lab_commons.launch as _door
from lab_commons.log import emit

from dev_lab.dev import datadeps, taskgate, walls
from dev_lab.dev.disclosure import details_for
from dev_lab.dev.forge import _GIT, _GIT_TIMEOUT_S, fetch_origin
from dev_lab.dev.labsession import trailers
from dev_lab.dev.lanepolicy import Policy, load_policy
from dev_lab.dev.lockcheck import LOCK
from dev_lab.dev.relock import RelockFailed, door_upgrade, rerender, siblings
from dev_lab.dev.trialmerge import Trial, rev, trial

__all__ = [
    'CONFIG_KEY', 'RELOCK_TITLE', 'STARTS_FROM_A_COMMIT', 'STEP_FAILED', 'STOPS_ON_A_CONFLICT', 'UPSTREAM_SET', 'Plan',
    'main', 'plan', 'refused', 'relock', 'relock_floating', 'sync', 'unwatch', 'upstreams', 'watch',
]  # fmt: skip

#: The per-branch git config key holding the opt-in refs (``branch.<child>.labSyncFrom``).
CONFIG_KEY: Final = 'labSyncFrom'

_ORIGIN: Final = 'origin/'

#: The file a data pin's relock rewrites (:mod:`dev_lab.dev.datadeps`).
PYPROJECT: Final = 'pyproject.toml'
#: The subject of the commit a sync's relock lands as.
RELOCK_TITLE: Final = 'build(deps): relock the floated siblings and data pins to their current heads'

#: The registry row a sync of a ref outside the upstream set, or of no child branch, is refused under.
UPSTREAM_SET: Final = 'DOWNSTREAM-SYNCS-INTEGRATION'
#: A merge (and a relock commit) starts from a commit: a dirty tree, a half-done merge or a held index is refused.
STARTS_FROM_A_COMMIT: Final = 'SYNC-STARTS-FROM-A-COMMIT'
#: A ref whose trial merge conflicts stops the sync before anything is merged; the owner resolves it.
STOPS_ON_A_CONFLICT: Final = 'SYNC-STOPS-ON-A-CONFLICT'
#: A step (fetch, merge commit, relock) failed; a failed merge is aborted and a failed relock restored.
STEP_FAILED: Final = 'SYNC-STEP-FAILED'
_RERUN: Final = 'then rerun forge sync'


def _refusal(rule: str, cause: str, door: str) -> str:
    """``<rule>: <cause>`` with ``Door: <door>`` on a line of its own (:func:`dev_lab.dev.walls.has_remedy`)."""
    return f'{rule}: {cause}\nDoor: {door}'


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return _door.run(
        [_GIT, *args],
        cwd=root,
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
        timeout=_GIT_TIMEOUT_S,
        check=False,
    )


def _key(branch: str) -> str:
    return f'branch.{branch}.{CONFIG_KEY}'


def upstreams(root: Path, branch: str, policy: Policy) -> tuple[str, ...]:
    """*branch*'s upstream set: ``origin/<integration>`` first, then each watched ref in watch order."""
    watched = _git(root, 'config', '--get-all', _key(branch)).stdout.split()
    base = _ORIGIN + policy.integration
    return (base, *(ref for ref in dict.fromkeys(watched) if ref != base))


def watch(root: Path, branch: str, ref: str) -> None:
    """Add *ref* to *branch*'s watched set (idempotent); a ref git cannot resolve is refused."""
    if rev(root, ref) is None:
        door = f'git fetch origin, or spell it as origin/<branch>, then rerun forge sync --watch {ref}'
        raise ValueError(_refusal(UPSTREAM_SET, f'{ref!r} names no commit in {root}', door))
    if ref not in _git(root, 'config', '--get-all', _key(branch)).stdout.split():
        _git(root, 'config', '--add', _key(branch), ref)


def unwatch(root: Path, branch: str, ref: str) -> None:
    """Remove *ref* from *branch*'s watched set; removing an unwatched ref is a no-op."""
    _git(root, 'config', '--fixed-value', '--unset-all', _key(branch), ref)


def refused(ref: str, allowed: Sequence[str], branch: str) -> str | None:
    """Why merging *ref* into *branch* is refused, or ``None`` when *ref* is in its upstream set."""
    if ref in allowed:
        return None
    listed = ', '.join(allowed)
    cause = f'{ref} is not in the upstream set of {branch} ({listed}): a child branch merges only integration'
    return _refusal(UPSTREAM_SET, cause, f'opt in with python -m dev_lab.dev.forge sync --watch {ref}, {_RERUN}')


@dataclass(frozen=True)
class Plan:
    """The current branch and, per upstream ref, what merging it would do."""

    branch: str
    trials: tuple[tuple[str, Trial], ...]

    @property
    def conflicting(self) -> tuple[tuple[str, Trial], ...]:
        """The refs whose merge would conflict."""
        return tuple(item for item in self.trials if not item[1].clean)


def _current(root: Path, policy: Policy) -> str:
    branch = _git(root, 'symbolic-ref', '--short', '-q', 'HEAD').stdout.strip()
    door = f'git switch <your child branch>, {_RERUN} there'
    if not branch:
        raise ValueError(_refusal(UPSTREAM_SET, 'HEAD is detached: sync updates a child branch', door))
    if branch in {policy.trunk, policy.integration}:
        cause = f'{branch} is not a child branch: only the integrator moves {policy.integration}, only promote moves'
        raise ValueError(_refusal(UPSTREAM_SET, f'{cause} {policy.trunk}', door))
    return branch


def plan(root: Path, policy: Policy, refs: Sequence[str] | None = None) -> Plan:
    """Trial every ref of the upstream set (or *refs*, each of which must be in it) against HEAD."""
    branch = _current(root, policy)
    allowed = upstreams(root, branch, policy)
    chosen = allowed if refs is None else tuple(refs)
    for ref in chosen:
        if (why := refused(ref, allowed, branch)) is not None:
            raise ValueError(why)
        if rev(root, ref) is None:
            raise ValueError(_refusal(UPSTREAM_SET, f'{ref} names no commit in {root}', f'git fetch origin, {_RERUN}'))
    return Plan(branch, tuple((ref, trial(root, ref, 'HEAD')) for ref in chosen))


def sync(root: Path, policy: Policy, refs: Sequence[str] | None = None) -> tuple[Plan, tuple[str, ...]]:
    """Merge every behind ref of the plan, integration first; nothing when any would conflict.

    Returns the plan and the refs actually merged. A dirty tree is refused before anything is read.
    """
    if (pending := _git(root, 'rev-parse', '-q', '--verify', 'MERGE_HEAD')).returncode == 0:
        cause = f'a merge of {pending.stdout.strip()[:10]} is in progress and uncommitted (an earlier run was killed?)'
        door = f'git commit --no-edit to conclude it, or git merge --abort, {_RERUN}'
        raise ValueError(_refusal(STARTS_FROM_A_COMMIT, cause, door))
    if _git(root, 'status', '--porcelain', '--untracked-files=no').stdout.strip():
        cause = 'the tree has uncommitted changes, and a merge must start from a commit'
        raise ValueError(_refusal(STARTS_FROM_A_COMMIT, cause, f'commit them (git add <paths>; git commit), {_RERUN}'))
    found = plan(root, policy, refs)
    if found.conflicting:
        return found, ()
    merged = []
    for ref, tried in found.trials:
        if tried.behind == 0:
            continue
        done = _git(root, 'merge', '--no-ff', '--no-commit', ref)
        if done.returncode == 0:
            done = _hooked(root, 'commit', '-q', '--no-edit', *_trailer_args())
        if done.returncode != 0:
            raise OSError(_failed_merge(root, ref, merged, done))
        merged.append(ref)
    return found, tuple(merged)


def relock_floating(tree: Path, *, upgrade: Callable[[Path, Sequence[str]], int] | None = None) -> tuple[str, ...]:
    """Relock *tree*'s floated siblings to their lines' current heads through the door; the names it moved.

    Writes the lock only; committing it is the caller's. RAISES :class:`~dev_lab.dev.relock.RelockFailed` when the
    door fails.
    """
    names = tuple(sorted(siblings(tree)))
    if not names:
        return ()
    if (exited := (upgrade or door_upgrade)(tree, names)) != 0:
        msg = f'the dependency door exited {exited} relocking {", ".join(names)} in {tree}'
        raise RelockFailed(msg)
    return names


def relock(
    root: Path,
    *,
    door: Callable[[Path], Sequence[str]] = relock_floating,
    render: Callable[[Path], Sequence[str]] = rerender,
    data: Callable[[Path], Sequence[str]] = datadeps.relock,
) -> tuple[str, ...]:
    """Relock *root*'s floated siblings (*door*); when the lock moved, re-*render* and commit both; the moved names.

    The rendered files depend on the dev-lab the lock now pins, so a relock that left them stale reds the repo's
    own suite (2026-11-07: numerics-lab's ``deny-rules.json`` after a new deny row). The lock and the renders are
    ONE commit. Nothing moved (no sibling, or each already at its head): nothing is rendered or committed, ``()``.
    RAISES :class:`OSError` (:class:`~dev_lab.dev.relock.RelockFailed` among them) when the door, a renderer or the
    commit fails, after restoring every file the relock touched to its committed state (user ruling 2026-11-07):
    a sync failing partway never leaves a dirty tree for the next sync to refuse.
    """
    if held := _staged(root):
        cause = f'the index already holds {", ".join(held)}, which a relock would sweep in'
        door = f'commit or unstage it first (git restore --staged -- <paths>), {_RERUN}'
        raise RelockFailed(_refusal(STARTS_FROM_A_COMMIT, cause, door))
    clean = _touched(root)
    try:
        names = (*door(root), *data(root))
        moved = {row[3:] for row in _git(root, 'status', '--porcelain', '--', LOCK, PYPROJECT).stdout.splitlines()}
        if not names or not moved:
            return ()
        rendered = tuple(render(root))
        # ONLY what the door and the renderers wrote: they never stage, so a path staged meanwhile is someone else's.
        wrote = sorted(({path for _, path in _touched(root) - clean} - set(_staged(root))) | moved)
        body = '\n'.join([f'Relocked: {", ".join(names)}', *([f'Rendered: {", ".join(rendered)}'] if rendered else [])])
        if (done := _git(root, 'add', '--', *wrote)).returncode != 0 or (
            done := _commit(root, wrote, RELOCK_TITLE, body)
        ).returncode != 0:
            msg = f'committing the relocked {LOCK} failed: {(done.stderr or done.stdout).strip()}'
            raise RelockFailed(msg)
    except (OSError, datadeps.DataRefused):
        _restore(root, _touched(root) - clean)
        raise
    return names


def _staged(root: Path) -> tuple[str, ...]:
    """The paths *root*'s index holds against HEAD."""
    return tuple(_git(root, 'diff', '--cached', '--name-only').stdout.split('\n')[:-1])


def _commit(root: Path, paths: Sequence[str], *message: str) -> subprocess.CompletedProcess[str]:
    """``git commit --only -- <paths>``: exactly *paths*, whatever else the index holds."""
    message_args = (arg for line in message for arg in ('-m', line))
    return _hooked(root, 'commit', '-q', *message_args, *_trailer_args(), '--only', '--', *paths)


def _hooked(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """``git <args>`` for a command that runs the repo's commit hooks: NO TIMEOUT.

    The hook runner itself runs them unbounded (:mod:`dev_lab.dev.githooks.runner`); acme-consumer's exceed 30 s
    (2026-11-07) and a sync's merge commit died on the fixed 30 s (2026-11-13), so any ceiling here is a guess.
    """
    argv = [_GIT, *args]
    return _door.run(argv, cwd=root, capture_output=True, text=True, encoding='utf-8', errors='replace', check=False)


def _failed_merge(root: Path, ref: str, merged: Sequence[str], done: subprocess.CompletedProcess[str]) -> str:
    """The state a failed merge of *ref* left -- aborted when uncommitted, else what HEAD holds -- and its door."""
    why = ' '.join((done.stderr or done.stdout).split()) or f'exit {done.returncode}'
    so_far = f'merged so far: {", ".join(merged) or "nothing"}'
    if _git(root, 'rev-parse', '-q', '--verify', 'MERGE_HEAD').returncode != 0:
        head = _git(root, 'rev-parse', '--short', 'HEAD').stdout.strip()
        cause = f'git merge {ref} exited {done.returncode} but no merge is pending; HEAD is {head} ({so_far}): {why}'
        return _refusal(STEP_FAILED, cause, f'git log -1 {head} to see what HEAD holds, {_RERUN}')
    _git(root, 'merge', '--abort')
    cause = f'git merge {ref} was NOT committed (exit {done.returncode}) and was aborted ({so_far}): {why}'
    return _refusal(STEP_FAILED, cause, f'fix what the commit hooks refused, {_RERUN}')


def _trailer_args() -> list[str]:
    """``--trailer`` for each session trailer (:func:`~dev_lab.dev.labsession.trailers`).

    A sync's commits are the session's and carry it whether or not the commit-msg hook is installed (it replaces).
    """
    return [arg for line in trailers() for arg in ('--trailer', line)]


def _touched(root: Path) -> frozenset[tuple[bool, str]]:
    """Every path ``git status`` reports in *root*, each with whether it is untracked."""
    listed = _git(root, 'status', '--porcelain', '-z', '--untracked-files=all').stdout
    return frozenset((row[:2] == '??', row[3:]) for row in listed.split('\0') if row)


def _restore(root: Path, touched: frozenset[tuple[bool, str]]) -> None:
    """Return each *touched* path to its committed state: tracked ones from HEAD, new ones removed."""
    if tracked := sorted(path for new, path in touched if not new):
        _git(root, 'checkout', 'HEAD', '--', *tracked)
    for path in sorted(path for new, path in touched if new):
        (root / path).unlink(missing_ok=True)


def _render(found: Plan) -> list[str]:
    lines = [f'[sync] {found.branch}: upstream set {", ".join(ref for ref, _ in found.trials)}']
    for ref, tried in found.trials:
        state = 'clean' if tried.clean else 'CONFLICTS in ' + ', '.join(tried.conflicts)
        lines.append(f'[sync]   {ref}: behind {tried.behind}; {state}')
    return lines


def task_refusal(root: Path) -> str | None:
    """Why the task gate would refuse this session's commits in *root*, else ``None``.

    :func:`dev_lab.dev.taskgate.refusal` decides it. A sync commits its merge and its relock, so it asks first: refused,
    nothing is fetched, merged or relocked. In a consumer repo (2026-11-16) the relock commit used to be refused after
    the tree had been rewritten, naming no door.
    """
    return taskgate.refusal(root, env=os.environ)


def _refuse(root: Path, text: str, *, reason: str) -> int:
    """Print one refusal -- rule line, door line, ``details:`` pointer -- and record its wall; exit 2.

    A text naming no rule (a failed fetch, a relock step) is a :data:`STEP_FAILED`: a step failing partway leaves no
    half-done state (a failed merge is aborted, a failed relock restored), so fixing the cause and rerunning is the
    door.
    """
    if walls.rule_of(text).startswith(walls.UNNAMED):
        text = _refusal(STEP_FAILED, ' '.join(text.split()), f'fix what the line above names, {_RERUN}')
    shown = f'{text}\n{details_for(walls.rule_of(text))}'
    emit(shown, err=True)
    walls.refused_text(root, shown, reason=reason)
    return 2


def main(
    argv: Sequence[str] | None = None,
    *,
    cwd: Path | None = None,
    fetch: Callable[[Path], None] = fetch_origin,
    door: Callable[[Path], Sequence[str]] = relock_floating,
) -> int:
    """``forge sync [--watch REF | --unwatch REF | --list]``: merge, then relock; exit 2 on a refusal or a conflict."""
    parser = argparse.ArgumentParser(prog='dev_lab.dev.forge sync', description=__doc__.splitlines()[0])
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--watch', metavar='REF', help='opt this branch in to also merge REF')
    group.add_argument('--unwatch', metavar='REF', help="drop REF from this branch's watched set")
    group.add_argument('--list', action='store_true', help="print this branch's upstream set and exit")
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    root = Path.cwd() if cwd is None else cwd
    if not (args.watch or args.unwatch or args.list) and (why := task_refusal(root)):
        return _refuse(root, why, reason='task')
    policy = load_policy(root)
    try:
        branch = _current(root, policy)
        if args.watch or args.unwatch:
            (watch if args.watch else unwatch)(root, branch, args.watch or args.unwatch)
        if args.watch or args.unwatch or args.list:
            emit(f'[sync] {branch}: upstream set {", ".join(upstreams(root, branch, policy))}')
            return 0
        fetch(root)
        found, merged = sync(root, policy)
        relocked = () if found.conflicting else relock(root, door=door)
    except (OSError, ValueError, subprocess.SubprocessError, datadeps.DataRefused) as exc:
        return _refuse(root, str(exc), reason='refused')
    for line in _render(found):
        emit(line)
    if found.conflicting:
        clashes = '; '.join(f'{ref} conflicts in {", ".join(tried.conflicts)}' for ref, tried in found.conflicting)
        door = f'git merge {found.conflicting[0][0]}, resolve those files, commit, run your tests, {_RERUN}'
        return _refuse(root, _refusal(STOPS_ON_A_CONFLICT, f'{clashes}; nothing was merged', door), reason='conflict')
    if relocked:
        emit(f'[sync] relocked {", ".join(relocked)} to their current heads; committed {LOCK} with what it renders')
    if not merged and not relocked:
        emit('[sync] up to date; nothing to merge or relock')
        return 0
    did = ', '.join([*(f'merged {ref}' for ref in merged), *(['relocked'] if relocked else [])])
    emit(f'[sync] {did}; now measure what you touched, then push {found.branch}; the forge produces its parts')
    return 0
