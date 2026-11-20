"""THE HOST'S uv FOLLOWS ITS PIN: before a lock is written, a uv that is not the pinned one is moved to it.

THE INCIDENT (2026-11-06). Host G ran uv 0.13.5 while :data:`~dev_lab.dev.lockcheck.UV_PIN` pinned 0.13.7. The
dependency door refused, rightly ("every lock is written by uv 0.13.7"), and every integration and sync job failed
for hours ("the lock could not be relocked: the dependency door exited 1") until a human ran winget. The refusal
named the remedy; nothing applied it. User ruling 2026-11-06: a mechanism guarantees the update, by itself.

ONE SOURCE, ONE DOOR. The version is :func:`~dev_lab.dev.lockcheck.uv_version` (``uv.toml``), never restated here;
the place it is enforced is the place a lock is written (:func:`dev_lab.dev._dep_project.lock_writer`) and the
relock that raises the pin (:func:`dev_lab.dev.relock.carry`). Every host that writes a lock -- the serve tick's
relock job, a workstation's ``--sync``/``--lock-upgrade`` on Ada, AMD-1/2, A1 -- passes through one of the two, so
no poller and no second schedule is added.

THE ROUTE IT WAS INSTALLED BY. uv updates through the installer that put it there, read from where the binary
lives (:func:`route_of`): a WinGet install (``.../WinGet/Links`` or ``.../WinGet/Packages/astral-sh.uv_...``)
is reinstalled at exactly the version by ``winget``; any other (the standalone installer, ``~/.local/bin`` or
``~/.cargo/bin``) by ``uv self update <version>``, which itself refuses a uv no installer of its own put there --
that refusal is reported, not guessed around. Both reach the network, so both run through
:func:`~dev_lab.dev.netverb.run_network_verb` and a transient failure is retried, not reported as "stale uv".

THE HOSTS FOLLOW TOO (measured 2026-11-09: the pin 0.13.7 was the newest release, a cloud host ran 0.12.5): the
cluster deploy and every kit tick (:mod:`dev_lab.dev.hpcaccount`) and ``ops upgrade``
(:func:`dev_lab.ops.upgrade.follow_uv`)
call the same follower, and ``family check`` names a pin lagging the newest release (:func:`lag`).

A HELD BINARY IS MOVED ASIDE (measured 2026-11-20: a WinGet downgrade failed 3/3 as unclassified with ``remove:
Access is denied`` on ``WinGet/Packages/astral-sh.uv_.../uv.exe`` -- running uv processes held it). The network door
classifies that refusal as ``file-held`` (:mod:`dev_lab.dev._netverb_rows`); :func:`follow` then renames the
package's executables aside (renaming a running exe is allowed, deleting it is not) and installs once more. The
moved files are deleted by a later :func:`follow` (:func:`sweep`) once nothing holds them.

THE POLICY (user ruling D101, 2026-11-20) is ``follow`` in ``uv.toml`` (:func:`~dev_lab.dev.lockcheck.uv_policy`):
``minor`` moves the pin only to a newer MINOR release, ``patch`` to any newer release; :func:`due` applies it.

When the update cannot land, :func:`follow` says why; the door's refusal carries it, and on a serving host the
relock step alarms with it (:func:`dev_lab.dev.forgeservesteps.relock`).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from enum import StrEnum
from pathlib import Path, PurePath
from typing import Final

from dev_lab.dev.netverb import Diagnosis, Report, run_network_verb

__all__ = [
    'ASIDE',
    'POLICIES',
    'WINGET_ID',
    'Route',
    'due',
    'follow',
    'held_package',
    'lag',
    'move_aside',
    'route_of',
    'sweep',
    'update_argv',
]

#: The WinGet package uv is installed as on Windows hosts (docs-src/dev/adding-a-workstation.md).
WINGET_ID: Final = 'astral-sh.uv'

#: Seconds one installer attempt may take: a download plus an install, never a hang.
_UPDATE_TIMEOUT_S: Final = 600

#: The uv auto-update policies ``uv.toml``'s ``follow`` may name: the release part a pin moves on.
POLICIES: Final = ('minor', 'patch')
#: The executables a WinGet uv package carries, each of which a running process may hold.
_EXECUTABLES: Final = ('uv.exe', 'uvx.exe', 'uvw.exe')
#: The suffix a held executable is renamed to; :func:`sweep` deletes such files once nothing holds them.
ASIDE: Final = '.held-aside'
#: The package directory a ``remove: Access is denied`` refusal names.
_HELD_DIR: Final = re.compile(
    r"""(?P<dir>(?:[A-Za-z]:)?[^\s"':]*?WinGet[\\/]Packages[\\/]astral-sh\.uv_[^\\/\s"']+)""", re.IGNORECASE
)


class Route(StrEnum):
    """The installer that put a uv binary where it is -- the one that may move it."""

    WINGET = 'winget'
    STANDALONE = 'standalone'


def route_of(uv: str) -> Route:
    """Which installer owns the uv at *uv*: WinGet when the path runs through its tree, else uv's own."""
    parts = [part.lower() for part in PurePath(uv.replace('\\', '/')).parts]
    return Route.WINGET if 'winget' in parts else Route.STANDALONE


def update_argv(uv: str, version: str) -> list[str]:
    """The one command that moves the uv at *uv* to EXACTLY *version*, through the route it was installed by."""
    if route_of(uv) is Route.WINGET:
        return [
            'winget', 'install', '--id', WINGET_ID, '--exact', '--version', version, '--force', '--silent',
            '--disable-interactivity', '--accept-package-agreements', '--accept-source-agreements',
        ]  # fmt: skip
    return [uv, 'self', 'update', version]


def follow(
    uv: str,
    version: str,
    *,
    version_of: Callable[[str], str],
    run: Callable[..., Report] | None = None,
) -> str:
    """Move the uv at *uv* to *version* when it is another; ``''`` when it is *version* now, else why it is not.

    *version_of* reads what a uv binary says it is; *run* is the retried network door, absent
    :func:`~dev_lab.dev.netverb.run_network_verb` read at the call (a test injects both, or replaces that one).
    """
    found = version_of(uv)
    if found == version:
        return ''
    argv = update_argv(uv, version)
    door = run or run_network_verb
    report = door(argv, timeout=_UPDATE_TIMEOUT_S)
    package = held_package(report)
    if package is not None:
        sweep(package)
        move_aside(package)
        report = door(argv, timeout=_UPDATE_TIMEOUT_S)
    now = version_of(uv)
    if now == version:
        return ''
    said = '' if report.ok else f': {report.remedy}'
    return f'uv {found or "(unreadable)"} at {uv} did not follow to {version} through `{" ".join(argv)}`{said}'


def held_package(report: Report) -> Path | None:
    """The WinGet uv package directory a ``file-held`` refusal in *report* names; ``None`` for any other answer."""
    if report.ok or report.diagnosis is not Diagnosis.FILE_HELD:
        return None
    output = report.attempts[-1].output if report.attempts else ''
    found = _HELD_DIR.search(output)
    return Path(found['dir']) if found else None


def move_aside(package: Path) -> tuple[Path, ...]:
    """Rename each uv executable in *package* to ``<name><ASIDE>`` so an installer can write a new one; the moved."""
    moved = []
    for name in _EXECUTABLES:
        exe = package / name
        if exe.is_file():
            target = exe.with_name(name + ASIDE)
            exe.replace(target)
            moved.append(target)
    return tuple(moved)


def sweep(package: Path) -> tuple[Path, ...]:
    """Delete the executables :func:`move_aside` left in *package* that nothing holds now; the ones still held."""
    still = []
    for aside in package.glob(f'*{ASIDE}') if package.is_dir() else ():
        try:
            aside.unlink()
        except PermissionError:
            still.append(aside)
    return tuple(still)


def _parts(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split('.'))


def due(pinned: str, newest: str, policy: str) -> str:
    """The uv the pin should be at under *policy* (:data:`POLICIES`): *newest* when it moves, else *pinned*.

    ``minor`` moves only when *newest* is a newer ``major.minor``; ``patch`` on any newer release.
    """
    if policy not in POLICIES:
        msg = f'uv follow policy {policy!r} is none of {", ".join(POLICIES)}'
        raise ValueError(msg)
    width = 2 if policy == 'minor' else 3
    return newest if _parts(newest)[:width] > _parts(pinned)[:width] else pinned


def lag(pinned: str, newest: str, policy: str) -> str:
    """Why the *pinned* uv lags the *newest* release under *policy*, one sentence; ``''`` when it does not."""
    if due(pinned, newest, policy) == pinned:
        return ''
    return f'the uv pin {pinned} lags the newest release {newest} ({policy} policy)'
