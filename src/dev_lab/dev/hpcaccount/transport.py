"""THE ONE TRANSPORT every hpcaccount remote step takes, chosen per dest: the HELD session, else key-only ssh.

A login host that asks a second factor (key + keyboard-interactive TOTP) can never be reached by
``ssh -o BatchMode=yes``; the user's code opens a held session for it instead
(``python -m dev_lab.dev.sshhold open <dest> --hours H``, :mod:`dev_lab.dev.sshhold`). So for each ``user@host``:

* a session recorded for *dest* whose holder answers a ping -> every command rides it
  (:func:`dev_lab.dev.sshholdrun.run_command`, audited by sshhold as every ``run`` is);
* a session recorded but its holder silent -> REFUSED by name (:class:`HoldRefused`), never a silent re-auth and
  never a fall back to ssh;
* no session recorded -> the existing key-only ssh (:func:`lab_commons.hpc.cluster.ssh_runner`,
  :func:`dev_lab.dev.remote.detached`); a host that answers ``Permission denied (keyboard-interactive)`` there is
  refused naming the door: open the held session first.

BEFORE ANY OF IT, this machine's declared reach of the cluster (:func:`lab_commons.hpc.reach.require`): a cluster
this machine declares no ``[dev] hpc_reach`` for is refused, no ssh attempted -- a held session included.

:func:`grant_runner` / :func:`host_runner` are the reads (a :data:`Runner`), :func:`start` is the deploy-fleet launch.
"""

from __future__ import annotations

import shlex
import subprocess
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import IO, Any, Final, Protocol

from lab_commons.hpc.cluster import CONNECT_TIMEOUT, Runner, Unreachable, failover_runner, ssh_runner
from lab_commons.hpc.grants import Grant

from dev_lab.dev import remote, sshholdrun, sshholdstate, sshholdwire
from dev_lab.dev.sshholdwire import HoldRefused

__all__ = [
    'DEPLOY_S', 'PROBE_S', 'TAIL', 'HoldRefused', 'Started', 'describe', 'door', 'grant_runner', 'held', 'host_runner',
    'ordered_targets', 'outcomes', 'start',
]  # fmt: skip

#: How long one deploy may take on a held session (it runs in the foreground there: the holder owns the stream).
DEPLOY_S: Final = 3600.0
#: What ssh says when a host wanted a second factor that BatchMode cannot type.
_SECOND_FACTOR: Final = 'keyboard-interactive'
_TIMEOUT: Final = 300.0
#: How long a failover host may take to answer ``true`` before it is skipped: ssh's connect bound plus a login shell.
PROBE_S: Final = CONNECT_TIMEOUT + 15.0


def require(dest: str) -> None:
    """Refuse *dest* when it is a declared cluster's login host and this machine declares no reach of it."""
    from lab_commons.hpc.reach import require as declared  # noqa: PLC0415 -- every kit import must not need it yet

    declared(dest)


def door(dest: str) -> str:
    """The door a second-factor host needs before any step can reach it."""
    return f"open it first: python -m dev_lab.dev.sshhold open {dest} --hours H (the user's code)"


def held(dest: str) -> bool:
    """Whether *dest* has a LIVE held session; a recorded one whose holder is silent is refused by name."""
    session = sshholdstate.read_session(dest)
    if session is None:
        return False
    if not sshholdwire.ping(session):
        msg = f'the held session of {dest} is recorded but its holder does not answer, never re-authenticated: '
        msg += door(dest)
        raise HoldRefused(msg)
    return True


def _held_runner(dest: str, timeout: float) -> Runner:
    def run(command: str, stdin: str | None = None) -> str:
        data = None if stdin is None else stdin.encode('utf-8')
        output, status = sshholdrun.run_command(dest, command, timeout, stdin=data)
        if status:
            said = output.strip() or '(no output)'
            msg = f'{dest} (held session) exited {status} running `{command}`: {said}'  # the token is never argv
            raise RuntimeError(msg)
        return output

    return run


def _ssh(dest: str, timeout: float) -> Runner:
    """Key-only ssh to *dest*; a second-factor refusal names the held-session door instead of the bare ssh error."""
    plain = ssh_runner(dest, timeout)

    def run(command: str, stdin: str | None = None) -> str:
        try:
            return plain(command, stdin)
        except RuntimeError as refused:
            if _SECOND_FACTOR in str(refused):
                msg = f'{dest} asks a second factor and no session is held: ' + door(dest)
                raise HoldRefused(msg) from refused
            raise

    return run


def host_runner(dest: str, timeout: float = _TIMEOUT) -> Runner:
    """A runner pinned to *dest* (``user@host``): its held session when live, else key-only ssh."""
    require(dest)
    return _held_runner(dest, timeout) if held(dest) else _ssh(dest, timeout)


