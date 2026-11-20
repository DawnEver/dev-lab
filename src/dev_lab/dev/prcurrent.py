"""PR-HEAD-IS-CURRENT: a ``pr/*`` head holds integration's tip and a lock fresh against the floating heads.

User ruling 2026-11-07, reversing part of toolchain plan P3 (``githooks/base.toml``): agents kept pushing stale
branches, and the forge's later ``integration`` alarm and lock freshness status came after the harm. So ONE
judgement (:func:`judge`) refuses a head when either holds:

* BEHIND -- the head lacks a first-parent landing of ``origin/<integration>`` (fetched afresh, that one ref) older
  than :data:`~dev_lab.dev.locklag.LAG_WINDOW` (:func:`~dev_lab.dev.locklag.lag_of`). A fetch that fails refuses
  with the network's reason, never passes unchecked. The window is the one ``lock/lag`` reads (DECISION 14): an
  exact-contains rule, measured 2026-11-15 on a repo landing a commit every few minutes, went stale on four heads in
  a row before review could start, and review waits on this gate (REVIEW RUNS LAST, ADVISORY);
* STALE -- the head's lock pins a floated sibling (dev-lab, lab-commons, ...) past the same window behind its line:
  :func:`dev_lab.dev.locklag.within_window`, the ONE window the forge's ``lock/lag`` also reads (DECISION 14) --
  exact heads made every landing stale every dependent PR. A sibling line that cannot be fetched is named with
  its fetch and refuses.

The window is TIME, not commits (user ruling 2026-11-15): a sibling landing 70+ commits a day expired a 20-commit
window within hours, so stale pushes reached the forge and turned red later.

THE PUSHING KIT (pre-push only, :func:`kit_stale`): the pushing interpreter's git-installed siblings must be the
commits the pushed tip's lock pins (:mod:`dev_lab.dev.lockpins`, the one stale-environment judgement), else the
hooks that just judged this push ran an older family kit; the remedy is the repo's bootstrap door. The forge
judges its own environment, so this is no status.

Both name the one remedy, :data:`SYNC` (``forge sync`` merges integration and relocks the floated siblings in the
same sync, :mod:`dev_lab.dev.forgesync`). The judgement is read at three doors: the forge's ``pr-current`` status on
every open PR head, an ALARM the merge never waits on (:mod:`dev_lab.dev.forgeheadgate`, W5 dev-lab#644: the
trial merge at merge time decides mergeability), ``forge pr ready`` (:func:`ready_refusals`), and the
``pr-current`` pre-push row (:func:`main`, ``refs = '^refs/heads/pr/'``) -- a WARNING: the row is ``advisory``
(dev-lab #661), because refusing a push on an alarm would be a merge gate that does not exist. The forge's own
pushers' branches (:data:`dev_lab.dev.sessionbranch.MACHINE_BRANCHES`) are not judged (:func:`judged`): the relock
IS what makes a lock fresh.
Integration is the pushed tip's ``[tool.dev_lab.integrator] integration``.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import time
import tomllib
from collections.abc import Callable, Sequence
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Final

import lab_commons.launch as _door
from lab_commons.log import emit

from dev_lab.dev.lanepolicy import policy_at
from dev_lab.dev.lockcheck import LOCK
from dev_lab.dev.locklag import LAG_WINDOW, Clock, hours, lag_of, within_window
from dev_lab.dev.lockpins import Installed, installed_git, mismatches, pinned_git, refusal, sync_door
from dev_lab.dev.netverb import run_network_verb
from dev_lab.dev.sessionbranch import MACHINE_BRANCHES

if TYPE_CHECKING:
    from collections.abc import Iterable

    from dev_lab.dev.forgework import Client, PullRequest

__all__ = [
    'HOOK_ID',
    'RULE',
    'SYNC',
    'behind',
    'head_refusals',
    'judge',
    'judged',
    'kit_stale',
    'lock_stale',
    'main',
    'ready_refusals',
    'refusals',
]

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
#: Why lock text is not current enough, one sentence per sibling past the window (locklag.within_window).
Read = Callable[[str], tuple[str, ...]]

#: What every warning here ends with: this hook is early feedback, and the forge's status is an alarm, not a gate.
EARLY: Final = (
    f'  (early feedback: the forge posts this judgement as the {HOOK_ID!r} status on the PR head, an alarm the '
    'merge does not wait on; the push goes ahead)'
)


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


def behind(
    root: Path,
    sha: str,
    integration: str,
    *,
    fetch: Fetch = fetch_ref,
    window: timedelta = LAG_WINDOW,
    now: Clock = time.time,
) -> str | None:
    """Why *sha* lacks ``origin/<integration>`` landings past *window* (:func:`~dev_lab.dev.locklag.lag_of`)."""
    if (why := fetch(root, integration)) is not None:
        return f'{RULE}: origin/{integration} could not be fetched, so {sha[:12]} cannot be judged current: {why}'
    try:
        lag = lag_of(lambda *argv: _git(root, *argv), sha, f'refs/remotes/origin/{integration}', now=now)
    except OSError as unread:
        return f'{RULE}: {unread}'
    if not lag.past(window):
        return None
    return (
        f'{RULE}: {sha[:12]} lacks {lag} of origin/{integration}, past the window of {hours(window)}; '
        f'run `{SYNC}`, then push again'
    )


def kit_stale(root: Path, sha: str, *, installed: Callable[[], Iterable[Installed]] = installed_git) -> str | None:
    """Why the pushing interpreter's git-installed siblings are not what *sha*'s lock pins, or ``None``."""
    shown = _git(root, 'show', f'{sha}:{LOCK}')
    try:
        pins = pinned_git(shown.stdout) if shown.returncode == 0 else {}
    except tomllib.TOMLDecodeError:
        pins = {}  # an unreadable lock pins nothing; the forge's lock/lag judges whether it renders
    why = refusal(mismatches(installed(), pins), door=sync_door(root))
    return None if why is None else f'{RULE}: the pushing kit is stale: {why}'


def lock_stale(root: Path, sha: str, *, read: Read = within_window) -> str | None:
    """Why *sha*'s lock pins a floated sibling past the lag window, or ``None`` when it does not."""
    shown = _git(root, 'show', f'{sha}:{LOCK}')
    found = read(shown.stdout) if shown.returncode == 0 else ()  # no lock: nothing floats
    if not found:
        return None
    return f'{RULE}: the lock of {sha[:12]} is stale: {"; ".join(found)}; run `{SYNC}`, then push again'


