"""IS MY TASK HEARD? The machine hearer's liveness, its stable interpreter, and a task's subscription (v1 #2).

:mod:`dev_lab.dev.forgefeed` is the hearer; this module answers about it without importing it:

* THE LOCK AND THE BEAT. The hearer holds ``lock.json`` (pid, creation stamp, interpreter) and writes
  ``beat.json`` after every tick, both under :func:`~dev_lab.dev.forgethreads.feed_dir`. A recycled pid reads as
  gone (:func:`alive`).
* A STABLE INTERPRETER. The hearer outlives every session, so it runs from the MAIN checkout's current environment
  (:func:`stable_python`) -- never a linked worktree's, which is republished or pruned under it (v1 #2: a hearer
  started from ``.claude/worktrees/<lane>/.venv`` died with that lane's environment).
* THE DOOR. Whatever cannot start it names :func:`start_door`; a label write that subscribes a task while no hearer
  runs says so (:func:`unheard_notice`).
* ``forgefeed status [<slug>]`` (:func:`status`): the hearer (pid, interpreter, last tick) and the task's
  subscription -- the open issues labeled ``task:<slug>`` in each declared repository -- and its kept events.
"""

from __future__ import annotations

import contextlib
import os
import time
from pathlib import Path
from typing import TYPE_CHECKING, Final, cast

from lab_commons.liveness import still_the_same_process

from dev_lab.dev.backgroundrun import repo_main
from dev_lab.dev.forgefailure import ForgeCallFailed
from dev_lab.dev.forgethreads import LABEL, feed_dir, read_json
from dev_lab.dev.venvpath import VENV_LAYOUTS
from dev_lab.dev.venvpointer import current

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping

    from dev_lab.dev.forge import Forge
    from dev_lab.dev.forgework import Client

__all__ = [
    'RULE',
    'NoStableInterpreter',
    'alive',
    'beat_path',
    'lock_path',
    'running',
    'stable_python',
    'start_door',
    'status',
    'unheard_notice',
]

#: The rule the hearer serves.
RULE: Final = 'TASK-HEARS-ITS-FORGE-EVENTS'
#: How many open issues one repository lists for a subscription.
_LISTED: Final = 100


class NoStableInterpreter(LookupError):
    """No main checkout with a current environment to run the hearer from; the message names the door."""


def lock_path() -> Path:
    """The hearer's lock: who holds the machine's one hearer."""
    return feed_dir() / 'lock.json'


def beat_path() -> Path:
    """The hearer's beat: written after every tick."""
    return feed_dir() / 'beat.json'


def alive(held_by: Mapping[str, object]) -> bool:
    """Whether the process *held_by* names (pid and creation stamp) still runs; a recycled pid is gone."""
    try:
        return bool(still_the_same_process(int(str(held_by['pid'])), held_by.get('created')))
    except KeyError, TypeError, ValueError:
        return False


def running() -> bool:
    """Whether a live hearer holds the machine lock."""
    return alive(read_json(lock_path()))


def stable_python(root: Path) -> tuple[Path, Path]:
    """``(main checkout, interpreter)`` the hearer runs in: the CURRENT environment of *root*'s MAIN checkout.

    Found from any tree of the repository; never a linked worktree's environment.

    Raises:
        NoStableInterpreter: *root* is in no git checkout, or its main checkout has no environment.

    """
    main = repo_main(root)
    if main is None:
        msg = (
            f'{RULE}: {root} is in no git checkout, so no main checkout holds a stable interpreter for the hearer; '
            'start it from a main checkout: <its python> -m dev_lab.dev.forgefeed start'
        )
        raise NoStableInterpreter(msg)
    python = current(main).joinpath(*VENV_LAYOUTS[os.name][1:])
    if not python.is_file():
        msg = (
            f'{RULE}: the main checkout {main} has no environment ({python} is missing), and the hearer never runs '
            f'from a worktree venv; bootstrap it (python -m dev_lab.dev.dep --bootstrap {main}), then start the '
            f'hearer: {python} -m dev_lab.dev.forgefeed start'
        )
        raise NoStableInterpreter(msg)
    return main, python


def start_door(root: Path) -> str:
    """The command that starts the hearer for *root*'s machine, from its stable interpreter."""
    try:
        python = str(stable_python(root)[1])
    except NoStableInterpreter:
        python = '<main checkout python>'
    return f'{python} -m dev_lab.dev.forgefeed start'


def unheard_notice(root: Path, labels: Iterable[str]) -> str | None:
    """The line a ``task:<slug>`` label write says while no hearer runs; ``None`` when one runs or none subscribes."""
    tasks = sorted({label for label in labels if label.startswith(LABEL) and len(label) > len(LABEL)})
    if not tasks or running():
        return None
    return (
        f'{RULE}: no hearer runs on this machine, so {", ".join(tasks)} is labeled but not heard; '
        f'start it: {start_door(root)}'
    )


def _hearer(root: Path, now: float) -> list[str]:
    held: dict[str, object] = read_json(lock_path())
    beat: dict[str, object] = read_json(beat_path())
    tick = beat.get('at')
    ago = f'last tick {now - float(tick):.0f} s ago' if isinstance(tick, int | float) else 'no tick recorded'
    if alive(held):
        python = str(held.get('python') or '(interpreter not recorded)')
        hosts = beat.get('hosts')
        heard = len(cast('list[object]', hosts)) if isinstance(hosts, list) else 0
        return [f'hearer: running, pid {held["pid"]} ({python}), {ago}, {heard} repos heard']
    return [f'hearer: NOT running ({ago}); start it: {start_door(root)}']


def _subscribed(slug: str, clients: Callable[[Forge], Client], forges: Iterable[Forge]) -> list[str]:
    label, found = f'{LABEL}{slug}', 0
    lines: list[str] = []
    for forge in sorted(set(forges), key=lambda f: f.identity):
        try:
            issues = clients(forge).issue_list(state='open', limit=_LISTED, labels=[label])
        except (ForgeCallFailed, OSError, ValueError) as failed:
            lines.append(f'  {forge.identity}: unreadable ({failed})')
            continue
        found += len(issues)
        lines += [f'  {forge.identity}#{one.number} {one.title}' for one in issues]
    if not found:
        lines.append(f'  no open issue carries {label}; subscribe one: forge issue label <N> --add {label}')
    return [f'task {slug}: {found} open thread(s) labeled {label}', *lines]


def status(
    root: Path,
    slug: str | None,
    *,
    clients: Callable[[Forge], Client],
    forges: Iterable[Forge],
    pending: Callable[[str], list[str]],
    now: float | None = None,
) -> list[str]:
    """``forgefeed status [<slug>]``: the hearer's liveness, then -- given a task -- its subscription and queue."""
    lines = _hearer(root, time.time() if now is None else now)
    if slug is None:
        return [*lines, 'task: none named and this checkout works on none; ask: forgefeed status <slug>']
    lines += _subscribed(slug, clients, forges)
    with contextlib.suppress(OSError):
        kept = pending(slug)
        lines.append(f'queue: {len(kept)} event(s) kept for {slug} (forgefeed task-pending {slug})')
    return lines
