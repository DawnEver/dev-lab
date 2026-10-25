"""The always-on loop: run a cycle, wait, run another, until told to stop.

A SUPERVISOR DOES NOT MANAGE ITSELF. There is no pid file here and no self-restart ladder, because
the kit's own rule is that a second lock is a second definition of the one that exists, and because
a process supervised by a process manager has no business supervising itself. Under systemd the
unit carries ``Restart=always``; the liveness question is answered by the manager, and it is asked
of the OS rather than of a timestamp this module wrote down.

WHAT THIS DOES OWN is the two things a loop must get right and a timer cannot: it does not overlap
itself, and it stops when asked. A cycle that finds the seat taken SKIPS rather than fails, because
the other cycle is the one doing the work. A signal sets a flag and the cycle in flight finishes
first, so a restart never lands mid-remedy -- a systemd restart that interrupted a deployment would
leave the target in a state no later cycle knows about.

AND IT IS WHERE A STALE SUPERVISOR FINDS OUT IT IS STALE, which the paragraph above cannot cover. A
deployment installs its own units and can upgrade the kit this process runs from -- and a Python
process goes on executing the modules it imported at startup no matter what lands on disk
underneath it. Measured on 2026-10-03: a kit fix was deployed, the daemon kept running the previous
one, and two cycles of evidence were recorded under the OLD rules before anybody restarted it by
hand. :func:`definition_signature` says what is compared; :attr:`Loop.definition` says what happens
when it moves, and the answer is that the loop EXITS.

EXITING IS THE POINT, NOT A WORKAROUND. Asking the manager to replace us and replacing ourselves
are different acts: the first is a process supervised by a process manager behaving correctly, the
second is the self-restart ladder this module's first paragraph refuses. And it cannot be done from
inside anyway -- a restart issued by the process halfway through writing this cycle's state would
kill the writer, and the deployment would be unrecorded.

WHAT IT DOES NOT DO IS DECIDE WHERE RECORDS GO. The loop hands each cycle's result to a callback
and the entry point chooses the journal, which keeps the digest's writer in one place instead of
having this module grow an opinion about files.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import signal
import threading
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from types import FrameType
from typing import Any, Final

from lab_commons.box import Refused
from lab_commons.log import emit

from dev_lab.supervise import notify
from dev_lab.supervise.alert import Notifier
from dev_lab.supervise.component import Registry
from dev_lab.supervise.loop import CycleResult, run_cycle
from dev_lab.supervise.policy import now
from dev_lab.supervise.process.base import ProcessManager
from dev_lab.supervise.report import summary
from dev_lab.supervise.state import StateStore

__all__ = ['MIN_INTERVAL', 'Definition', 'Loop', 'definition_signature', 'serve']

#: The shortest interval a loop will honour. Anything smaller is a supervisor competing with the
#: service it supervises, which on a two-core host is the service losing.
MIN_INTERVAL: Final = 5

#: What a cycle's result is handed to, for a caller that wants to record it.
Watcher = Callable[[CycleResult, datetime], None]

#: A signature of WHAT THIS PROCESS LOADED, re-taken from disk. A callable rather than a value,
#: because the whole question is whether the disk still agrees with the process.
Definition = Callable[[], str]

#: The distribution this module is published in. Named rather than derived from ``__package__``
#: because the point is to compare the process against the INSTALLED artefact, and a source tree
#: that was never installed has no version to compare at all.
_DISTRIBUTION: Final = 'dev-lab'


def definition_signature(project: Path, paths: Sequence[str]) -> str:
    """A signature over the things this process cannot pick up by re-reading them.

    Two ingredients, and they are the two ways a deployment replaces a running supervisor:

    * **The kit's own installed version.** A deployment that upgrades this package puts new modules
      on disk, and the running process keeps the old ones until it is replaced.
    * **The content of the named files.** A unit file is read by the manager at start; a config the
      unit points at is read by whoever reads it. Neither reaches a process already running.

    A MISSING FILE IS A FACT AND NOT AN EMPTY ONE. A path that cannot be read records
    ``<unreadable>`` rather than nothing, so a deployment that DELETED a file is a change like any
    other -- reporting it as absent would make the one case that most needs a replace the one case
    that looks like no change at all.

    Args:
        project: the target's directory, which the named paths are relative to.
        paths: the files that are part of this process's definition.

    Returns:
        A signature, stable while nothing that matters has moved.

    """
    parts = [f'kit={_installed_version()}']
    for name in paths:
        try:
            digest = hashlib.sha256((project / name).read_bytes()).hexdigest()[:16]
        except OSError as exc:
            # THE REASON TRAVELS, because "unreadable" alone sends the next reader looking for a
            # permissions problem when the usual cause is that the file is not there any more.
            digest = f'<{type(exc).__name__}>'
        parts.append(f'{name}={digest}')
    return '|'.join(parts)


def _installed_version() -> str:
    """Return the installed version of this kit, or a marker saying there is not one.

    Returns:
        The version string, or ``uninstalled`` for a source tree that was never installed.

    """
    try:
        return importlib.metadata.version(_DISTRIBUTION)
    except importlib.metadata.PackageNotFoundError:
        return 'uninstalled'


@dataclass
class Loop:
    """Everything one running supervisor holds.

    Attributes:
        registry: the components, actions and chains.
        store: where state lives.
        config: the merged configuration.
        project: the target's directory.
        manager: how a remedy reaches the service's process.
        notifier: how a notice is delivered. Defaults to one over the merged config.
        stop: set to ask the loop to finish the cycle in flight and return.
        definition: what this process loaded, re-taken from disk each cycle. When it moves, the
            cycle in flight finishes and the loop returns, for the manager to replace. None in a
            caller that runs a cycle at a time, where there is no process to go stale.

    """

    registry: Registry
    store: StateStore
    config: dict[str, Any]
    project: Path
    manager: ProcessManager
    notifier: Notifier | None = None
    stop: threading.Event = field(default_factory=threading.Event)
    definition: Definition | None = None

    def interval(self) -> int:
        """Return how long to wait between cycles.

        Returns:
            The configured interval, floored at :data:`MIN_INTERVAL`.

        """
        return max(MIN_INTERVAL, int(self.config.get('cycle', {}).get('interval', 300)))

    def once(self, clock: datetime | None = None) -> CycleResult | None:
        """Run one cycle, or skip it because another holds the seat.

        Args:
            clock: the instant to judge this cycle at. Defaults to the real one.

        Returns:
            The cycle's result, or None when another cycle held the seat -- a skip is not a
            failure, because the other cycle is the one doing the work.

        """
        try:
            return run_cycle(
                self.registry,
                self.store,
                self.config,
                self.project,
                self.manager,
                clock=clock or now(),
                notifier=self.notifier,
            )
        except Refused as exc:
            emit(f'supervise: skipped, another cycle holds this target ({exc})', flush=True)
            return None

    def cycles(self, clock: Callable[[], datetime] | None = None) -> Iterator[CycleResult]:
        """Yield one cycle at a time until the stop flag is set.

        Args:
            clock: a callable returning the instant to judge each cycle at. Defaults to the real
                one; a test passes its own rather than freezing the process's.

        Yields:
            Each cycle that ran, in order. A skipped cycle yields nothing.

        """
        tick = clock or now
        loaded = self.definition() if self.definition is not None else ''
        while not self.stop.is_set():
            result = self.once(tick())
            if result is not None:
                yield result
            # CHECKED AFTER THE CYCLE, NEVER DURING ONE. Everything this cycle measured has been
            # written and handed to the journal by the time `once` returns, so the replace lands on
            # a process with nothing in flight.
            if self.definition is not None and self.definition() != loaded:
                emit(
                    'supervise: what this process loaded has changed on disk -- finishing here and '
                    'exiting, for the manager to start a supervisor that reads the new definition',
                    flush=True,
                )
                self.stop.set()
                return
            self.stop.wait(self.interval())


@contextmanager
def _stopping(loop: Loop) -> Iterator[Loop]:
    """Set *loop*'s stop flag when the process is asked to terminate.

    SIGTERM and SIGINT are handled so a restart finishes the cycle in flight instead of landing
    mid-remedy.

    Args:
        loop: the loop to stop.

    Yields:
        The same loop.

    """
    previous: dict[int, signal.Handlers] = {}

    def request_stop(_signum: int, _frame: FrameType | None) -> None:
        loop.stop.set()

    for signum in (signal.SIGTERM, signal.SIGINT):
        previous[signum] = signal.getsignal(signum)
        signal.signal(signum, request_stop)
    try:
        yield loop
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)


def serve(
    loop: Loop,
    *,
    once: bool = False,
    on_cycle: Watcher | None = None,
    clock: Callable[[], datetime] | None = None,
) -> int:
    """Run *loop* until stopped, reporting each cycle as it happens.

    Args:
        loop: the loop to run.
        once: run a single cycle and return, for a timer-driven deployment with no daemon.
        on_cycle: called with each cycle's result and the instant it ran, for a caller that keeps
            a journal. The loop itself has no opinion about where records go.
        clock: a callable returning the instant to judge each cycle at.

    Returns:
        The number of cycles that found something wrong, which is what an exit status should carry.

    """
    tick = clock or now
    degraded = 0
    with _stopping(loop) as running:
        # WHETHER THE MANAGER IS WATCHING IS SAID OUT LOUD ONCE, AT THE TOP, because the two answers
        # are different facts and only one of them is reassurance. Under `Type=notify` a failure to
        # arrive here is a failure to start; in a foreground run there is simply nobody listening,
        # and a daemon that reported a check-in it never made would be the worst of the three.
        if notify.ready():
            emit('supervise: the manager was told this process is up', flush=True)
        else:
            emit('supervise: no notify socket -- nothing is watching this process but its own log', flush=True)
        for result in running.cycles(tick):
            at = tick()
            # THE CHECK-IN GOES WITH THE LOG LINE, once per cycle, so `WatchdogSec=` measures the
            # same thing the reader sees. It is sent even for a DEGRADED cycle: the question the
            # manager is asking is whether this process is still working, not whether the target is.
            notify.watchdog()
            # FLUSHED. A DAEMON'S LOG THAT IS BUFFERED IS NOT A LOG, and `emit` does not flush by
            # default -- right for a command that exits, wrong for one that never does. Its stdout
            # is a pipe to the journal, so the default is block buffering and one short line every
            # few minutes leaves the buffer days from filling. Measured on the host: every
            # `supervise:` line appeared in the journal in the same second as a restart, because
            # the restart was the only thing that flushed it. A healthy daemon was
            # indistinguishable from one that had never run.
            emit(f'supervise: {summary(result)}', flush=True)
            if result.status != 'healthy':
                degraded += 1
            if on_cycle is not None:
                on_cycle(result, at)
            if once:
                running.stop.set()
    return degraded
