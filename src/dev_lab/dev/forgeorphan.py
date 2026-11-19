"""AN ORPHANED PR GOES TO THE INTEGRATOR (MERGE-OR-DELETE executed; user approval 2026-11-15).

Sessions open PRs and end; a PR left red, conflicting or stale then sits with nobody to move it. The serve
tick's integration step (:func:`take`) hands such a PR to the integrator, on the forge, in ONE place:

* ORPHANED (:func:`orphaned`) -- an open PR into integration whose head has not moved for :data:`ORPHAN_AGE`
  and none of whose owning sessions is live. The owners are the ``Lab-Session`` trailers its commits carry
  (:func:`dev_lab.dev.labsession.sessions`, the one ownership record); a session is live when its
  ``forge watch --session`` runs (:func:`dev_lab.dev.sessionprs.watching`). A new head, or a live owner, is
  never taken.
* TAKEN -- the PR gets the label :data:`LABEL` and one comment naming why, carrying the head it was taken at in a
  hidden marker. The label IS the idempotency key: a labelled PR is never commented again, and a second host's
  tick writes nothing.
* HANDED BACK -- liveness is per machine, so a session working elsewhere may look dead here. When a labelled
  PR's head moves past the head it was taken at, its owner pushed: the tick removes the label and says so once.
* LISTED -- every open labelled PR is an ``integration`` alarm on the host card each tick (``forge queue``), and
  ``python -m dev_lab.dev.forgeorphan`` (:func:`main`) prints the integrator's orphaned PRs. The integrator
  merges or closes it; removing the label hands it back.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Final

from lab_commons.log import emit

from dev_lab.dev import forgedraft, sessionprs
from dev_lab.dev.forgealarm import INTEGRATION, Alarm, pull_context
from dev_lab.dev.forgeclient import client_for
from dev_lab.dev.forgefailure import ForgeCallFailed
from dev_lab.dev.forgelabels import add_label, ensure_labels, remove_label
from dev_lab.dev.forgepulls import comment_list, pr_list
from dev_lab.dev.labsession import sessions
from dev_lab.dev.lanepolicy import load_policy

if TYPE_CHECKING:
    from dev_lab.dev.forgework import Client, PullRequest

__all__ = [
    'LABEL', 'ORPHAN_AGE', 'PUSH_RELEASES', 'alarms', 'labels_of', 'main', 'orphaned', 'release', 'take', 'taken',
]  # fmt: skip

#: How long an open PR's head may stand still, with no live owner, before the integrator takes it.
ORPHAN_AGE: Final = timedelta(hours=24)
#: The label that hands a PR to the integrator: the one place the integrator reads.
LABEL: Final = 'owner:integrator'
#: What the take comment promises its owner: the one way back.
PUSH_RELEASES: Final = 'push to this branch and the label comes off'
#: The hidden marker a take comment records the taken head in.
_TAKEN_AT: Final = re.compile(r'<!-- orphan-taken-at ([0-9a-f]{7,64}) -->')


def labels_of(client: Client, number: int) -> tuple[str, ...]:
    """The label names on PR *number*, as the forge holds them now."""
    return tuple(str(one['name']) for one in client.call('GET', f'{client.repo}/issues/{number}/labels') or ())


def _live(owners: Sequence[str]) -> bool:
    return any(sessionprs.watching(one) for one in owners)


def orphaned(*, age: timedelta, owners: Sequence[str], live: Callable[[Sequence[str]], bool]) -> bool:
    """Whether a PR whose head is *age* old and carries *owners* is the integrator's: still, and nobody live."""
    return age >= ORPHAN_AGE and not live(owners)


