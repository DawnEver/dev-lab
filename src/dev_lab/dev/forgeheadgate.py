"""The forge's judgement of an open PR head, as commit statuses on that head; the merge requires the GATES.

User ruling 2026-10-24 (toolchain plan P3): a judgement no one read locally is said where the author reads it -- a
status on the PR head, ``failure`` naming the exact command that fixes it. User ruling 2026-11-07 (systemic): A FAMILY
CHECK NEVER DEPENDS ON A CONSUMER'S LOCAL GIT HOOK BEING CURRENT -- a stale or missing pre-push shim silently disarmed
the push rows in 4 of 5 consumers. So each push row that can be judged of a PR head is also a status here, from THE
SAME JUDGE the row calls (one judge, two callers), and the merge requires it (:data:`GATES`, :func:`gates_wait`, read
by :func:`dev_lab.dev.forgemerge.decide`); the hook stays as early feedback only:

* :data:`SESSION_BRANCH_CONTEXT` -- :func:`dev_lab.dev.sessionbranch.head_refusals`: the head is published as
  itself and admitted by the branch set its own commit declares (P2, P6). A GATE.
* :data:`PR_CURRENT_CONTEXT` -- :func:`dev_lab.dev.prcurrent.head_refusals`: a ``pr/`` head holds
  ``origin/<integration>``'s tip and a lock no floated sibling has moved past. A GATE.
* :data:`LOCK_CONTEXT` -- the head's ``uv.lock`` moves a resolution its BASE does not
  (:func:`dev_lab.dev.lockcheck.stale` on the head, then on its merge-base with ``origin/<integration>``, each in a
  detached worktree); the remedy is the one dependency door, :data:`LOCK_REMEDY`. A resolution that cannot run is
  ``error`` with its diagnosis, never a pass. A PR NEVER CHASES THE LOCK (user ruling 2026-10-28): a move the base
  lags too is integration's, carried by the forge's relock pull request (:mod:`dev_lab.dev.relock`).
* :data:`LAG_CONTEXT` -- the head's ``uv.lock`` pins a floated sibling more than :data:`LAG_LIMIT` commits behind
  that sibling's line (:func:`dev_lab.dev.locklag.floating_lag`): an ALARM that the relock is not carrying, never a
  gate -- ``pr-current`` already refuses any floating move on a ``pr/`` head.

The other two push rows are not head statuses, by what they judge: ``merge-resolution``
(:func:`dev_lab.dev.mergeresolution.unresolved`) is already a condition of the merge decision itself, on the same
judge; ``landed-pr`` judges new commits on a branch whose PR is CLOSED, so no open PR head exists to carry a status.

ONCE PER HEAD SHA, FOR A VERDICT: a head whose context already reads ``success`` or ``failure`` is not judged
again (a resolution is minutes of network), so a new head earns a new judgement -- save the :data:`VOLATILE`
contexts, whose verdict reads a tip that moves while the head does not (integration's, a sibling's): those are
judged every time and posted only when the verdict changed. An ``error`` or ``pending`` is not a verdict and is
judged again. Two producers, one :func:`judge`: Gitea's ``forge serve`` integration step on every open PR into
integration (:func:`dev_lab.dev.forgeintegration.tick`, oldest PR first, starting no head once :data:`TICK_BUDGET_S`
is spent), and GitHub's ``head-gates`` workflow job (``forge headgate run --pr N``, :func:`main`), which the
``merge-ready`` job needs.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Final

import lab_commons.launch as _door
from lab_commons.log import emit

from dev_lab.dev import prcurrent, sessionbranch
from dev_lab.dev.forge import _GIT, _GIT_TIMEOUT_S
from dev_lab.dev.forgefailure import ForgeCallFailed
from dev_lab.dev.forgestatus import DESCRIPTION_LIMIT, status_list, status_post
from dev_lab.dev.forgework import client_for
from dev_lab.dev.lanepolicy import load_policy
from dev_lab.dev.lockcheck import DOOR, LOCK, RESOLVE_TIMEOUT_S, UNRESOLVED, stale
from dev_lab.dev.locklag import floating_lag
from dev_lab.dev.relock import detached_worktree

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from dev_lab.dev.forgeintegration import Child
    from dev_lab.dev.forgestatus import CommitStatus
    from dev_lab.dev.forgework import Client

__all__ = [
    'GATES',
    'LAG_CONTEXT',
    'LAG_LIMIT',
    'LOCK_CONTEXT',
    'LOCK_REMEDY',
    'PR_CURRENT_CONTEXT',
    'SESSION_BRANCH_CONTEXT',
    'TERMINAL',
    'TICK_BUDGET_S',
    'VOLATILE',
    'gates_wait',
    'judge',
    'judge_heads',
    'lag_verdict',
    'lock_verdict',
    'main',
    'merge_base',
    'refused_verdict',
    'run_pull',
]

LOCK_CONTEXT: Final = 'lock/fresh'
LAG_CONTEXT: Final = 'lock/lag'
#: The push rows' own ids: the status a row's judge posts is named as the row is.
SESSION_BRANCH_CONTEXT: Final = sessionbranch.HOOK_ID
PR_CURRENT_CONTEXT: Final = prcurrent.HOOK_ID
#: The statuses the merge requires ``success`` (:func:`gates_wait`).
GATES: Final = (SESSION_BRANCH_CONTEXT, PR_CURRENT_CONTEXT)
#: The contexts judged on every pass, posted only on a change: their verdict reads a tip the head does not hold.
VOLATILE: Final = frozenset({PR_CURRENT_CONTEXT, LAG_CONTEXT})
#: Commits a consumer's lock may pin a floated sibling behind that sibling's line before :data:`LAG_CONTEXT` fails.
#: The relock pull request follows every sibling push within a serve tick or two, so a carried lock lags a handful
#: of commits at most; twenty is about a working day of sibling merges -- past it, the relock is not carrying.
LAG_LIMIT: Final = 20
#: The fix a stale lock names, first, so the 140-character status keeps it whole.
LOCK_REMEDY: Final = f'run `{DOOR}`, then commit {LOCK}'
#: The states that are a verdict; any other (``error``, ``pending``) is judged again.
TERMINAL: Final = frozenset({'success', 'failure'})
#: Seconds of a serve tick the gate may START heads within: one cold resolution's own ceiling.
TICK_BUDGET_S: Final = RESOLVE_TIMEOUT_S

Verdict = tuple[str, str]


def lock_verdict(tree: Path, base: Path, *, read: Callable[[Path], tuple[str, ...]] = stale) -> Verdict:
    """``(state, description)`` for the lock in *tree* against its *base* tree: failure on a move *base* lacks.

    *base* is resolved only when *tree* is not at the newest: the moves both share are integration's to carry.
    """
    why = read(tree)
    if not why:
        return 'success', f'{LOCK} is the newest resolution'
    if why[0].startswith(UNRESOLVED):
        return 'error', why[0]
    inherited = read(base)
    if inherited and inherited[0].startswith(UNRESOLVED):
        return 'error', f'the base: {inherited[0]}'
    own = [one for one in why if one not in inherited]
    if not own:
        return 'success', f'{LOCK} lags only what its base lags; the forge relock carries it'
    moved = '; '.join(one.split(': ', 1)[-1] for one in own)
    return 'failure', f'stale {LOCK}: {LOCK_REMEDY} ({moved})'


def refused_verdict(found: Sequence[str], holds: str) -> Verdict:
    """``(state, description)`` of a push row's refusals: none is ``success`` *holds*, else ``failure`` naming them."""
    return ('failure', '; '.join(found)) if found else ('success', holds)


