"""A CLUSTER SUBMIT RUNS IN ITS OWN PROCESS, under its own lock -- never inside the serve tick's ``flock``.

A submit fetches, builds and COLLECTS on the login node (:func:`lab_commons.hpc.run.submit_run`); a cold
``pytest --collect-only`` measured over an hour on Ada (2026-11-07). Inside the tick it held the cron line's
``flock -n``, so every tick behind it was skipped and finished runs waited to be gathered and posted. So the
tick DETACHES a run still to submit (:func:`detach`: ``forge serve --submit <run>``) and moves on; that process
takes the run's own lock (:func:`held`, ``<run>.submit`` beside the run file, ``O_EXCL`` -- GPFS-safe, unlike
``flock``) and advances that one run. While the lock is live (:func:`busy`) the tick leaves the run alone; a
lock older than :data:`STALE_LOCK_S` belongs to a submit that died, and the next one takes it over.
"""

from __future__ import annotations

import contextlib
import os
import subprocess
import sys
import time
from typing import TYPE_CHECKING, Any, Final

import lab_commons.launch as _door

from dev_lab.dev.forgerunstate import CLAIMED_PHASE, SUBMITTING, live, name_of, submit_lock
from dev_lab.dev.platformparts import run_tag

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Sequence
    from pathlib import Path

    from dev_lab.dev.forgerunstate import Run

__all__ = ['STALE_LOCK_S', 'TO_SUBMIT', 'busy', 'detach', 'detach_argv', 'hand_off', 'held', 'submit_one']

#: The phases whose next step is a submit -- a build and a collection on the login node.
TO_SUBMIT: Final = frozenset({CLAIMED_PHASE, SUBMITTING})

#: A submit lock this old belongs to a submit that died: a cold build plus collection is hours, never six.
STALE_LOCK_S: Final = 6 * 3600.0
#: Windows: no console window, its own process group, out of the parent's job (``subprocess`` names).
_DETACHED: Final = 0x08000000 | 0x00000200 | 0x01000000


def busy(run: Run, *, stale_s: float = STALE_LOCK_S) -> bool:
    """Whether a live submit of *run* holds its lock now."""
    try:
        return time.time() - submit_lock(run).stat().st_mtime <= stale_s
    except OSError:
        return False


@contextlib.contextmanager
def held(run: Run, *, stale_s: float = STALE_LOCK_S) -> Iterator[bool]:
    """Hold *run*'s submit lock for the block; yields ``False`` (holding nothing) while another live submit has it."""
    lock = submit_lock(run)
    lock.parent.mkdir(parents=True, exist_ok=True)
    for _ in range(2):
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            if busy(run, stale_s=stale_s):
                yield False
                return
            with contextlib.suppress(OSError):
                lock.unlink()  # a dead submit's: taken over
            continue
        os.write(fd, str(os.getpid()).encode('ascii'))
        os.close(fd)
        try:
            yield True
        finally:
            with contextlib.suppress(OSError):
                lock.unlink()
        return
    yield False


def detach_argv(run: Run) -> list[str]:
    """The command a detached submit of *run* runs: this kit's ``forge serve --submit <run>``."""
    return [sys.executable, '-P', '-m', 'dev_lab.dev.forge', 'serve', '--submit', name_of(run)]


def detach(root: Path, run: Run, *, spawn: Callable[..., Any] = _door.popen) -> str:
    """Start *run*'s submit in its own process in *root*'s checkout and return at once; one line saying so.

    The child inherits stdout and stderr (its lines land in the tick's log) and no other descriptor, so it
    never holds the tick's ``flock``.
    """
    options: dict[str, Any] = {'creationflags': _DETACHED} if os.name == 'nt' else {'start_new_session': True}
    child = spawn(detach_argv(run), cwd=root, stdin=subprocess.DEVNULL, close_fds=True, **options)
    return f'submit detached (pid {child.pid}): {name_of(run)}'


def hand_off(
    runs: Sequence[Run], submit: Callable[[Run], str] | None, say: Callable[[str], None]
) -> tuple[list[Run], list[str]]:
    """RESULTS BEFORE SUBMITS: (the runs the tick advances itself, the shas handed away) for one tick.

    Every run already submitted goes before every run still to submit, each side in its given order. Given
    *submit*, a run still to submit is not the tick's at all: it goes to its own process, or is left alone
    while a live submit holds its lock. ``None`` keeps every run inline (the ``--submit`` process itself).
    """
    ordered = sorted(runs, key=lambda run: run.phase in TO_SUBMIT)  # stable: each side keeps its order
    if submit is None:
        return ordered, []
    handed = [run for run in ordered if run.phase in TO_SUBMIT]
    for run in handed:
        tag = run_tag(run.platform, run.sha)
        say(f'{tag}: submitting in its own process' if busy(run) else f'{tag}: {submit(run)}')
    return [run for run in ordered if run.phase not in TO_SUBMIT], [run.sha for run in handed]


def submit_one(repo: str, name: str, advance: Callable[[Run], object], say: Callable[[str], None]) -> int:
    """``serve --submit <run>``: *advance* the one run file *name* of *repo* under its submit lock; 0.

    Another live submit of it, or no such run left, is a no-op.
    """
    run = next((one for one in live(repo) if name_of(one) == name), None)
    if run is None:
        say(f'[submit] {name}: no such run in flight; nothing to submit')
        return 0
    with held(run) as mine:
        if not mine:
            say(f'[submit] {name}: another submit holds it')
            return 0
        advance(run)
    return 0