def judge(
    root: Path,
    sha: str,
    integration: str,
    *,
    fetch: Fetch = fetch_ref,
    read: Read = within_window,
    window: timedelta = LAG_WINDOW,
) -> list[str]:
    """Every reason *sha* is not current against *integration*: BEHIND first, then STALE."""
    reasons = (behind(root, sha, integration, fetch=fetch, window=window), lock_stale(root, sha, read=read))
    return [why for why in reasons if why]


def head_refusals(
    root: Path,
    sha: str,
    branch: str,
    integration: str,
    *,
    fetch: Fetch = fetch_ref,
    read: Read = within_window,
    window: timedelta = LAG_WINDOW,
) -> list[str]:
    """:func:`judge` on *branch* at *sha*; nothing where the rule does not apply (a machine branch, a non-``pr/``).

    The one entry both the pre-push row (:func:`refusals`) and the forge's status (:mod:`~dev_lab.dev.forgeheadgate`)
    call, so the two never disagree on which heads are judged.
    """
    return judge(root, sha, integration, fetch=fetch, read=read, window=window) if judged(branch) else []


def judged(branch: str) -> bool:
    """Whether *branch* is one this rule judges: a ``pr/`` head, the forge's own pushers' aside."""
    return branch.startswith('pr/') and branch not in MACHINE_BRANCHES


def refusals(
    root: Path,
    lines: str,
    *,
    fetch: Fetch = fetch_ref,
    read: Read = within_window,
    window: timedelta = LAG_WINDOW,
    kit: Callable[[Path, str], str | None] = kit_stale,
) -> list[str]:
    """:func:`judge` and :func:`kit_stale` on every created or updated branch git's pre-push *lines* name.

    Machine branches aside; the kit is judged once, against the first judged tip's lock.
    """
    found: list[str] = []
    kit_read = False
    for fields in (line.split() for line in lines.splitlines()):
        if len(fields) != _FIELDS or not fields[2].startswith(_HEADS) or set(fields[1]) == {'0'}:
            continue
        branch = fields[2][len(_HEADS) :]
        if not judged(branch):
            continue
        if not kit_read and (stale_kit := kit(root, fields[1])):
            found.append(stale_kit)
        kit_read = True
        try:
            integration = policy_at(root, fields[1]).integration
        except (ValueError, OSError, subprocess.CalledProcessError) as exc:
            found.append(f'{RULE}: {fields[1][:12]} declares no readable integrator: {exc}')
            continue
        found += head_refusals(root, fields[1], branch, integration, fetch=fetch, read=read, window=window)
    return found


def ready_refusals(
    root: Path,
    client: Client,
    pull: PullRequest,
    *,
    fetch: Fetch = fetch_ref,
    read: Read = within_window,
    window: timedelta = LAG_WINDOW,
) -> list[str]:
    """Why PR *pull* may not be marked ready: :func:`judge` on its head as origin holds it -- never the local tree.

    Ready is a forge API call on a pushed head (user ruling 2026-11-13): the checkout it runs from -- a main checkout
    with an unrelated ``M uv.lock``, any worktree of the repo -- has no say, so no dirty-tree condition exists.
    The required test statuses are NOT read (ruling 2026-11-07, D53): a draft runs nothing, so ready is the event
    that starts the tests, and the merge gate (:mod:`dev_lab.dev.forgemerge`) already requires them to pass.
    """
    del client  # the head is read off the PR record; the forge itself is not asked again
    if (why := fetch(root, pull.head)) is not None:
        return [f'{RULE}: the head {pull.head} could not be fetched: {why}']
    return judge(root, pull.head_sha, pull.base, fetch=fetch, read=read, window=window)


def main(argv: Sequence[str] | None = None) -> int:
    """The pre-push row: git's ref lines on stdin; exit 1 names a stale head, which the ``advisory`` row shows."""
    del argv  # the remote name and url; the judgement reads origin
    top = _git(Path.cwd(), 'rev-parse', '--show-toplevel').stdout.strip()
    found = refusals(Path(top or Path.cwd()), '' if sys.stdin.isatty() else sys.stdin.read())
    if found:
        emit('\n'.join(['', *(f'  WARNING: {line}' for line in found), EARLY, '']), err=True)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
