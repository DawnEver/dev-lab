"""The process manager for a host that runs systemd -- which is every host this family deploys to.

THE CEILING IS THE REASON THIS EXISTS. ``run_capped`` runs a one-off command IN THE BOX
(:func:`lab_commons.box.command`): admitted on the machine's one ledger at :data:`CAPPED_CPU` core, its
memory ceiling and its timeout as the wall, and held there by the box's own scope -- a cgroup of its own.
That matters because the alternative -- spawning a child from the supervisor -- puts it in the
SUPERVISOR's cgroup, where the limit it lands under is the wrong one and where killing it is
indistinguishable from killing the supervisor. A candidate build that forks is exactly the load that took
this family's host down once already. Where the box cannot enforce, it refuses, and the command reports
that refusal rather than running unbounded. The box's decision is read from its RECORD (``--outcome``, a
temporary file removed once read), never from the exit code, which is the command's own: a refused, killed
or crashed box is reported as ``-1`` naming why (:func:`judged`).

The commands are built and then run through an injected runner, so what a manager WOULD execute is
assertable without a systemd on the machine running the test.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

import lab_commons.launch as _door
from lab_commons.box import Refused, command, read_ended
from lab_commons.compute.model import Demand

from dev_lab.supervise.notify import NOTIFY_SOCKET
from dev_lab.supervise.process.base import Ran

__all__ = [
    'CAPPED_CPU',
    'CAPPED_QUEUE_S',
    'OUTPUT_CAP',
    'Runner',
    'SystemdProcessManager',
    'ceiling_gb',
    'judged',
    'subprocess_runner',
]

#: Run an argv and report what it produced. Injected so a test can read the command rather than
#: execute it.
Runner = Callable[[list[str], int, 'str | None'], Ran]

#: How much of a command's output is kept, per stream. Generous for a log line and small enough
#: that a runaway command cannot take the supervisor's own cgroup with it.
OUTPUT_CAP: Final = 64 * 1024

#: How long a subprocess is given beyond the ceiling the command itself carries. The box's wall kills
#: the command; this is the backstop for the box machinery not coming up.
_GRACE: Final = 15

#: The cores a one-off command declares to the box: a probe, a fetch or a build, never the box's width.
CAPPED_CPU: Final = 1

#: How long a one-off command waits for room in the box before it is refused, in seconds.
CAPPED_QUEUE_S: Final = 120

#: A memory ceiling's binary suffixes, in GB (``600M`` is 600 MiB).
_SUFFIX_GB: Final = {'K': 2.0**-20, 'M': 2.0**-10, 'G': 1.0, 'T': 2.0**10}


def ceiling_gb(memory_max: str) -> float:
    """*memory_max* (``600M``, ``2G``) in GB; a ceiling with no binary suffix is refused by name."""
    number, suffix = memory_max[:-1], memory_max[-1:].upper()
    if suffix not in _SUFFIX_GB or not number.replace('.', '', 1).isdigit():
        msg = f'a memory ceiling is a number with a K/M/G/T suffix (600M), got {memory_max!r}'
        raise ValueError(msg)
    return float(number) * _SUFFIX_GB[suffix]


def subprocess_runner(argv: list[str], timeout: int, cwd: str | None) -> Ran:
    """Run *argv*, capturing both streams, and never raise for a failing command.

    Args:
        argv: the command and its arguments.
        timeout: seconds to allow.
        cwd: working directory, or None for the caller's.

    Returns:
        What the command produced, with -1 for a timeout.

    """
    # OUTPUT GOES TO DISK AND ONLY A PREFIX COMES BACK, because `capture_output=True` collects the
    # whole thing into THIS process's memory -- and this process is the supervisor, whose own
    # cgroup is 300M. The command runs inside a scope the kernel bounds (the candidate build under
    # 600M); a command that emits 500MB, or a compiler that reports ten thousand errors, would blow
    # the SUPERVISOR's ceiling instead and take the thing doing the supervising with it.
    #
    # A capped prefix is what every caller wants anyway: `Ran.detail` keeps 200 characters for a
    # log line, and the numeric probes parse a leading token. Nothing reads the middle of a build
    # log. The full output still lands on disk, bounded by the command's own timeout.
    #
    # AND THE CHILD DOES NOT GET THE MANAGER'S NOTIFY SOCKET. Every fork the supervisor makes goes
    # through here -- the probes, the fetches, the candidate build, `systemd-run` itself -- and every
    # one of them would otherwise inherit `$NOTIFY_SOCKET` and be able to speak AS THE SUPERVISOR.
    # Measured on the host on 2026-10-03, the moment the watchdog went live: notification messages
    # arriving from CHILD pids, rejected only because `NotifyAccess=main` is the default. Widen that
    # to `all` -- the permissive-looking setting -- and a subprocess would satisfy the check-in that
    # exists to prove THE DAEMON is still working, which is not a watchdog. Removing the variable is
    # the one-place fix for the whole class, and it does not depend on knowing which child it was:
    # the journal names a pid, and the pid is gone by the time anybody reads it.
    environment = {key: value for key, value in os.environ.items() if key != NOTIFY_SOCKET}
    try:
        with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
            done = _door.run(argv, stdout=out, stderr=err, timeout=timeout, cwd=cwd, check=False, env=environment)
            out.seek(0)
            err.seek(0)
            kept_out = out.read(OUTPUT_CAP).decode('utf-8', 'replace')
            kept_err = err.read(OUTPUT_CAP).decode('utf-8', 'replace')
    except subprocess.TimeoutExpired:
        return Ran(code=-1, err=f'timed out after {timeout}')
    except OSError as exc:
        return Ran(code=-1, err=f'could not run {argv[0]}: {exc}')
    return Ran(code=done.returncode, out=kept_out, err=kept_err)


@dataclass(frozen=True)
class SystemdProcessManager:
    """Drive a service through ``systemctl``, and bound one-off work through ``systemd-run``.

    Attributes:
        systemctl: the control binary. Injectable for a host that spells it elsewhere.
        systemd_run: the transient-unit binary.
        runner: how a built command is executed.

    """

    systemctl: str = 'systemctl'
    systemd_run: str = 'systemd-run'
    runner: Runner = field(default=subprocess_runner)
    name: str = 'systemd'

    def is_active(self, unit: str) -> bool:
        """Report whether *unit* is running.

        Args:
            unit: the systemd unit name.

        Returns:
            True when ``systemctl is-active`` exits zero.

        """
        return self.runner([self.systemctl, 'is-active', unit], 30, None).ok

    def ask_active(self, unit: str) -> Ran:
        """Ask whether *unit* is running, and keep the difference between no and don't know.

        `is_active` answers a bool, which is what its callers want -- but a bool cannot carry "the
        command could not be run at all", and `systemctl` exits 3 for inactive and 4 for a unit that
        does not exist while this module marks "could not run" as -1. Collapsing those three into
        False is what let `stop_unit` report success on a unit it never stopped.

        Args:
            unit: the systemd unit name.

        Returns:
            What systemctl said.

        """
        return self.runner([self.systemctl, 'is-active', unit], 30, None)

    def start(self, unit: str) -> Ran:
        """Start *unit*.

        Args:
            unit: the systemd unit name.

        Returns:
            What systemctl said.

        """
        return self.runner([self.systemctl, 'start', unit], 120, None)

    def stop(self, unit: str) -> Ran:
        """Stop *unit*.

        Args:
            unit: the systemd unit name.

        Returns:
            What systemctl said.

        """
        return self.runner([self.systemctl, 'stop', unit], 120, None)

    def restart(self, unit: str) -> Ran:
        """Restart *unit*.

        Args:
            unit: the systemd unit name.

        Returns:
            What systemctl said.

        """
        return self.runner([self.systemctl, 'restart', unit], 180, None)

    def start_capped(
        self,
        argv: list[str],
        *,
        memory_max: str,
        name: str,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
    ) -> Ran:
        """Start a transient unit carrying a memory ceiling.

        ``--collect`` so a unit that exits is garbage-collected rather than left as a failed unit
        for the next ``systemctl list-units`` to explain.

        Args:
            argv: the command and its arguments.
            memory_max: the ceiling, e.g. ``600M``.
            name: the unit's name.
            cwd: working directory, or None for the caller's.
            env: extra environment for the process.

        Returns:
            What systemd-run said.

        """
        command = [
            self.systemd_run,
            f'--unit={name}',
            '--collect',
            '--quiet',
            f'--property=MemoryMax={memory_max}',
        ]
        if cwd:
            command.append(f'--working-directory={cwd}')
        for key, value in (env or {}).items():
            command.append(f'--setenv={key}={value}')
        command.extend(['--', *argv])
        return self.runner(command, 60, None)

    def stop_unit(self, name: str) -> Ran:
        """Stop a transient unit by name.

        Args:
            name: the unit's name.

        Returns:
            What systemctl said. A unit that is already gone is stopped.

        """
        probe = self.ask_active(name)
        if probe.code == -1:
            # COULD NOT ASK IS NOT ALREADY GONE. Reporting success here leaves a candidate's
            # transient unit alive, holding the spare port every later candidate is started on.
            return Ran(code=-1, err=f'could not ask whether {name} is running: {probe.err}')
        if probe.code != 0:
            return Ran(code=0, out='already gone')
        return self.runner([self.systemctl, 'stop', name], 120, None)

    def run_capped(self, argv: list[str], *, memory_max: str, timeout: int, cwd: str | None = None) -> Ran:
        """Run *argv* in the box under a memory ceiling (the module docstring).

        ``timeout`` is the claim's WALL, so the box kills the command's whole tree within its own
        cgroup: a ``timeout`` applied outside would leave the scope's processes running after the
        wrapper had gone.

        Args:
            argv: the command and its arguments.
            memory_max: the ceiling, e.g. ``600M``.
            timeout: seconds to allow the command.
            cwd: working directory, or None for the caller's.

        Returns:
            What the command produced.

        """
        demand = Demand(cpu=CAPPED_CPU, mem_gb=ceiling_gb(memory_max))
        what = f'supervise: {" ".join(argv)}'[:120]
        with tempfile.TemporaryDirectory(prefix='lab-supervise-box-') as scratch:
            record = Path(scratch) / 'outcome.json'
            boxed = command(
                argv, demand, timeout, CAPPED_QUEUE_S, key=f'supervise:{argv[0]}', what=what, outcome=record
            )
            return judged(self.runner(boxed, timeout + CAPPED_QUEUE_S + _GRACE, cwd), record)


def judged(ran: Ran, record: Path) -> Ran:
    """*ran* as the box recorded it at *record*: the command's own result, or ``-1`` naming a refusal, kill or crash.

    A runner that could not run the box at all (``-1``) is already a failure naming itself.
    """
    if ran.code == -1:
        return ran
    ended = read_ended(record)
    if isinstance(ended, Refused):
        return Ran(code=-1, out=ran.out, err=f'box refused: {ended}')
    if ended is None:
        return Ran(code=-1, out=ran.out, err=f'box crashed: no record of how it ended; {ran.err}'.strip())
    if ended.killed:
        return Ran(code=-1, out=ran.out, err=f'box killed it past its declared {ended.reason}; {ran.err}'.strip())
    return ran
