"""INTEGRATION NEEDS NO WORKING TREE: merge a branch into the integration branch, or promote the trunk, by refs alone.

The integration branch is one more session branch (:mod:`lab_commons.dev.sessionbranch`): what makes a
commit on it legitimate is that it is a merge that passes the audit and lands by fast-forward, not which
directory it was made in. So neither verb checks anything out, and neither pushes -- the session publishes
with a plain ``git push origin <branch>``, which the pre-push guard judges.

* ``merge <branch>`` -- ``git merge-tree --write-tree`` of the local integration branch and *branch*;
  refused on a conflict, naming the files. The message carries ``Merged-Branch: <branch>`` and any
  ``--audit`` lines; it passes through the repo's OWN ``commit-msg`` hook stage
  (:func:`lab_commons.dev.githooks.runner.run_stage`, the rows every commit runs) and the merge audit
  (:func:`lab_commons.dev.mergeaudit.judge`) -- the same functions, never a copy. Then ``commit-tree`` and
  ``update-ref`` with the old tip as compare-and-swap.
* ``promote <sha>`` -- fast-forward the LOCAL trunk ref to *sha*, an integration commit on origin whose
  every derived ``tests/<part>`` stands PASS at scope full (:func:`decide`, the same standing push
  admission reads). Never a merge onto the trunk.

A ref that is checked out in some worktree is refused: moving it under that tree would leave the tree
showing the reverse of the merge as local changes.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import lab_commons.launch as _door
from lab_commons.dev.checkout import worktrees
from lab_commons.dev.forge import fetch_origin
from lab_commons.dev.forgestatus import status_list
from lab_commons.dev.forgework import Client, ForgeCallFailed, client_for
from lab_commons.dev.githooks.runner import run_stage
from lab_commons.dev.githooks.table import hook_table_from
from lab_commons.dev.lanepolicy import Policy, policy_at
from lab_commons.dev.mergeaudit import TRAILER, MergeAuditError, judge
from lab_commons.dev.platformparts import standing
from lab_commons.dev.sessionbranch import MERGED_BRANCH
from lab_commons.dev.trialmerge import contains, rev
from lab_commons.hpc.declared import pyproject_at
from lab_commons.hpc.shell import FULL
from lab_commons.log import emit

__all__ = ['IntegrateRefused', 'Promotion', 'decide', 'main', 'merge', 'promote']

_GIT: Final = shutil.which('git') or 'git'
_CONFLICTED: Final = 1
#: The top-level files a commit-msg row may read its configuration from: the manifest and commitizen's own.
_MANIFESTS: Final = frozenset({'pyproject.toml', '.cz.toml', 'cz.toml', '.cz.json', 'cz.json', '.cz.yaml', 'cz.yaml'})


class IntegrateRefused(RuntimeError):
    """The merge or promotion was refused; the message names why and the remedy."""


@dataclass(frozen=True)
class Promotion:
    """What promote decided: ``promote``, ``current`` (nothing to do) or ``refused``, with why."""

    action: str
    sha: str
    reasons: tuple[str, ...] = ()


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return _door.run(
        [_GIT, '-C', str(root), *args], capture_output=True, text=True, encoding='utf-8', check=False, timeout=300
    )


def _unchecked_out(root: Path, branch: str) -> None:
    held = [path for path, name in worktrees(root) or () if name == branch]
    if held:
        msg = f'{branch} is checked out at {held[0]}; it needs no working tree -- switch that checkout off it'
        raise IntegrateRefused(msg)


def _move(root: Path, branch: str, new: str, old: str | None) -> None:
    done = _git(root, 'update-ref', '-m', f'integrate: {branch}', f'refs/heads/{branch}', new, old or '')
    if done.returncode != 0:
        msg = f'{branch} moved while it was being updated: {done.stderr.strip()}'
        raise IntegrateRefused(msg)


def merge(root: Path, branch: str, *, audit: Sequence[str] = ()) -> str:
    """Merge *branch* into the local integration branch with no working tree; the new tip (or the old, if merged).

    The declaration is read from COMMITS, never the working tree: the integration branch's name from
    *branch*'s tip (the commit arriving), then the whole policy from the MERGED tree -- the commit being made
    declares the policy it lands under -- which must name the same integration branch.
    """
    target = _policy(root, branch).integration
    _unchecked_out(root, target)
    if (_git(root, 'rev-parse', '-q', '--verify', 'MERGE_HEAD')).returncode == 0:
        msg = f'{root} is in the middle of a merge; finish or abort it first (its commit-msg rows would judge it)'
        raise IntegrateRefused(msg)
    tip, other = rev(root, f'refs/heads/{target}'), rev(root, branch)
    if tip is None or other is None:
        msg = f'cannot resolve {target if tip is None else branch} in {root}'
        raise IntegrateRefused(msg)
    if contains(root, tip, other):
        return tip
    tried = _git(root, 'merge-tree', '--write-tree', '--name-only', '--no-messages', tip, other)
    if tried.returncode == _CONFLICTED:
        files = ', '.join(line for line in tried.stdout.splitlines()[1:] if line.strip())
        msg = f'merging {branch} into {target} conflicts in: {files}. Resolve it on {branch} (merge {target} there)'
        raise IntegrateRefused(msg)
    if tried.returncode != 0:
        msg = f'git merge-tree failed: {tried.stderr.strip()}'
        raise IntegrateRefused(msg)
    tree = tried.stdout.splitlines()[0].strip()
    policy = _policy(root, tree)
    if policy.integration != target:
        msg = f'the merged tree declares integration {policy.integration!r}, but {branch} declares {target!r}'
        raise IntegrateRefused(msg)
    ledger = ''.join(f'{TRAILER}: {line}\n' for line in audit)
    text = f'chore(merge): {branch} into {target}\n\n{MERGED_BRANCH}: {branch}\n{ledger}'
    message = _checked_message(root, tree, text)
    try:
        problems = judge(root, [tip, other], tree, message, roots=policy.test_roots, label=f'{branch} into {target}')
    except MergeAuditError as error:
        problems = (str(error),)
    if problems:
        msg = 'merge-audit: ' + '; '.join(problems) + ' -- pass each as --audit "<KIND> <test> -- <reason>"'
        raise IntegrateRefused(msg)
    made = _git(root, 'commit-tree', tree, '-p', tip, '-p', other, '-m', message)
    if made.returncode != 0:
        msg = f'git commit-tree failed: {made.stderr.strip()}'
        raise IntegrateRefused(msg)
    sha = made.stdout.strip()
    _move(root, target, sha, tip)
    return sha


def _policy(root: Path, at: str) -> Policy:
    try:
        return policy_at(root, at)
    except (ValueError, subprocess.CalledProcessError) as exc:
        msg = f'the declaration at {at} cannot be read: {exc}'
        raise IntegrateRefused(msg) from exc


def _checked_message(root: Path, tree: str, message: str) -> str:
    """*message* after the commit-msg rows *tree* declares (which may append a trailer); refused when one fails.

    The rows run with *tree*'s top-level manifests as their working tree -- a scratch directory holding
    them, with ``GIT_DIR`` still the repository -- so every row, a tool's own config read (commitizen)
    included, judges the commit being made and never whatever the checkout happens to hold. The
    merge-audit row finds no merge in progress there and reads nothing; :func:`merge` audits *tree* itself
    through :func:`lab_commons.dev.mergeaudit.judge`, the same function.
    """
    rows = hook_table_from(pyproject_at(root, tree), f'{tree}:pyproject.toml').get('commit-msg', ())
    git_dir = _git(root, 'rev-parse', '--absolute-git-dir').stdout.strip()
    with tempfile.TemporaryDirectory() as scratch:
        work = Path(scratch) / 'tree'
        work.mkdir()
        for name in _git(root, 'ls-tree', '--name-only', tree).stdout.split():
            if name in _MANIFESTS:
                (work / name).write_text(_git(root, 'show', f'{tree}:{name}').stdout, encoding='utf-8')
        path = Path(scratch) / 'COMMIT_EDITMSG'
        path.write_text(message, encoding='utf-8')
        env = {'GIT_DIR': git_dir, 'GIT_WORK_TREE': str(work)}
        if run_stage('commit-msg', [str(path)], root=work, hooks=rows, env=env):
            msg = 'the commit-msg hook stage refused the merge message (its rows are printed above)'
            raise IntegrateRefused(msg)
        return path.read_text(encoding='utf-8')


def decide(root: Path, client: Client, policy: Policy, sha: str) -> Promotion:
    """Whether the local trunk may fast-forward to *sha*; pure of any write. Reads origin's integration branch."""
    found = rev(root, sha)
    trunk = rev(root, f'refs/heads/{policy.trunk}') or rev(root, f'origin/{policy.trunk}')
    published = rev(root, f'origin/{policy.integration}')
    if found is None or published is None or not contains(root, published, found):
        return Promotion('refused', sha, (f'{sha} is not a commit of origin/{policy.integration}',))
    if trunk == found:
        return Promotion('current', found)
    if trunk is not None and not contains(root, found, trunk):
        why = f'{policy.trunk} ({trunk[:12]}) is not an ancestor of {found[:12]}: it cannot fast-forward'
        return Promotion('refused', found, (why,))
    parts = standing(status_list(client, found), head=found, scope=FULL)
    if parts.result != 'PASS':
        return Promotion(
            'refused', found, (f'the parts of {found[:12]} stand {parts.result or "unsettled"}', *parts.problems)
        )
    return Promotion('promote', found)


