"""HOLD: keep a PR out of the merge tick on every forge, whatever the caller's permissions.

``forge pr draft <N>`` is the stronger move (a draft runs nothing, D53), but GitHub refuses it to a caller without
the right to convert a PR (2026-11-17: "<owner> does not have permission to convert the pull request to draft"), and
a green PR it could not hold was merged by the tick. A HOLD is the :data:`HOLD_LABEL` label on the PR, set and
cleared through the forge door (:meth:`~dev_lab.dev.forgework.Client.call`, journaled and retried): a label write
needs only triage rights. Its parts and review still run; only the merge waits.

The merge decision honours it: :func:`dev_lab.dev.forgemergeready.ready` posts ``tests/merge-ready`` ``pending``
:data:`HELD` and :func:`dev_lab.dev.forgemerge.judged` names it as missing, so nothing merges a held head and the
reason names the release door. ``python -m dev_lab.dev.forge pr hold <N>`` / ``pr release <N>`` (:func:`main`).
"""

from __future__ import annotations

import argparse
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Final

from lab_commons.log import emit

from dev_lab.dev.forgefailure import ForgeCallFailed
from dev_lab.dev.forgelabels import add_label, ensure_labels, remove_label
from dev_lab.dev.forgework import client_for

if TYPE_CHECKING:
    from dev_lab.dev.forgework import Client, PullRequest

__all__ = ['HELD', 'HOLD_DOOR', 'HOLD_LABEL', 'RELEASE_DOOR', 'hold', 'is_held', 'main', 'release']

#: The label that holds a PR from the merge tick.
HOLD_LABEL: Final = 'hold'
#: The door that holds PR ``{n}``, and the one that releases it.
HOLD_DOOR: Final = 'python -m dev_lab.dev.forge pr hold {n}'
RELEASE_DOOR: Final = 'python -m dev_lab.dev.forge pr release {n}'
#: What a held head's ``tests/merge-ready`` says (``pending``), and what the merge decision names as missing.
HELD: Final = f'held (label `{HOLD_LABEL}`): release with `{RELEASE_DOOR}` -- nothing merges a held PR'


def is_held(pull: PullRequest) -> bool:
    """Whether *pull* carries :data:`HOLD_LABEL`."""
    return HOLD_LABEL in pull.labels


def hold(client: Client, number: int) -> PullRequest:
    """Put :data:`HOLD_LABEL` on PR *number* (created in the repository first when missing); idempotent."""
    if not is_held(client.pr_view(number)):
        ensure_labels(client, [HOLD_LABEL])
        add_label(client, number, HOLD_LABEL)
    return client.pr_view(number)


def release(client: Client, number: int) -> PullRequest:
    """Take :data:`HOLD_LABEL` off PR *number*; idempotent."""
    if is_held(client.pr_view(number)):
        remove_label(client, number, HOLD_LABEL)
    return client.pr_view(number)


def main(argv: Sequence[str], *, cwd: Path | None = None, client: Client | None = None) -> int:
    """``forge pr hold <N>`` / ``forge pr release <N>``: exit 0 moved, 1 refused by the forge."""
    parser = argparse.ArgumentParser(prog='dev_lab.dev.forge pr', description=__doc__.splitlines()[0])
    parser.add_argument('verb', choices=('hold', 'release'))
    parser.add_argument('number', type=int)
    args = parser.parse_args(list(argv))
    try:
        client = client or client_for(Path.cwd() if cwd is None else cwd)
        pull = (hold if args.verb == 'hold' else release)(client, args.number)
    except (ForgeCallFailed, LookupError, ValueError, OSError, subprocess.SubprocessError) as refused:
        emit(f'#{args.number} is unchanged: pr {args.verb} refused: {" ".join(str(refused).split())}')
        return 1
    if is_held(pull):
        emit(f'#{pull.number} is HELD: nothing merges it until `{RELEASE_DOOR.format(n=pull.number)}`')
    else:
        emit(f'#{pull.number} is released: the merge tick judges it again')
    return 0
