"""What it means to reach a service's process, with nothing said about who manages it.

A supervisor has to restart a service, ask whether it is up, and run a one-off command under a
resource limit. The predecessor did all three by hosting the process ITSELF -- freeing a port,
spawning a detached child, reconnect-polling to see whether it had bound -- because it assumed the
machine had no service manager. That assumption is wrong on every host this family deploys to, and
it costs the memory discipline: a process the supervisor spawned has no cgroup, so it has no
``MemoryMax``, and on a small box the difference between a capped child and an uncapped one is
whether the host survives.

So the manager is a seam. This module states the four things a deploy engine may ask for and
nothing else -- no ``systemctl``, no ``sc.exe``, no port arithmetic.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

__all__ = ['ProcessManager', 'Ran']


@dataclass(frozen=True)
class Ran:
    """What running a command produced.

    Attributes:
        code: the command's exit status, or -1 when it was killed for running too long.
        out: its standard output, decoded.
        err: its standard error, decoded, which is where a refusal usually explains itself.

    """

    code: int
    out: str = ''
    err: str = ''

    @property
    def ok(self) -> bool:
        """Return whether the command succeeded.

        Returns:
            True when the exit status was zero.

        """
        return self.code == 0

    def detail(self) -> str:
        """Return the first line of output that says anything, for a log line.

        Returns:
            The trimmed standard error when there is one, else the trimmed standard output,
            else a note that the command said nothing.

        """
        for text in (self.err, self.out):
            stripped = text.strip()
            if stripped:
                return stripped.splitlines()[0][:200]
        return f'exit {self.code} with no output'


@runtime_checkable
class ProcessManager(Protocol):
    """The four questions a deploy engine may ask of whatever runs a service.

    A manager is looked up once by name and used for the life of a run. Implementations raise
    nothing for an ordinary failure -- a service that would not restart returns a failing
    :class:`Ran`, because a refusal is an outcome to report, not an exception to unwind.
    """

    name: str

    def is_active(self, unit: str) -> bool:
        """Report whether *unit* is running.

        Args:
            unit: the service's name under this manager.

        Returns:
            True when the manager reports it running.

        """
        ...

    def start(self, unit: str) -> Ran:
        """Start *unit*.

        Args:
            unit: the service's name.

        Returns:
            What the manager said.

        """
        ...

    def stop(self, unit: str) -> Ran:
        """Stop *unit*.

        Args:
            unit: the service's name.

        Returns:
            What the manager said.

        """
        ...

    def restart(self, unit: str) -> Ran:
        """Restart *unit*.

        Args:
            unit: the service's name.

        Returns:
            What the manager said.

        """
        ...

    def start_capped(
        self,
        argv: list[str],
        *,
        memory_max: str,
        name: str,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
    ) -> Ran:
        """Start a long-running command under a memory ceiling, detached.

        The candidate gate needs this and nothing else does: a release is proven by STARTING it
        beside the live one and asking it questions, which cannot be done with a runner that waits
        for the process to finish. Detached rather than backgrounded so the ceiling outlives the
        call that made it.

        Args:
            argv: the command and its arguments.
            memory_max: the ceiling, in the manager's own spelling.
            name: what to call the started thing, so it can be stopped by name -- and so a
                leftover from a crash is identifiable rather than anonymous.
            cwd: working directory, or None for the caller's.
            env: extra environment for the process.

        Returns:
            What starting it said. A manager that cannot run things detached says so in *err*
            rather than pretending it started one.

        """
        ...

    def stop_unit(self, name: str) -> Ran:
        """Stop something :meth:`start_capped` started.

        Args:
            name: the name it was started under.

        Returns:
            What stopping it said. Stopping something already gone is a success, not a failure: a
            cleanup path that fails on a crashed candidate is a cleanup path that leaves litter.

        """
        ...

    def run_capped(self, argv: list[str], *, memory_max: str, timeout: int, cwd: str | None = None) -> Ran:
        """Run a one-off command under a memory ceiling.

        The ceiling is the point: a candidate build, an import probe or a migration is exactly the
        kind of work that forks and blows up on a small host, and it must be bounded by something
        the kernel enforces rather than by a number in a comment.

        Args:
            argv: the command and its arguments.
            memory_max: the ceiling, in the manager's own spelling (``600M`` for a cgroup).
            timeout: seconds to allow before killing the command.
            cwd: working directory, or None for the caller's.

        Returns:
            What the command produced. A manager that cannot enforce a ceiling says so in *err*
            rather than pretending it did.

        """
        ...