def _why(pull: PullRequest, owners: Sequence[str], age: timedelta) -> str:
    who = ', '.join(owners) or 'no Lab-Session trailer'
    hours = int(age.total_seconds() // 3600)
    return (
        f'The integrator takes #{pull.number} `{pull.head}` (label `{LABEL}`): its head `{pull.head_sha[:12]}` has '
        f'not moved for {hours} h (bound {ORPHAN_AGE}) and no owning session is live [{who}]. MERGE-OR-DELETE: '
        f'the integrator merges or closes it. Its owner: {PUSH_RELEASES}.'
        f'\n<!-- orphan-taken-at {pull.head_sha} -->'
    )


def take(
    root: Path,
    client: Client,
    base: str,
    *,
    now: datetime,
    live: Callable[[Sequence[str]], bool] = _live,
) -> list[str]:
    """Label and comment, once, every orphaned open PR into *base*; one line per PR taken."""
    lines = []
    for pull in pr_list(client):
        if pull.base != base or not pull.head_sha or LABEL in labels_of(client, pull.number):
            continue
        age = now - forgedraft.pushed(client, pull.head_sha)
        owners = sorted(sessions(root, f'origin/{base}', pull.head_sha))
        if not orphaned(age=age, owners=owners, live=live):
            continue
        ensure_labels(client, [LABEL])
        add_label(client, pull.number, LABEL)
        client.issue_comment(pull.number, _why(pull, owners, age))
        lines.append(f'#{pull.number} {pull.head} taken by the integrator: still {int(age.total_seconds() // 3600)} h')
    return lines


def _taken_at(client: Client, number: int) -> str | None:
    """The head the newest take comment on PR *number* recorded; ``None`` when it has none."""
    found = [m[1] for c in comment_list(client, number) if (m := _TAKEN_AT.search(c.body))]
    return found[-1] if found else None


def release(client: Client, base: str) -> list[str]:
    """Hand back every labelled PR into *base* whose head moved past the head it was taken at; one line each."""
    lines = []
    for pull in pr_list(client):
        if pull.base != base or LABEL not in labels_of(client, pull.number):
            continue
        at = _taken_at(client, pull.number)
        if at is None or at == pull.head_sha:
            continue
        remove_label(client, pull.number, LABEL)
        client.issue_comment(
            pull.number,
            f'Handed back: the head moved from `{at[:12]}` to `{pull.head_sha[:12]}` after the integrator took it, '
            f'so its owner is working on it; label `{LABEL}` removed.',
        )
        lines.append(f'#{pull.number} {pull.head} handed back: its head moved')
    return lines


def taken(client: Client, base: str) -> list[PullRequest]:
    """Every open PR into *base* the integrator holds (labelled :data:`LABEL`)."""
    return [pull for pull in pr_list(client) if pull.base == base and LABEL in labels_of(client, pull.number)]


def alarms(root: Path, client: Client, base: str, repo: str, *, now: datetime) -> list[Alarm]:
    """Hand back the moved (:func:`release`), take the orphans (:func:`take`), then alarm per PR held."""
    release(client, base)
    take(root, client, base, now=now)
    return [
        Alarm(
            INTEGRATION,
            repo,
            f'the integrator takes #{pull.number} {pull.head}: orphaned',
            f'#{pull.number} ({pull.title}) by {pull.author} is labelled `{LABEL}`: merge it or close it.',
            context=pull_context(pull),
        )
        for pull in taken(client, base)
    ]


def main(argv: Sequence[str] | None = None, *, cwd: Path | None = None, client: Client | None = None) -> int:
    """List the PRs the integrator holds; exit 1 when the forge cannot answer."""
    argparse.ArgumentParser(prog='python -m dev_lab.dev.forgeorphan', description=__doc__.splitlines()[0]).parse_args(
        list(sys.argv[1:] if argv is None else argv)
    )
    root = Path.cwd() if cwd is None else cwd
    try:
        client = client or client_for(root)
        found = taken(client, load_policy(root).integration)
    except (ForgeCallFailed, OSError, ValueError) as failed:
        emit(f'[orphan] the forge did not answer: {failed}', err=True)
        return 1
    for pull in found:
        emit(f'[orphan] #{pull.number} {pull.head} {pull.head_sha[:12]} -- {pull.title} ({pull.url})')
    emit(f'[orphan] {len(found)} PR(s) held by the integrator (label {LABEL}) at {datetime.now(UTC):%Y-%m-%d %H:%M}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
