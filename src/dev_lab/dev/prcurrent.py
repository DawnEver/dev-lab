"""PR-HEAD-IS-CURRENT: a ``pr/*`` head holds integration's tip and a lock fresh against the floating heads.

User ruling 2026-11-07, reversing part of toolchain plan P3 (``githooks/base.toml``): agents kept pushing stale
branches, and the forge's later ``integration`` alarm and ``lock/fresh`` status came after the harm. So ONE
judgement (:func:`judge`) refuses a head when either holds:

* BEHIND -- ``origin/<integration>``, fetched afresh (that one ref), is not an ancestor of the head. A fetch that
  fails refuses with the network's reason, never passes unchecked;
* STALE -- the head's lock lags a floated sibling's current head (dev-lab, lab-commons, ...): the floating-head
  reading :func:`dev_lab.dev.relock.floating_stale`, in a detached worktree at the head.

Both name the one remedy, :data:`SYNC` (``forge sync`` merges integration and relocks the floated siblings in the
same sync, :mod:`dev_lab.dev.forgesync`). The judgement is read at two doors: the ``pr-current`` pre-push row
(:func:`main`, ``refs = '^refs/heads/pr/'``) and ``forge pr ready`` (:func:`ready_refusals`). The forge's own
pushers' branches (:data:`dev_lab.dev.sessionbranch.MACHINE_BRANCHES`) are not judged at push: the relock IS
what makes a lock fresh. Integration is the pushed tip's ``[tool.dev_lab.integrator] integration``.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Final

import lab_commons.launch as _door
from lab_commons.log import emit

from dev_lab.dev.lanepolicy import policy_at
from dev_lab.dev.netverb import run_network_verb
from dev_lab.dev.relock import detached_worktree, floating_stale
from dev_lab.dev.sessionbranch import MACHINE_BRANCHES

if TYPE_CHECKING:
    from dev_lab.dev.forgework import Client, PullRequest

__all__ = ['HOOK_ID', 'RULE', 'SYNC', 'behind', 'judge', 'lock_stale', 'main', 'ready_refusals', 'refusals']

RULE: Final = 'PR-HEAD-IS-CURRENT'
#: The id this guard runs under in ``githooks/base.toml``.
HOOK_ID: Final = 'pr-current'
#: The one remedy for both refusals.
SYNC: Final = 'python -m dev_lab.dev.forge sync'

_GIT: Final = shutil.which('git') or 'git'
_HEADS: Final = 'refs/heads/'
_FIELDS: Final = 4

#: Fetches one ref of origin into *root*: ``None`` when it landed, else the network's reason.
Fetch = Callable[[Path, str], str | None]
#: The floating-head staleness of a tree: one sentence per lagging sibling (:func:`dev_lab.dev.relock.floating_stale`).
Read = Callable[[Path], tuple[str, ...]]


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return _door.run(
        [_GIT, '-C', str(root), *args],
        capture_output=True, text=True, encoding='utf-8', errors='replace', check=False, timeout=120,
    )  # fmt: skip


def fetch_ref(root: Path, branch: str) -> str | None:
    """Fetch origin's *branch* into ``refs/remotes/origin/<branch>``; ``None``, or why it could not."""
    spec = f'+{_HEADS}{branch}:refs/remotes/origin/{branch}'
    report = run_network_verb([_GIT, '-C', str(root), 'fetch', '--quiet', 'origin', spec], timeout=300)
    return None if report.ok else report.remedy


def behind(root: Path, sha: str, integration: str, *, fetch: Fetch = fetch_ref) -> str | None:
    """Why *sha* does not hold ``origin/<integration>``'s current tip, or ``None`` when it does."""
    if (why := fetch(root, integration)) is not None:
        return f'{RULE}: origin/{integration} could not be fetched, so {sha[:12]} cannot be judged current: {why}'
    tip = f'refs/remotes/origin/{integration}'
    if _git(root, 'merge-base', '--is-ancestor', tip, sha).returncode == 0:
        return None
    return f'{RULE}: {sha[:12]} does not contain origin/{integration}; run `{SYNC}`, then push again'


def lock_stale(root: Path, sha: str, *, read: Read = floating_stale) -> str | None:
    """Why *sha*'s lock lags a floated sibling's current head, or ``None`` when it does not."""
    try:
        with detached_worktree(root, sha) as tree:
            found = read(tree)
    except OSError as why:
        return f'{RULE}: the lock of {sha[:12]} could not be read: {why}'
    if not found:
        return None
    return f'{RULE}: the lock of {sha[:12]} is stale: {"; ".join(found)}; run `{SYNC}`, then push again'


def judge(
    root: Path, sha: str, integration: str, *, fetch: Fetch = fetch_ref, read: Read = floating_stale
) -> list[str]:
    """Every reason *sha* is not current against *integration*: BEHIND first, then STALE."""
    return [why for why in (behind(root, sha, integration, fetch=fetch), lock_stale(root, sha, read=read)) if why]


def refusals(root: Path, lines: str, *, fetch: Fetch = fetch_ref, read: Read = floating_stale) -> list[str]:
    """:func:`judge` over every created or updated branch git's pre-push *lines* name, machine branches aside."""
    found: list[str] = []
    for fields in (line.split() for line in lines.splitlines()):
        if len(fields) != _FIELDS or not fields[2].startswith(_HEADS) or set(fields[1]) == {'0'}:
            continue
        if fields[2][len(_HEADS) :] in MACHINE_BRANCHES:
            continue
        try:
            integration = policy_at(root, fields[1]).integration
        except (ValueError, OSError, subprocess.CalledProcessError) as exc:
            found.append(f'{RULE}: {fields[1][:12]} declares no readable integrator: {exc}')
            continue
        found += judge(root, fields[1], integration, fetch=fetch, read=read)
    return found


def ready_refusals(
    root: Path, client: Client, pull: PullRequest, *, fetch: Fetch = fetch_ref, read: Read = floating_stale
) -> list[str]:
    """Why PR *pull* may not be marked ready: a dirty tree, then :func:`judge` on its head as origin holds it.

    The required test statuses are NOT read (ruling 2026-11-07, D53): a draft runs nothing, so ready is the event
    that starts the tests, and the merge gate (:mod:`dev_lab.dev.forgemerge`) already requires them to pass.
    """
    del client  # the head is read off the PR record; the forge itself is not asked again
    if dirty := _git(root, 'status', '--porcelain', '--untracked-files=no').stdout.strip():
        return [f'{RULE}: the tree has uncommitted changes to tracked files; commit and push them first:\n{dirty}']
    if (why := fetch(root, pull.head)) is not None:
        return [f'{RULE}: the head {pull.head} could not be fetched: {why}']
    return judge(root, pull.head_sha, pull.base, fetch=fetch, read=read)


def main(argv: Sequence[str] | None = None) -> int:
    """The pre-push hook: git's ref lines on stdin; exit 1 refuses, 0 publishes."""
    del argv  # the remote name and url; the judgement reads origin
    top = _git(Path.cwd(), 'rev-parse', '--show-toplevel').stdout.strip()
    found = refusals(Path(top or Path.cwd()), '' if sys.stdin.isatty() else sys.stdin.read())
    if found:
        emit('\n'.join(['', *(f'  REFUSED: {line}' for line in found), '']), err=True)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
