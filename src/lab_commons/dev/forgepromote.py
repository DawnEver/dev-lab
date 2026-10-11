"""``forge promote``: move the trunk by FAST-FORWARD to the integration tip -- and only when it is fully green.

The trunk is the stable branch. It has exactly one way to move: to an integration commit whose every
required ``tests/<platform>`` part stands PASS at scope ``full`` -- the SAME reading push admission
makes for the trunk (:func:`lab_commons.dev.platformparts.standing`), so the door that moves it and
the hook that admits the push cannot disagree. No merge commit ever lands on the trunk: when the trunk
is not an ancestor of the integration tip, the move is refused rather than reconciled.

FETCHED FIRST, through the retry wrapper; the push is a plain (never forced) ``git push origin
<sha>:refs/heads/<trunk>``, which git itself refuses unless it fast-forwards. No branch is checked out.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from lab_commons.dev.forge import _GIT, fetch_origin
from lab_commons.dev.forgestatus import status_list
from lab_commons.dev.forgework import Client, ForgeCallFailed, client_for
from lab_commons.dev.lanepolicy import Policy, load_policy
from lab_commons.dev.netverb import run_network_verb
from lab_commons.dev.platformparts import standing
from lab_commons.dev.trialmerge import contains, rev
from lab_commons.hpc.shell import FULL
from lab_commons.log import emit

__all__ = ['Promotion', 'decide', 'main', 'promote']

_ORIGIN: Final = 'origin/'


@dataclass(frozen=True)
class Promotion:
    """What promote decided: ``promote``, ``current`` (nothing to do) or ``refused``, with why."""

    action: str
    sha: str
    reasons: tuple[str, ...] = ()


def decide(root: Path, client: Client, policy: Policy) -> Promotion:
    """Read the integration tip's parts and the trunk's ancestry; pure of any write."""
    tip = rev(root, _ORIGIN + policy.integration)
    trunk = rev(root, _ORIGIN + policy.trunk)
    if tip is None:
        return Promotion('refused', '', (f'origin has no {policy.integration} branch',))
    if trunk == tip:
        return Promotion('current', tip)
    if trunk is not None and not contains(root, tip, trunk):
        why = f'{policy.trunk} ({trunk[:12]}) is not an ancestor of {policy.integration}: it cannot fast-forward'
        return Promotion('refused', tip, (why, f'merge {policy.trunk} into {policy.integration} first'))
    found = standing(status_list(client, tip), head=tip, scope=FULL)
    if found.result != 'PASS':
        return Promotion(
            'refused', tip, (f'the parts of {tip[:12]} stand {found.result or "unsettled"}', *found.problems)
        )
    return Promotion('promote', tip)


def promote(root: Path, client: Client, policy: Policy) -> Promotion:
    """:func:`decide`, then the fast-forward push when it says ``promote``; a failed push raises."""
    found = decide(root, client, policy)
    if found.action == 'promote':
        report = run_network_verb(
            [_GIT, 'push', 'origin', f'{found.sha}:refs/heads/{policy.trunk}'], cwd=root, timeout=300
        )
        if not report.ok:
            raise OSError(report.remedy)
    return found


def main(
    argv: Sequence[str] | None = None,
    *,
    cwd: Path | None = None,
    client: Client | None = None,
    fetch: Callable[[Path], None] = fetch_origin,
) -> int:
    """``forge promote``: exit 0 promoted or already current, 2 refused (missing parts named), 1 on a failure."""
    argparse.ArgumentParser(prog='lab_commons.dev.forge promote', description=__doc__.splitlines()[0]).parse_args(
        list(sys.argv[1:] if argv is None else argv)
    )
    root = Path.cwd() if cwd is None else cwd
    policy = load_policy(root)
    try:
        fetch(root)
        found = promote(root, client or client_for(root), policy)
    except ForgeCallFailed as failed:
        emit(f'[promote] {failed}', err=True)
        return 1
    except OSError as exc:
        emit(f'[promote] {exc}', err=True)
        return 1
    if found.action == 'refused':
        emit(f'[promote] REFUSED: {policy.trunk} stays where it is.', err=True)
        for reason in found.reasons:
            emit(f'[promote]   {reason}', err=True)
        return 2
    verb = 'already at' if found.action == 'current' else 'fast-forwarded to'
    emit(f'[promote] {policy.trunk} {verb} {found.sha}')
    return 0
