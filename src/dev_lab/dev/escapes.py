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
or lies in one of ``lab_commons.home``'s write roots or agent repos (:func:`allowed_roots`), or when the resolver
exempts it -- Claude's configuration and git's credential store (user ruling 2026-11-07).
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path
from typing import Final

from lab_commons import home as machine
from lab_commons.compute.durable import durable_text
from lab_commons.config import section

from dev_lab.dev.forgealarm import ESCAPE, Alarm
from dev_lab.supervise.hostalarms import state_path

__all__ = ['ESCAPE_ROOTS', 'allowed_roots', 'scan', 'step']

#: Where escaped writes were found (2026-11-03 sweep): the system-drive temp dirs and JMAG's own temp.
ESCAPE_ROOTS: Final = ('C:/tmp', 'C:/temp', 'C:/jmtmp', '~/JMAGDesignerTemp', '~/ModellerTemp')
#: The state file beside the host's alarm state: when the census last looked.
STATE_NAME: Final = 'escapes.json'


def allowed_roots() -> tuple[Path, ...]:
    """The roots a write may land in, as ``lab_commons.home`` declares them: its write roots and agent repos."""
    return (*machine.write_roots(), *machine.agent_repos().values())


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


def scan(roots: Sequence[Path], *, home: Path, allowed: Sequence[Path], since: float) -> list[Path]:
    """Every entry of a watched root, and every top-level home entry outside *allowed*, changed after *since*.

    A home entry ``lab_commons.home`` exempts (Claude's configuration, git's credential store) is never one.
    """
    found: list[Path] = []
    for root in roots:
        if root.is_dir():
            found += _changed(sorted(root.iterdir()), since)
    if home.is_dir():
        outside = (one for one in sorted(home.iterdir()) if not (_under(one, allowed) or machine.exempt(one)))
        found += _changed(outside, since)
    return found


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

    The first scan on a host records a baseline and sounds nothing.
    """
    home = home or Path.home()
    state = state or state_path().with_name(STATE_NAME)
    now = time.time()
    try:
        since = float(json.loads(state.read_text(encoding='utf-8'))['scanned'])
    except (OSError, ValueError, KeyError, TypeError):
        since = None  # the first scan is the baseline: what already sits there is the 11-03 sweep's, not news
    if since is None:
        state.parent.mkdir(parents=True, exist_ok=True)
        durable_text(state, json.dumps({'scanned': now}))
        return []
    found = scan(
        _watched(home) if roots is None else roots,
        home=home,
        allowed=allowed_roots() if allowed is None else allowed,
        since=since,
    )
    for path in found:
        alarm(Alarm(
            ESCAPE, repo, f'a write escaped the allowed roots: {path.as_posix()}',
            f'{path.as_posix()} was written outside every allowed root. A program output belongs in its repo\'s '
            f'output/logs/<yy>/<mm>/<dd>/<kind>/, a script in scratch/<yy>/<mm>/<dd>/<kind>/: move it there and fix '
            'its writer (a vendor tool writes into its cwd or its own temp: give it one under output/).',
            about=path.as_posix(),
        ))  # fmt: skip
    state.parent.mkdir(parents=True, exist_ok=True)
    durable_text(state, json.dumps({'scanned': now}))
    return found
