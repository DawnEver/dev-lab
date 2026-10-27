"""ONE ``forge serve`` PER HOST: an exclusive, non-blocking lock, and the notes a stopped producer leaves.

A scheduler fires a serve every few minutes whether or not the last one finished, so the serve itself
refuses to overlap: :func:`held` takes an OS lock on *path* without waiting -- ``msvcrt.locking`` on
Windows, ``fcntl.flock`` elsewhere (the same lock ``flock -n`` takes on a cluster's crontab line) -- and
yields ``False`` when another process holds it. ``forge serve --lock [PATH]`` is :func:`locked` around the
serve's own entry: a second serve on a held lock exits 0 having done nothing, and says so. The OS drops
the lock when its holder dies, however it dies, so a killed serve never leaves a stale lock behind.

THE FORGE HOME is per user, because the forge credential and a vendor's scheduler are, and it is the
platform data dir -- never a user-visible directory beside the dev repos (user ruling 2026-10-26):
``%LOCALAPPDATA%/lab-forge`` on Windows, ``${XDG_DATA_HOME:-~/.local/share}/lab-forge`` elsewhere.
:func:`forge_home` is the ONE place it is named; the lock, the log, the stop notes and the serve
checkouts (``<forge home>/repos/<repo>``) all derive from it.

A STOP NOTE says a producer was stopped on purpose (:mod:`dev_lab.dev.stoprun`), so the serve that
spawned it releases the claim as ``error: stopped`` rather than as a crash; :func:`was_stopped` reads
a note once and deletes it.
"""

from __future__ import annotations

import argparse
import contextlib
import os
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path

from lab_commons.log import emit

__all__ = ['default_lock', 'forge_home', 'held', 'locked', 'note_stopped', 'was_stopped']


def forge_home() -> Path:
    """The forge's machine home: ``%LOCALAPPDATA%/lab-forge``, else ``${XDG_DATA_HOME:-~/.local/share}/lab-forge``."""
    nt = os.name == 'nt'
    data = os.environ.get('LOCALAPPDATA' if nt else 'XDG_DATA_HOME')
    return (Path(data) if data else Path.home() / ('AppData/Local' if nt else '.local/share')) / 'lab-forge'


def default_lock() -> Path:
    """The per-user serve lock, in the :func:`forge_home`."""
    return forge_home() / 'serve.lock'


def _try_lock(fd: int) -> bool:
    if os.name == 'nt':
        import msvcrt  # noqa: PLC0415 -- Windows only

        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        except OSError:
            return False
        return True
    import fcntl  # noqa: PLC0415 -- POSIX only

    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False
    return True


@contextlib.contextmanager
def held(path: Path) -> Iterator[bool]:
    """Hold the lock at *path* for the block; yields ``False`` (and holds nothing) when another process has it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        yield _try_lock(fd)
    finally:
        os.close(fd)  # closing the descriptor releases the lock on both platforms


def locked(argv: Sequence[str], run: Callable[[list[str]], int]) -> int:
    """``run(rest)`` -- under the lock ``--lock [PATH]`` names (bare: :func:`default_lock`), else 0 doing nothing."""
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--lock', type=Path, nargs='?', const=default_lock())
    args, rest = parser.parse_known_args(list(argv))
    if args.lock is None:
        return run(rest)
    with held(args.lock) as mine:
        if not mine:
            emit(f'[serve] another forge serve holds {args.lock}; this one does nothing', err=True)
            return 0
        return run(rest)


def _notes(root: Path | None) -> Path:
    return (forge_home() if root is None else root) / 'stopped'


def note_stopped(pid: int, *, root: Path | None = None) -> None:
    """Record that *pid* is being stopped on purpose."""
    notes = _notes(root)
    notes.mkdir(parents=True, exist_ok=True)
    (notes / str(pid)).touch()


def was_stopped(pid: int, *, root: Path | None = None) -> bool:
    """Whether *pid* was stopped on purpose; the note is consumed."""
    note = _notes(root) / str(pid)
    try:
        note.unlink()
    except FileNotFoundError:
        return False
    return True