def lag_verdict(
    root: Path, head: str, *, limit: int = LAG_LIMIT, lag: Callable[..., tuple[str, ...]] = floating_lag
) -> Verdict:
    """``(state, description)`` for *head*'s lock: ``failure`` past *limit* commits behind a floated sibling's line."""
    shown = _git(root, 'show', f'{head}:{LOCK}')
    if shown.returncode != 0:
        return 'success', f'no {LOCK}: nothing floats'
    found = lag(shown.stdout, limit)
    if any(one.startswith(UNRESOLVED) for one in found):
        return 'error', '; '.join(found)
    return refused_verdict(found, f'{LOCK} pins every floated sibling within {limit} commits of its line')


def _git(root: Path, *argv: str) -> subprocess.CompletedProcess[str]:
    return _door.run(
        [_GIT, '-C', str(root), *argv],
        capture_output=True, text=True, encoding='utf-8', errors='replace', check=False, timeout=_GIT_TIMEOUT_S,
    )  # fmt: skip


def merge_base(root: Path, head: str, integration: str) -> str:
    """The merge-base of *head* with ``origin/<integration>`` in *root*; RAISES :class:`OSError` on none."""
    done = _git(root, 'merge-base', head, f'refs/remotes/origin/{integration}')
    if done.returncode != 0:
        msg = f'no merge-base of {head[:12]} with origin/{integration}: {done.stderr.strip()}'
        raise OSError(msg)
    return done.stdout.strip()


def _lock_fresh(root: Path, head: str, integration: str, read: Callable[[Path], tuple[str, ...]]) -> Verdict:
    try:
        base = merge_base(root, head, integration)
        with detached_worktree(root, head) as tree, detached_worktree(root, base) as based:
            return lock_verdict(tree, based, read=read)
    except OSError as why:
        return 'error', f'the head could not be checked out to resolve: {why}'


