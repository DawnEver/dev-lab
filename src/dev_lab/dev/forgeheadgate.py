"""The forge's judgement of an open PR head's LOCK FRESHNESS and BRANCH SET, as two commit statuses on that head.

User ruling 2026-10-24 (toolchain plan P3): neither is read at a local push any more, so the forge says each one
where the author reads it -- a status on the PR head, ``failure`` naming the exact command that fixes it:

* :data:`LOCK_CONTEXT` -- the head's ``uv.lock`` is not the newest resolution (:func:`dev_lab.dev.lockcheck.stale`,
  resolved in a detached worktree of the head); the remedy is the one dependency door, :data:`LOCK_REMEDY`.
  A resolution that cannot run is ``error`` with its diagnosis, never a pass.
* :data:`BRANCHSET_CONTEXT` -- the head's branch is not admitted by the branch set its own commit declares
  (:func:`dev_lab.dev.branchset.branchset_at`); an unreadable declaration is ``error``.

ONCE PER HEAD SHA, FOR A VERDICT: a head whose context already reads ``success`` or ``failure`` is not judged
again (a resolution is minutes of network), so a new push earns a new judgement; an ``error`` or ``pending`` is
not a verdict and is judged again next tick. A tick judges heads after its merge, sync and notice work, oldest PR
first, and starts no head once :data:`TICK_BUDGET_S` is spent; the rest wait for the next tick.
Run by the integration step of ``forge serve`` on every open PR into integration
(:func:`dev_lab.dev.forgeintegration.tick`, given its host).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from dev_lab.dev.branchset import BranchSetNotDeclared, branchset_at
from dev_lab.dev.forgestatus import status_list, status_post
from dev_lab.dev.lockcheck import DOOR, LOCK, RESOLVE_TIMEOUT_S, stale
from dev_lab.dev.relock import _worktree

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from pathlib import Path

    from dev_lab.dev.forgeintegration import Child
    from dev_lab.dev.forgework import Client

__all__ = [
    'BRANCHSET_CONTEXT',
    'LOCK_CONTEXT',
    'LOCK_REMEDY',
    'TERMINAL',
    'TICK_BUDGET_S',
    'branchset_verdict',
    'judge',
    'judge_heads',
    'lock_verdict',
]

LOCK_CONTEXT: Final = 'lock/fresh'
BRANCHSET_CONTEXT: Final = 'branchset'
#: The fix a stale lock names, first, so the 140-character status keeps it whole.
LOCK_REMEDY: Final = f'run `{DOOR}`, then commit {LOCK}'
#: The states that are a verdict; any other (``error``, ``pending``) is judged again.
TERMINAL: Final = frozenset({'success', 'failure'})
#: Seconds of a serve tick the gate may START heads within: one cold resolution's own ceiling.
TICK_BUDGET_S: Final = RESOLVE_TIMEOUT_S

Verdict = tuple[str, str]


def lock_verdict(tree: Path, *, read: Callable[[Path], tuple[str, ...]] = stale) -> Verdict:
    """``(state, description)`` for the lock in *tree*: success at the newest, else failure naming the remedy."""
    why = read(tree)
    if not why:
        return 'success', f'{LOCK} is the newest resolution'
    if why[0].startswith('the newest resolution could not run'):
        return 'error', why[0]
    moved = '; '.join(one.split(': ', 1)[-1] for one in why)
    return 'failure', f'stale {LOCK}: {LOCK_REMEDY} ({moved})'


def branchset_verdict(root: Path, sha: str, branch: str) -> Verdict:
    """``(state, description)`` for *branch* at *sha*: admitted by the branch set *sha* itself declares."""
    try:
        declared = branchset_at(root, sha)
    except BranchSetNotDeclared as why:
        return 'error', f'no readable branch set at {sha[:12]}: {why}'
    if declared.admits(branch):
        return 'success', f'{branch} is declared'
    return 'failure', (
        f'{branch} is undeclared: push it as an ephemeral head ({", ".join(declared.ephemeral) or "none declared"}) '
        'or add it to [tool.lab_commons.branchset] sessions'
    )


def judge(
    root: Path, client: Client, head: str, branch: str, *, read: Callable[[Path], tuple[str, ...]] = stale
) -> list[str]:
    """Post each context *head* does not yet carry; one line per post."""
    have = {status.context for status in status_list(client, head) if status.state in TERMINAL}
    lines = []
    if BRANCHSET_CONTEXT not in have:
        state, text = branchset_verdict(root, head, branch)
        status_post(client, head, context=BRANCHSET_CONTEXT, state=state, description=text)
        lines.append(f'{BRANCHSET_CONTEXT}: {state}')
    if LOCK_CONTEXT not in have:
        try:
            with _worktree(root, head) as tree:
                state, text = lock_verdict(tree, read=read)
        except OSError as why:
            state, text = 'error', f'the head could not be checked out to resolve: {why}'
        status_post(client, head, context=LOCK_CONTEXT, state=state, description=text)
        lines.append(f'{LOCK_CONTEXT}: {state}')
    return lines


def judge_heads(
    root: Path,
    origin: Client,
    children: Sequence[Child],
    gate: Callable[..., list[str]],
    monotonic: Callable[[], float],
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
            lines += [f'{where}: {line}' for line in gate(root, origin, child.head, child.branch)]
        except Exception as why:  # noqa: BLE001 -- one head's defect must not end the tick for the others
            lines.append(f'{where}: gate raised {type(why).__name__}: {why}')
    return lines
