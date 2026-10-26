"""PROMOTING THE TRUNK NEEDS NO WORKING TREE: fast-forward the trunk ref to an integration commit.

The trunk is one more session branch (:mod:`dev_lab.dev.sessionbranch`): what makes it legitimate is that
it lands by fast-forward on an integration commit whose every part stands PASS, not which directory it was
moved in. So the verb checks nothing out and pushes nothing -- the session publishes with a plain
``git push origin <branch>``, which the pre-push guard judges.

* ``promote <sha>`` -- fast-forward the LOCAL trunk ref to *sha*, an integration commit on origin whose
  every derived ``tests/<part>`` stands PASS at scope full (:func:`decide`, the same standing push
  admission reads). Never a merge onto the trunk.

The integration branch is moved by the FORGE alone, server side, when it merges a green pull request
(:mod:`dev_lab.dev.forgemerge`). A client has no verb for that, and this one is not a bypass: a ref that
is checked out in some worktree is refused, and a trunk that cannot fast-forward is refused rather than merged.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import lab_commons.launch as _door
from lab_commons.hpc.shell import FULL
from lab_commons.log import emit
from lab_commons.outcomes import Conclusion

from dev_lab.dev import metrics
from dev_lab.dev.checkout import worktrees
from dev_lab.dev.forge import fetch_origin
from dev_lab.dev.forgestatus import status_list
from dev_lab.dev.forgework import Client, ForgeCallFailed, client_for
from dev_lab.dev.lanepolicy import Policy, policy_at
from dev_lab.dev.platformparts import standing
from dev_lab.dev.trialmerge import contains, rev

__all__ = ['IntegrateRefused', 'Promotion', 'decide', 'main', 'promote']

_GIT: Final = shutil.which('git') or 'git'

#: The refusal's id in the metrics log (:mod:`dev_lab.dev.metrics`).
_RULE: Final = 'integrate-promote'


class IntegrateRefused(RuntimeError):
    """The promotion was refused; the message names why and the remedy."""


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


def _policy(root: Path, at: str) -> Policy:
    try:
        return policy_at(root, at)
    except (ValueError, subprocess.CalledProcessError) as exc:
        msg = f'the declaration at {at} cannot be read: {exc}'
        raise IntegrateRefused(msg) from exc


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
    if parts.result is not Conclusion.PASS:
        return Promotion('refused', found, (f'the parts of {found[:12]} stand {parts.result.name}', *parts.problems))
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


def _log(root: Path, kind: str, sha: str) -> None:
    """The metrics line of one promotion (:mod:`dev_lab.dev.metrics`): a hand action, or its refusal."""
    named = {'rule': _RULE, 'reason': 'integrate'} if kind == metrics.REFUSAL else {'lab_action': 'integrate promote'}
    metrics.record(kind, root=root, repo=metrics.repo_of(root), vcs_ref_head_revision=sha, **named)


def main(
    argv: Sequence[str] | None = None,
    *,
    cwd: Path | None = None,
    client: Client | None = None,
    fetch: Callable[[Path], None] = fetch_origin,
) -> int:
    """``promote <sha>``: exit 0 done, 2 refused, 1 on a failure."""
    parser = argparse.ArgumentParser(prog='python -m dev_lab.dev.integrate', description=__doc__.splitlines()[0])
    verbs = parser.add_subparsers(dest='verb', required=True)
    verbs.add_parser('promote').add_argument('sha')
    args = parser.parse_args(argv)
    root = Path.cwd() if cwd is None else cwd
    try:
        fetch(root)
        found = promote(root, client or client_for(root), args.sha)
        trunk = _policy(root, args.sha).trunk
    except IntegrateRefused as refused:
        _log(root, metrics.REFUSAL, args.sha)
        emit(f'[integrate] REFUSED: {refused}', err=True)
        return 2
    except (ForgeCallFailed, OSError) as failed:
        emit(f'[integrate] {failed}', err=True)
        return 1
    if found.action == 'refused':
        _log(root, metrics.REFUSAL, args.sha)
        emit(f'[integrate] REFUSED: {trunk} stays where it is.', err=True)
        for reason in found.reasons:
            emit(f'[integrate]   {reason}', err=True)
        return 2
    _log(root, metrics.HAND_ACTION, args.sha)
    verb = 'already at' if found.action == 'current' else 'fast-forwarded to'
    emit(f'[integrate] {trunk} {verb} {found.sha}; publish it: git push origin {trunk}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
