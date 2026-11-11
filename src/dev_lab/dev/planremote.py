"""The hosts a consent plan runs on (:mod:`.planrun`): one shell command at a time, and one private file put.

:func:`remote_for` is a host's held session (:mod:`.sshhold`) when one is open -- no new authentication, no code --
else plain key-only ssh that never prompts. A put's content and a run's stdin ride heredoc DATA or ssh's stdin --
never the host's disk (a run's stdin), an argv or an audit (the audit names the command or path and a sha256
prefix only).
"""

from __future__ import annotations

import hashlib
import secrets
import shlex
from dataclasses import dataclass
from typing import Final, Protocol

import lab_commons.launch as _door

from dev_lab.dev import remote as ssh_remote
from dev_lab.dev import sshhold

__all__ = ['HeldRemote', 'Remote', 'SshRemote', 'remote_for']

_TIMEOUT_S: Final = 600.0
_PUT_S: Final = 60.0


class Remote(Protocol):
    """A host a plan runs on: one shell command at a time, and one private file put."""

    def run(self, command: str, stdin: bytes | None = None) -> tuple[str, int]:
        """``(merged output, exit status)`` of *command* (a POSIX shell line); *stdin* never on disk, argv or audit."""
        ...

    def put(self, path: str, text: str) -> None:
        """Write *text* at *path* under umask 077; its content never reaches an argv or an audit."""
        ...


@dataclass(frozen=True)
class HeldRemote:
    """The held session of *dest* (:mod:`.sshhold`): no new authentication, no code."""

    dest: str

    def run(self, command: str, stdin: bytes | None = None) -> tuple[str, int]:
        """Run *command* on the held connection; *stdin* rides it as heredoc DATA (:func:`.sshhold.stdin_script`)."""
        return sshhold.run_command(self.dest, command, stdin=stdin)

    def put(self, path: str, text: str) -> None:
        """Write *text* through the held channel as heredoc DATA; audited as the path and a sha256 prefix only."""
        session = sshhold.read_session(self.dest)
        if session is None:
            msg = f'no held session for {self.dest}'
            raise sshhold.HoldRefused(msg)
        end = f'__PLANRUN_PUT_{secrets.token_hex(8)}'
        script = f"{_put_command(path)} <<'{end}'\n{text.rstrip()}\n{end}"
        try:
            reply = sshhold.request(session, {'verb': 'run', 'command': script, 'timeout_s': _PUT_S}, _PUT_S + 30)
        except OSError as gone:
            msg = f'the holder of {self.dest} is gone ({gone}); open a new session'
            raise sshhold.HoldRefused(msg) from gone
        digest = hashlib.sha256(text.encode()).hexdigest()[:12]
        sshhold.audit('put', self.dest, command=path, status=reply.get('status'), sha256=digest)
        if 'error' in reply or reply.get('status'):
            msg = f'{self.dest}: could not write {path}: {reply.get("error") or reply.get("output", "").strip()}'
            raise sshhold.HoldRefused(msg)


@dataclass(frozen=True)
class SshRemote:
    """Plain key-only ssh to *dest* (never prompts): for a host whose account needs no second factor."""

    dest: str

    def _ssh(self, command: str, data: bytes | None) -> tuple[str, int]:
        argv = ssh_remote.ssh_argv(self.dest, command, batch=True)
        done = _door.run(argv, input=data, capture_output=True, check=False, timeout=_TIMEOUT_S)
        return (done.stdout + done.stderr).decode('utf-8', 'replace'), done.returncode

    def run(self, command: str, stdin: bytes | None = None) -> tuple[str, int]:
        """Run *command* over a fresh key-only connection, *stdin* on ssh's stdin."""
        return self._ssh(command, stdin)

    def put(self, path: str, text: str) -> None:
        """Write *text* at *path*: the content on ssh's stdin, never its argv."""
        output, status = self._ssh(_put_command(path), text.encode('utf-8'))
        if status:
            msg = f'{self.dest}: could not write {path} ({status}): {output.strip()}'
            raise sshhold.HoldRefused(msg)


def _put_command(path: str) -> str:
    quoted = shlex.quote(path)
    return f'umask 077 && mkdir -p "$(dirname {quoted})" && cat > {quoted}'


def remote_for(dest: str) -> Remote:
    """*dest*'s held session when one is recorded, else plain key-only ssh."""
    return HeldRemote(dest) if sshhold.read_session(dest) is not None else SshRemote(dest)
