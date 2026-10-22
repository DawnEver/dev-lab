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

THE OWNER'S CHECKOUT, THE OWNER'S PUSH. Run by the owner's agent in develop mode on a clean tree.
It merges locally and stops: the owner runs their tests and pushes. It never pushes, and it refuses on
the trunk, on the integration branch and on a detached HEAD, where a sync has no meaning.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import lab_commons.launch as _door
from lab_commons.log import emit

from dev_lab.dev.forge import _GIT, _GIT_TIMEOUT_S, fetch_origin
from dev_lab.dev.lanepolicy import Policy, load_policy
from dev_lab.dev.trialmerge import Trial, rev, trial

__all__ = ['CONFIG_KEY', 'Plan', 'main', 'plan', 'refused', 'sync', 'unwatch', 'upstreams', 'watch']

#: The per-branch git config key holding the opt-in refs (``branch.<child>.labSyncFrom``).
CONFIG_KEY: Final = 'labSyncFrom'

_ORIGIN: Final = 'origin/'


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
        msg = f'{ref!r} names no commit in {root}; fetch it first, or spell it as origin/<branch>'
        raise ValueError(msg)
    if ref not in _git(root, 'config', '--get-all', _key(branch)).stdout.split():
        _git(root, 'config', '--add', _key(branch), ref)


def unwatch(root: Path, branch: str, ref: str) -> None:
    """Remove *ref* from *branch*'s watched set; removing an unwatched ref is a no-op."""
    _git(root, 'config', '--fixed-value', '--unset-all', _key(branch), ref)


def refused(ref: str, allowed: Sequence[str], branch: str) -> str | None:
    """Why merging *ref* into *branch* is refused, or ``None`` when *ref* is in its upstream set."""
    if ref in allowed:
        return None
    return (
        f'{ref} is not in the upstream set of {branch} ({", ".join(allowed)}): a child branch merges only '
        f'integration (DOWNSTREAM-SYNCS-INTEGRATION). To opt in: forge sync --watch {ref}'
    )


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
    if not branch:
        msg = 'HEAD is detached: sync updates a child branch, so check one out'
        raise ValueError(msg)
    if branch in {policy.trunk, policy.integration}:
        msg = (
            f'{branch} is not a child branch: only the integrator moves {policy.integration}, '
            f'only promote moves {policy.trunk}'
        )
        raise ValueError(msg)
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
            msg = f'{ref} names no commit in {root}; fetch it first'
            raise ValueError(msg)
    return Plan(branch, tuple((ref, trial(root, ref, 'HEAD')) for ref in chosen))


def sync(root: Path, policy: Policy, refs: Sequence[str] | None = None) -> tuple[Plan, tuple[str, ...]]:
    """Merge every behind ref of the plan, integration first; nothing when any would conflict.

    Returns the plan and the refs actually merged. A dirty tree is refused before anything is read.
    """
    if _git(root, 'status', '--porcelain', '--untracked-files=no').stdout.strip():
        msg = 'the tree has uncommitted changes: commit them first, a merge must start from a commit'
        raise ValueError(msg)
    found = plan(root, policy, refs)
    if found.conflicting:
        return found, ()
    merged = []
    for ref, tried in found.trials:
        if tried.behind == 0:
            continue
        done = _git(root, 'merge', '--no-ff', '--no-edit', ref)
        if done.returncode != 0:
            _git(root, 'merge', '--abort')
            why = (done.stderr or done.stdout).strip()
            msg = f'git merge {ref} failed after a clean trial and was aborted (merged so far: {merged}): {why}'
            raise OSError(msg)
        merged.append(ref)
    return found, tuple(merged)


def _render(found: Plan) -> list[str]:
    lines = [f'[sync] {found.branch}: upstream set {", ".join(ref for ref, _ in found.trials)}']
    for ref, tried in found.trials:
        state = 'clean' if tried.clean else 'CONFLICTS in ' + ', '.join(tried.conflicts)
        lines.append(f'[sync]   {ref}: behind {tried.behind}; {state}')
    return lines


def main(
    argv: Sequence[str] | None = None, *, cwd: Path | None = None, fetch: Callable[[Path], None] = fetch_origin
) -> int:
    """``forge sync [--watch REF | --unwatch REF | --list]``; exit 2 on a refusal or a conflict."""
    parser = argparse.ArgumentParser(prog='dev_lab.dev.forge sync', description=__doc__.splitlines()[0])
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--watch', metavar='REF', help='opt this branch in to also merge REF')
    group.add_argument('--unwatch', metavar='REF', help="drop REF from this branch's watched set")
    group.add_argument('--list', action='store_true', help="print this branch's upstream set and exit")
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    root = Path.cwd() if cwd is None else cwd
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
    except (OSError, ValueError) as exc:
        emit(f'[sync] refused: {exc}', err=True)
        return 2
    for line in _render(found):
        emit(line)
    if found.conflicting:
        for ref, tried in found.conflicting:
            emit(f'[sync] stopped: {ref} conflicts in {", ".join(tried.conflicts)}; nothing was merged.', err=True)
            emit(f'[sync] Remedy: git merge {ref}, resolve those files, commit, run your tests, push.', err=True)
        return 2
    if not merged:
        emit('[sync] up to date; nothing to merge')
        return 0
    emit(
        f'[sync] merged {", ".join(merged)}; now measure what you touched, then push {found.branch}; '
        'the forge produces its parts'
    )
    return 0
