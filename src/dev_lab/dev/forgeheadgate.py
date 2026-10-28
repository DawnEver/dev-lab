"""The forge's judgement of an open PR head's LOCK FRESHNESS and BRANCH SET, as two commit statuses on that head.

User ruling 2026-10-24 (toolchain plan P3): neither is read at a local push any more, so the forge says each one
where the author reads it -- a status on the PR head, ``failure`` naming the exact command that fixes it:

* :data:`LOCK_CONTEXT` -- the head's ``uv.lock`` moves a resolution its BASE does not
  (:func:`dev_lab.dev.lockcheck.stale` on the head, then on its merge-base with ``origin/<integration>``, each in a
  detached worktree); the remedy is the one dependency door, :data:`LOCK_REMEDY`. A resolution that cannot run is
  ``error`` with its diagnosis, never a pass.

  A PR NEVER CHASES THE LOCK (user ruling 2026-10-28): a move the base lags too -- a sibling or a dist that
  published after the PR branched -- is integration's, carried by the forge's relock pull request
  (:mod:`dev_lab.dev.relock`) and taken by ``forge sync``; it is never the head's defect. What stays refused is the
  head's own: a lock older than its base's, or one its own ``pyproject.toml`` moves (a requirement not relocked).
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

import lab_commons.launch as _door

from dev_lab.dev.branchset import BranchSetNotDeclared, branchset_at
from dev_lab.dev.forge import _GIT, _GIT_TIMEOUT_S
from dev_lab.dev.forgestatus import status_list, status_post
from dev_lab.dev.lockcheck import DOOR, LOCK, RESOLVE_TIMEOUT_S, UNRESOLVED, stale
from dev_lab.dev.relock import detached_worktree

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
    'merge_base',
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
        'or add it to [tool.dev_lab.branchset] sessions'
    )


def merge_base(root: Path, head: str, integration: str) -> str:
    """The merge-base of *head* with ``origin/<integration>`` in *root*; RAISES :class:`OSError` on none."""
    done = _door.run(
        [_GIT, '-C', str(root), 'merge-base', head, f'refs/remotes/origin/{integration}'],
        capture_output=True, text=True, encoding='utf-8', errors='replace', check=False, timeout=_GIT_TIMEOUT_S,
    )  # fmt: skip
    if done.returncode != 0:
        msg = f'no merge-base of {head[:12]} with origin/{integration}: {done.stderr.strip()}'
        raise OSError(msg)
    return done.stdout.strip()


def judge(
    root: Path,
    client: Client,
    head: str,
    branch: str,
    *,
    integration: str,
    read: Callable[[Path], tuple[str, ...]] = stale,
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
            base = merge_base(root, head, integration)
            with detached_worktree(root, head) as tree, detached_worktree(root, base) as based:
                state, text = lock_verdict(tree, based, read=read)
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