def ordered_targets(grant: Grant, first: str = '') -> tuple[str, ...]:
    """*grant*'s ssh targets, the one *first* (``user@host``, host in full or by its first DNS label) names leading.

    Measured 2026-11-20: a credential for ``user@hpclogin02`` probed hpclogin01 first and waited out a 300 s
    timeout there before failing over; the host the caller named is the one it means.
    """
    host = first.partition('@')[2]
    named = [t for t in grant.targets if host and host in {t.partition('@')[2], t.partition('@')[2].split('.', 1)[0]}]
    return (*named, *(t for t in grant.targets if t not in named))


def _probed(dest: str, runner: Runner) -> Runner:
    """*runner*, used once *dest* answers ``true`` within :data:`PROBE_S`; a silent host is :class:`Unreachable`."""
    answered: list[bool] = []

    def run(command: str, stdin: str | None = None) -> str:
        if not answered:
            try:
                _ssh(dest, PROBE_S)('true', None)
            except subprocess.TimeoutExpired as silent:
                msg = f'{dest} did not answer a probe within {PROBE_S:.0f} s'
                raise Unreachable(msg) from silent
            answered.append(True)
        return runner(command, stdin)

    return run


def grant_runner(grant: Grant, timeout: float = _TIMEOUT, *, first: str = '') -> Runner:
    """The grant's login hosts, *first* leading: the first with a live held session, else key-only ssh in order.

    A host failed over TO is probed first with a short bound (:data:`PROBE_S`), so a silent one costs seconds,
    never the full *timeout*.
    """
    order = ordered_targets(grant, first)
    for dest in order:
        require(dest)
    for dest in order:
        if held(dest):
            return _held_runner(dest, timeout)
    lead, *rest = order
    return failover_runner([(lead, _ssh(lead, timeout)), *((d, _probed(d, _ssh(d, timeout))) for d in rest)])


def describe(dest: str, command: str) -> str:
    """How :func:`start` reaches *dest*, as one line a person can read."""
    session = sshholdstate.read_session(dest)
    if session is not None:
        return f'held session {dest}: {command}'
    argv = remote.ssh_argv(dest, command, batch=True)  # it ends in the command base64-encoded: show it read
    return f'{shlex.join(argv[: argv.index(dest) + 1])} <login shell runs> {shlex.quote(command)} (sent base64-encoded)'


class Started(Protocol):
    """A verb :func:`start` left running: ``poll()`` is its exit status once it ended, else ``None``."""

    def poll(self) -> int | None:
        """The exit status once ended, else ``None``."""
        ...


def start(dest: str, command: str, log: IO[Any]) -> int | Started:
    """Run *command* on *dest*, everything it prints into *log*; its exit status, or the process still running.

    A live held session runs it in the foreground through the holder (bounded by :data:`DEPLOY_S`), its output and
    status written to *log*; otherwise one detached key-only ssh (:func:`dev_lab.dev.remote.detached`), whose
    outcome :func:`outcomes` waits for.
    """
    require(dest)
    if held(dest):
        output, status = sshholdrun.run_command(dest, command, DEPLOY_S)
        log.write(f'{output}\n[held session {dest}] exit {status}\n')
        return status
    return remote.detached(remote.ssh_argv(dest, command, batch=True), log)


#: The lines of an account's log said with its outcome: the remote's last words, where a failure names itself.
TAIL: Final = 20


def outcomes(
    started: Sequence[tuple[str, Path, int | Started]],
    say: Callable[[str], None],
    *,
    kind: str,
    wait_s: float = DEPLOY_S,
    nap: Callable[[float], None] = time.sleep,
) -> int:
    """Say each account's outcome as it ends, with its log's last :data:`TAIL` lines; the count not exiting 0.

    ``<user>: exit N`` is said and appended to that account's log.

    Measured 2026-11-27: ``deploy-fleet`` exited 0 with every log holding only its "started" line, so a remote that
    crashed was never said (EVERY-WALL-TEACHES). No barrier: an account is reported when IT ends, never after the
    slowest. One still running after *wait_s* is reported unfinished and counts as not 0: its log keeps filling.
    """
    pending, failed, waited = list(started), 0, 0.0
    while pending:
        for item in list(pending):
            user, log, handle = item
            status = handle if isinstance(handle, int) else handle.poll()
            if status is not None:
                pending.remove(item)
                failed += status != 0
                _said(user, log, f'exit {status}', say, kind)
        if pending and waited >= wait_s:
            for user, log, _ in pending:
                _said(user, log, f'still running after {wait_s:.0f} s; its log keeps filling', say, kind)
            return failed + len(pending)
        if pending:
            nap(1.0)
            waited += 1.0
    return failed


def _said(user: str, log: Path, outcome: str, say: Callable[[str], None], kind: str) -> None:
    tail = log.read_text(encoding='utf-8', errors='replace').splitlines()[-TAIL:] if log.is_file() else []
    say(f'{user}: {outcome}')
    for line in tail:
        say(f'  {line}')
    with log.open('a', encoding='utf-8') as out:
        out.write(f'[{kind}] {user}: {outcome}\n')
