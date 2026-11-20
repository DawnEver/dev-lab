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

:func:`grant_runner` / :func:`host_runner` are the reads (a :data:`Runner`), :func:`start` is the deploy-fleet launch.
"""

from __future__ import annotations

import shlex
from typing import IO, Any, Final

from lab_commons.hpc.cluster import Runner, failover_runner, ssh_runner
from lab_commons.hpc.grants import Grant

from dev_lab.dev import remote, sshholdrun, sshholdstate, sshholdwire
from dev_lab.dev.sshholdwire import HoldRefused

__all__ = ['DEPLOY_S', 'HoldRefused', 'describe', 'door', 'grant_runner', 'held', 'host_runner', 'start']

#: How long one deploy may take on a held session (it runs in the foreground there: the holder owns the stream).
DEPLOY_S: Final = 3600.0
#: What ssh says when a host wanted a second factor that BatchMode cannot type.
_SECOND_FACTOR: Final = 'keyboard-interactive'
_TIMEOUT: Final = 300.0


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
    return _held_runner(dest, timeout) if held(dest) else _ssh(dest, timeout)


def grant_runner(grant: Grant, timeout: float = _TIMEOUT) -> Runner:
    """The grant's login hosts: the first with a live held session, else key-only ssh over them in order."""
    for dest in grant.targets:
        if held(dest):
            return _held_runner(dest, timeout)
    return failover_runner([(dest, _ssh(dest, timeout)) for dest in grant.targets])


def describe(dest: str, command: str) -> str:
    """How :func:`start` reaches *dest*, as one line a person can read."""
    session = sshholdstate.read_session(dest)
    if session is not None:
        return f'held session {dest}: {command}'
    return shlex.join(remote.ssh_argv(dest, command, batch=True))


def start(dest: str, command: str, log: IO[Any]) -> object:
    """Run *command* on *dest*, everything it prints into *log*.

    A live held session runs it in the foreground through the holder (bounded by :data:`DEPLOY_S`), its output and
    status written to *log*; otherwise one detached key-only ssh (:func:`dev_lab.dev.remote.detached`).
    """
    if held(dest):
        output, status = sshholdrun.run_command(dest, command, DEPLOY_S)
        log.write(f'{output}\n[held session {dest}] exit {status}\n')
        return status
    return remote.detached(remote.ssh_argv(dest, command, batch=True), log)