def judge(
    root: Path,
    client: Client,
    head: str,
    branch: str,
    *,
    integration: str,
    read: Callable[[Path], tuple[str, ...]] = stale,
) -> list[str]:
    """Post each context *head* needs judged (:data:`VOLATILE`: whenever its verdict changed); one line per post."""
    latest = {status.context: status for status in status_list(client, head)}
    rows: tuple[tuple[str, Callable[[], Verdict]], ...] = (
        (
            SESSION_BRANCH_CONTEXT,
            lambda: refused_verdict(sessionbranch.head_refusals(root, head, branch), f'{branch} is declared'),
        ),
        (
            PR_CURRENT_CONTEXT,
            lambda: refused_verdict(
                prcurrent.head_refusals(root, head, branch, integration),
                f'{branch} holds origin/{integration} and a current lock'
                if prcurrent.judged(branch)
                else f'{branch} is not a judged pr/ head',
            ),
        ),
        (LOCK_CONTEXT, lambda: _lock_fresh(root, head, integration, read)),
        (LAG_CONTEXT, lambda: lag_verdict(root, head)),
    )
    lines = []
    for context, verdict in rows:
        held = latest.get(context)
        if held is not None and held.state in TERMINAL and context not in VOLATILE:
            continue
        state, text = verdict()
        if (
            context in VOLATILE
            and held is not None
            and (held.state, held.description) == (state, text[:DESCRIPTION_LIMIT])
        ):
            continue
        status_post(client, head, context=context, state=state, description=text)
        lines.append(f'{context}: {state}')
    return lines


def gates_wait(statuses: Sequence[CommitStatus]) -> str | None:
    """Why the head's :data:`GATES` do not all stand ``success``, or ``None``: what the merge decision reads."""
    latest = {status.context: status for status in statuses}
    waits = []
    for context in GATES:
        held = latest.get(context)
        if held is None:
            waits.append(f'{context} is not yet judged')
        elif held.state != 'success':
            waits.append(f'{context} is {held.state}: {held.description}')
    return '; '.join(waits) or None


def judge_heads(
    root: Path,
    origin: Client,
    children: Sequence[Child],
    gate: Callable[..., list[str]],
    monotonic: Callable[[], float],
    *,
    integration: str,
) -> list[str]:
    """*gate* on each child's head, oldest PR first, starting none once :data:`TICK_BUDGET_S` is spent.

    A gate that raises is one line for its head; the next head is still judged.
    """
    lines: list[str] = []
    start = monotonic()
    for child in sorted(children, key=lambda c: c.pr or 0):
        where = f'{child.branch} #{child.pr}'
        if monotonic() - start >= TICK_BUDGET_S:
            lines.append(f'{where}: gate waits for the next tick (budget {TICK_BUDGET_S:.0f} s spent)')
            continue
        try:
            lines += [
                f'{where}: {line}' for line in gate(root, origin, child.head, child.branch, integration=integration)
            ]
        except Exception as why:  # noqa: BLE001 -- one head's defect must not end the tick for the others
            lines.append(f'{where}: gate raised {type(why).__name__}: {why}')
    return lines


def run_pull(root: Path, client: Client, number: int, *, gate: Callable[..., list[str]] = judge) -> str:
    """:func:`judge` on PR *number*'s head: what GitHub's ``head-gates`` job runs for its event; the line said."""
    into = load_policy(root).integration
    pull = client.pr_view(number)
    if pull.base != into or not pull.head_sha:
        return f'#{number}: not judged -- only a PR into {into} is'
    lines = gate(root, client, pull.head_sha, pull.head, integration=into)
    return f'#{number} {pull.head_sha[:12]}: {"; ".join(lines) or "every head gate already judged"}'


def main(argv: Sequence[str] | None = None, *, cwd: Path | None = None, client: Client | None = None) -> int:
    """``forge headgate run --pr <N>``: post PR *N*'s head statuses. Exit 0 done, 2 refused."""
    parser = argparse.ArgumentParser(prog='dev_lab.dev.forge headgate', description=__doc__.splitlines()[0])
    verbs = parser.add_subparsers(dest='verb', required=True)
    running = verbs.add_parser('run', help="judge one PR's head: what a GitHub workflow job runs for its event")
    running.add_argument('--pr', type=int, required=True)
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    root = Path.cwd() if cwd is None else cwd
    try:
        said = run_pull(root, client or client_for(root), args.pr)
    except (ForgeCallFailed, OSError, ValueError, subprocess.CalledProcessError) as failed:
        emit(f'[headgate] refused: {failed}', err=True)
        return 2
    emit(f'[headgate] {said}')
    return 0
