"""OLD COPIES: what the layout before an account's declared root left behind, and the retention rule that removes it.

USER RULING 2026-11-22: "deleting is allowed -- deleting is the DEFAULT." Until then ``drift`` listed these as a
dry-run list nothing removed, and an account's FILE quota filled with them (measured: 120 k and 267 k files on an
account at its 2.0 M limit), with no door to remove them and raw ssh forbidden.

ONE LIST (:data:`STRAYS_IN_HOME`, :data:`STRAYS_IN_ROOT`, a retired ``repos/<repo>/.venv-current``): ``drift``
reports it (:func:`left_behind`) and the account's retention deletes it (:func:`plan`, rule :data:`RULE`) -- a dry
run unless ``--apply``, like every rule. Nothing outside the list is ever an old copy: a research directory in the
home is the user's.

A REFERENCED COPY IS KEPT, BY NAME (:func:`plan`'s second list): one a live process works in or executes from, one
a crontab line still names, one this very retention runs from, and one that holds the declared root itself -- an
account not yet moved to its declared root still LIVES in its old copy. A crontab that cannot be read keeps them all.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Final

from lab_commons.census import Process

from dev_lab.dev.liverun import label, removal_holders
from dev_lab.dev.retentionplan import Doomed
from dev_lab.dev.venvpointer import RETIRED_POINTER

__all__ = ['DOOR', 'RULE', 'STRAYS_IN_HOME', 'STRAYS_IN_ROOT', 'left_behind', 'plan']

#: Where the layout before the declared root kept the forge, home-relative and root-relative.
STRAYS_IN_HOME: Final = ('.local/share/lab-forge', 'ci', 'src/dev-lab')
STRAYS_IN_ROOT: Final = ('dev-lab', 'src')
#: The retention rule an old copy goes by.
RULE: Final = 'old-copy'
#: The door that removes them, from the workstation.
DOOR: Final = 'python -m dev_lab.dev.hpcaccount retention --account <user> [--apply]'


def left_behind(home: Path, root: Path) -> list[Path]:
    """Every old copy the account at *root* (login home *home*) still holds; read only."""
    old = [home / p for p in STRAYS_IN_HOME] + [root / p for p in STRAYS_IN_ROOT]
    old += [repo / RETIRED_POINTER for repo in sorted((root / 'repos').glob('*'))]
    return [p for p in old if p.exists() or p.is_symlink()]


def _holds(copy: Path, path: Path) -> bool:
    return path == copy or copy in path.parents


def _named(copy: Path, home: Path, crontab: str) -> bool:
    """Whether a live line of *crontab* names *copy*: absolute, or as ``~/...`` / ``$HOME/...`` under *home*."""
    spelled = [copy.as_posix()]
    if _holds(home, copy):
        rest = copy.relative_to(home).as_posix()
        spelled += [f'~/{rest}', f'$HOME/{rest}', f'${{HOME}}/{rest}']
    named = re.compile('|'.join(f'{re.escape(one)}(?![\\w.-])' for one in spelled))
    return any(named.search(line) for line in crontab.splitlines() if not line.lstrip().startswith('#'))


def _kept(
    copy: Path, *, home: Path, root: Path, cwd: Path, crontab: str | None, holders: Callable[[Path], Sequence[Process]]
) -> str:
    """Why *copy* is still referenced (``''``: nothing references it)."""
    if _holds(copy, root):
        return 'it holds the declared root: the account still lives in it'
    if _holds(copy, cwd):
        return 'this retention runs from it'
    if crontab is None:
        return 'the crontab cannot be read, so no line is known not to name it'
    if _named(copy, home, crontab):
        return 'a crontab line still names it'
    if live := holders(copy):
        return 'a live process still uses it: ' + ', '.join(f'pid {one.pid} ({label(one)})' for one in live)
    return ''


def plan(
    home: Path,
    root: Path,
    *,
    cwd: Path,
    crontab: Callable[[], str | None],
    holders: Callable[[Path], Sequence[Process]] = removal_holders,
) -> tuple[list[Doomed], list[str]]:
    """The old copies that go (rule :data:`RULE`), and one line per copy kept because something references it.

    *crontab* reads the account's crontab (``None``: unreadable) -- only when there is an old copy to judge.
    """
    found = left_behind(home, root)
    listed = crontab() if found else ''
    doomed: list[Doomed] = []
    kept: list[str] = []
    for copy in found:
        if why := _kept(copy, home=home, root=root, cwd=cwd, crontab=listed, holders=holders):
            kept.append(f'[retention] old copy kept: {copy.as_posix()} -- {why}')
        else:
            doomed.append(Doomed(copy, RULE))
    return doomed, kept