def promote(root: Path, client: Client, sha: str) -> Promotion:
    """:func:`decide`, then the local fast-forward of the trunk ref when it says ``promote``.

    The declaration is the one *sha* -- the commit being promoted -- carries, never the working tree's.
    """
    policy = _policy(root, sha)
    _unchecked_out(root, policy.trunk)
    found = decide(root, client, policy, sha)
    if found.action == 'promote':
        _move(root, policy.trunk, found.sha, rev(root, f'refs/heads/{policy.trunk}'))
    return found


def main(
    argv: Sequence[str] | None = None,
    *,
    cwd: Path | None = None,
    client: Client | None = None,
    fetch: Callable[[Path], None] = fetch_origin,
) -> int:
    """``merge <branch> [--audit L]...`` or ``promote <sha>``: exit 0 done, 2 refused, 1 on a failure."""
    parser = argparse.ArgumentParser(prog='python -m lab_commons.dev.integrate', description=__doc__.splitlines()[0])
    verbs = parser.add_subparsers(dest='verb', required=True)
    merging = verbs.add_parser('merge')
    merging.add_argument('branch')
    merging.add_argument('--audit', action='append', default=[], help='<KIND> <test> -- <reason>')
    verbs.add_parser('promote').add_argument('sha')
    args = parser.parse_args(argv)
    root = Path.cwd() if cwd is None else cwd
    try:
        if args.verb == 'merge':
            sha = merge(root, args.branch, audit=args.audit)
            target = _policy(root, sha).integration
            emit(f'[integrate] {target} at {sha}; publish it: git push origin {target}')
            return 0
        fetch(root)
        found = promote(root, client or client_for(root), args.sha)
        trunk = _policy(root, args.sha).trunk
    except IntegrateRefused as refused:
        emit(f'[integrate] REFUSED: {refused}', err=True)
        return 2
    except (ForgeCallFailed, OSError) as failed:
        emit(f'[integrate] {failed}', err=True)
        return 1
    if found.action == 'refused':
        emit(f'[integrate] REFUSED: {trunk} stays where it is.', err=True)
        for reason in found.reasons:
            emit(f'[integrate]   {reason}', err=True)
        return 2
    verb = 'already at' if found.action == 'current' else 'fast-forwarded to'
    emit(f'[integrate] {trunk} {verb} {found.sha}; publish it: git push origin {trunk}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
