"""ESCAPE CENSUS: a file written outside every allowed root is found on the tick and alarmed once (2026-11-03).

User ruling 2026-11-03: every write lands in a configured repo's ``output/`` or ``scratch/``, or in the machine
home. The ``WRITE-OUTSIDE-ROOTS`` hook refuses a write whose target it can read; this census is the backstop for
the rest -- a target spelled through a variable, a vendor tool's own temp, a process no hook sees. The 11-03
sweep found 25 GB of them (``C:/tmp``, ``C:/temp``, ``C:/jmtmp``).

WHAT IS WATCHED, cheaply -- one level deep, never walked: each watched root's direct entries
(:data:`ESCAPE_ROOTS`, plus the machine file's ``[sync] roots``), and the home's top level minus the allowed
roots. An entry is an escape when it changed since the last scan; the scan time is kept beside the host's alarm
state, so each escape is found once and :func:`step` sounds it once (:data:`~dev_lab.dev.forgealarm.ESCAPE`,
deduplicated per path by the alarm's repeat window).

WHAT IS ALLOWED is the machine home's resolver's, never restated here: a home entry is no escape when it holds
or lies in one of ``lab_commons.home``'s write roots or agent repos, or in the account's ONE declared root where
it has one (``LAB_ROOT``, :func:`lab_commons.hpc.layout.local_root`) (:func:`allowed_roots`), or when the
resolver exempts it -- agent host configuration and git's credential store (user ruling 2026-11-07).

THE ALARM IS FOR A RUN WRITING OUTSIDE ITS TREE, so the home is judged by what a run can add to it (measured
2026-11-22: a served account alarmed its own ``.bashrc``, ``.cache``, ``.config`` and its declared root on every
tick). The state keeps the names the home held at the last scan: a DOTFILE that was already there is the
account's own login state (a profile, a tool's cache or configuration) and its changing is no escape; a NEW
entry, dotfile or not, and a changed entry that is not a dotfile, still are. The credential door's own files
(:data:`~dev_lab.dev.credstore.STORE` and its ``.reader`` / ``.bak-<ts>`` / ``.new-<ts>`` siblings) are login
state it writes by design, never a run's.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Collection, Iterable, Sequence
from pathlib import Path
from typing import Final

from lab_commons import home as machine
from lab_commons.compute.durable import durable_text
from lab_commons.config import section
from lab_commons.hpc.layout import RootUndeclared, local_root

from dev_lab.dev.credstore import STORE
from dev_lab.dev.forgealarm import ESCAPE, Alarm
from dev_lab.supervise.hostalarms import state_path

__all__ = ['ESCAPE_ROOTS', 'allowed_roots', 'scan', 'step']

#: Where escaped writes were found (2026-11-03 sweep): the system-drive temp dirs and JMAG's own temp.
ESCAPE_ROOTS: Final = ('C:/tmp', 'C:/temp', 'C:/jmtmp', '~/JMAGDesignerTemp', '~/ModellerTemp')
#: The state file beside the host's alarm state: when the census last looked.
STATE_NAME: Final = 'escapes.json'


def allowed_roots() -> tuple[Path, ...]:
    """The roots a write may land in: ``lab_commons.home``'s write roots and agent repos, and the declared root.

    The declared root is a served account's (``LAB_ROOT``, exported by its deploy); a machine with none has none.
    """
    try:
        declared: tuple[Path, ...] = (Path(local_root().root),)
    except RootUndeclared:
        declared = ()
    return (*machine.write_roots(), *machine.agent_repos().values(), *declared)


def _under(path: Path, roots: Iterable[Path]) -> bool:
    return any(path == root or root in path.parents or path in root.parents for root in roots)


def _changed(entries: Iterable[Path], since: float) -> list[Path]:
    found = []
    for entry in entries:
        try:
            if entry.stat().st_mtime > since:
                found.append(entry)
        except OSError:
            continue  # gone between listing and stat
    return found


def _login_state(name: str, known: Collection[str]) -> bool:
    """Whether the home entry *name* is the account's own login state: a dotfile already there, or the store's."""
    return (name.startswith('.') and name in known) or name == STORE or name.startswith(f'{STORE}.')


def scan(
    roots: Sequence[Path], *, home: Path, allowed: Sequence[Path], since: float, known: Collection[str] = ()
) -> list[Path]:
    """Every entry of a watched root, and every top-level home entry outside *allowed*, changed after *since*.

    A home entry ``lab_commons.home`` exempts (agent host configuration, git's credential store) is never one,
    nor is the account's login state: a dotfile the home already held (*known*) or the credential door's files.
    """
    found: list[Path] = []
    for root in roots:
        if root.is_dir():
            found += _changed(sorted(root.iterdir()), since)
    if home.is_dir():
        outside = (
            one
            for one in sorted(home.iterdir())
            if not (_under(one, allowed) or _login_state(one.name, known) or machine.exempt(one))
        )
        found += _changed(outside, since)
    return found


def _names(home: Path) -> list[str]:
    return sorted(one.name for one in home.iterdir()) if home.is_dir() else []


def _remember(state: Path, now: float, home: Path) -> None:
    state.parent.mkdir(parents=True, exist_ok=True)
    durable_text(state, json.dumps({'scanned': now, 'home': _names(home)}))


def _watched(home: Path) -> tuple[Path, ...]:
    declared = section('sync').get('roots', [])
    return tuple(Path(str(one).replace('~', str(home), 1)) for one in (*ESCAPE_ROOTS, *declared))


def step(
    repo: str,
    *,
    alarm: Callable[[Alarm], object],
    roots: Sequence[Path] | None = None,
    home: Path | None = None,
    allowed: Sequence[Path] | None = None,
    state: Path | None = None,
) -> list[Path]:
    """One tick's census: scan since the last one, sound each escape once, remember the scan time.

    The first scan on a host -- no state, or one that does not name the home's entries -- records a baseline and
    sounds nothing.
    """
    home = home or Path.home()
    state = state or state_path().with_name(STATE_NAME)
    now = time.time()
    try:
        record = json.loads(state.read_text(encoding='utf-8'))
        since, known = float(record['scanned']), frozenset(map(str, record['home']))
    except (OSError, ValueError, KeyError, TypeError):
        _remember(state, now, home)  # the baseline: what already sits there is the 11-03 sweep's, not news
        return []
    found = scan(
        _watched(home) if roots is None else roots,
        home=home,
        allowed=allowed_roots() if allowed is None else allowed,
        since=since,
        known=known,
    )
    for path in found:
        alarm(Alarm(
            ESCAPE, repo, f'a write escaped the allowed roots: {path.as_posix()}',
            f'{path.as_posix()} was written outside every allowed root. A program output belongs in its repo\'s '
            f'output/logs/<yy>/<mm>/<dd>/<kind>/, a script in scratch/<yy>/<mm>/<dd>/<kind>/: move it there and fix '
            'its writer (a vendor tool writes into its cwd or its own temp: give it one under output/).',
            about=path.as_posix(),
        ))  # fmt: skip
    _remember(state, now, home)
    return found
