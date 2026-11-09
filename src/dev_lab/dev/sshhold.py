"""SSHHOLD: authenticate to a key + TOTP host ONCE per work session; every later command rides that connection.

User ruling 2026-11-09. Windows OpenSSH has no ControlMaster (measured: "Failed to connect to new control
master") and WSL was ruled out, so the session is a DETACHED holder process (:mod:`dev_lab.dev._sshholder`)
owning ONE ``ssh -T <dest> bash --noprofile --norc -s``. It listens on 127.0.0.1 behind a random token; this
module is the client and the CLI::

    python -m dev_lab.dev.sshhold open <dest> --hours H [--code CODE]   # code on stdin when omitted
    python -m dev_lab.dev.sshhold run <dest> -- <command...>            # exits with the remote status
    python -m dev_lab.dev.sshhold close <dest>
    python -m dev_lab.dev.sshhold status

* The keyboard-interactive answer is the user's single-use code from THIS conversation
  (CONSENT-CODE-FROM-THE-USER). It reaches the holder on a pipe and the ssh child through ``SSH_ASKPASS``;
  never argv, disk or a log. An empty code is allowed (a host's trusted window accepts an empty answer).
* ``--hours`` above the ceiling (``[ssh.hold] max_hours`` in the machine file, default
  :data:`DEFAULT_MAX_HOURS`) is REFUSED, never clamped. The holder also ends after ``idle_minutes`` idle.
* A dropped connection is said by name and the user re-opens: never a silent re-authentication.
* Every open/run/close appends one JSONL line to :func:`audit_path` -- the command and its status, never the
  code or the token.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import re
import socket
import subprocess
import sys
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Final

import lab_commons.launch as _door
from lab_commons.config import section
from lab_commons.home import part
from lab_commons.log import emit

from dev_lab.ops.totp import write_private

__all__ = [
    'DEFAULT_IDLE_MINUTES',
    'DEFAULT_MAX_HOURS',
    'DEFAULT_TIMEOUT_S',
    'HoldRefused',
    'Session',
    'audit',
    'audit_path',
    'ceiling',
    'check_hours',
    'close_session',
    'frame',
    'idle_s',
    'main',
    'open_session',
    'read_session',
    'request',
    'run_command',
    'split_marker',
    'state_dir',
    'state_path',
    'status_lines',
    'write_session',
]

#: The ceiling on ``--hours`` when the machine file names none (user ruling 2026-11-09: 4 h).
DEFAULT_MAX_HOURS: Final = 4.0
#: A session with no command for this long ends itself.
DEFAULT_IDLE_MINUTES: Final = 30.0
#: One command's bound; past it the session closes, since a half-read stream cannot be trusted.
DEFAULT_TIMEOUT_S: Final = 600.0
_OPEN_WAIT_S: Final = 120.0
_CONNECT_S: Final = 5.0


class HoldRefused(RuntimeError):
    """A session verb that cannot proceed; the message says why and what to do."""


@dataclass(frozen=True)
class Session:
    """One live holder as its state file records it."""

    dest: str
    pid: int
    port: int
    token: str
    opened: float
    expires: float


def _table(table: dict[str, Any] | None) -> dict[str, Any]:
    if table is not None:
        return table
    hold = section('ssh').get('hold', {})
    return hold if isinstance(hold, dict) else {}


def ceiling(table: dict[str, Any] | None = None) -> float:
    """``[ssh.hold] max_hours`` from the machine file (*table* overrides it), else :data:`DEFAULT_MAX_HOURS`."""
    return float(_table(table).get('max_hours', DEFAULT_MAX_HOURS))


def idle_s(table: dict[str, Any] | None = None) -> float:
    """``[ssh.hold] idle_minutes`` in seconds, else :data:`DEFAULT_IDLE_MINUTES`."""
    return float(_table(table).get('idle_minutes', DEFAULT_IDLE_MINUTES)) * 60


def check_hours(hours: float, limit: float) -> None:
    """Refuse *hours* outside ``(0, limit]``; never clamp it."""
    if not 0 < hours <= limit:
        msg = (
            f'--hours {hours:g} is outside (0, {limit:g}]: the ceiling is [ssh.hold] max_hours in the machine '
            'file; ask for a shorter session, or the user raises the ceiling'
        )
        raise HoldRefused(msg)


def frame(command: str, nonce: str) -> str:
    """*command* as the holder writes it to the remote shell: merged streams, then the marker with ``$?``."""
    return f'{{ {command}\n}} 2>&1; printf \'\\n__SSHHOLD_{nonce}_%s\\n\' "$?"\n'


def split_marker(text: str, nonce: str) -> tuple[str, int] | None:
    """``(output, status)`` once *text* ends on *nonce*'s marker line; ``None`` while it has not."""
    found = re.search(rf'\n__SSHHOLD_{re.escape(nonce)}_(\d+)\r?\n\Z', text)
    return None if found is None else (text[: found.start()], int(found.group(1)))


def state_dir() -> Path:
    """``<machine home>/state/sshhold``: one state file per dest, and the audit."""
    return part('state') / 'sshhold'


def state_path(dest: str) -> Path:
    """The state file of *dest*, its name made filesystem-safe."""
    return state_dir() / f'{re.sub(r"[^A-Za-z0-9._-]", "_", dest)}.json'


def audit_path() -> Path:
    """The append-only JSONL audit of every open, run and close."""
    return state_dir() / 'audit.jsonl'


def write_session(session: Session) -> None:
    """Record *session* private (it carries the token)."""
    write_private(state_path(session.dest), json.dumps(asdict(session)))


def read_session(dest: str) -> Session | None:
    """The recorded session of *dest*, or ``None``."""
    path = state_path(dest)
    try:
        return Session(**json.loads(path.read_text(encoding='utf-8')))
    except (OSError, ValueError, TypeError):
        return None


def audit(verb: str, dest: str, *, command: str = '', status: int | None = None, duration_s: float = 0.0) -> None:
    """Append one audit line. Callers pass the command text and status; nothing else is ever written."""
    line = {'time': time.time(), 'dest': dest, 'verb': verb, 'command': command, 'status': status}
    line['duration_s'] = round(duration_s, 3)
    state_dir().mkdir(parents=True, exist_ok=True)
    with audit_path().open('a', encoding='utf-8') as out:
        out.write(json.dumps(line) + '\n')


def request(session: Session, payload: dict[str, Any], timeout_s: float) -> dict[str, Any]:
    """Send *payload* with the token and read the one JSON reply; :class:`OSError` when the holder is gone."""
    with socket.create_connection(('127.0.0.1', session.port), timeout=_CONNECT_S) as conn:
        conn.settimeout(timeout_s)
        conn.sendall(json.dumps({**payload, 'token': session.token}).encode('utf-8') + b'\n')
        with conn.makefile('rb') as reply:
            line = reply.readline()
    if not line:
        msg = 'the holder closed the connection without a reply'
        raise OSError(msg)
    return json.loads(line)


def _live(dest: str) -> Session:
    session = read_session(dest)
    if session is None:
        msg = f'no held session for {dest}: open one with the code the user gives'
        raise HoldRefused(msg)
    return session


def open_session(dest: str, hours: float, code: str, *, ssh: tuple[str, ...] = ('ssh',)) -> str:
    """Start the holder for *dest*, answer the prompt with *code*, and return once it authenticated."""
    check_hours(hours, ceiling())
    if (held := read_session(dest)) is not None and _ping(held):
        msg = f'{dest} already has a held session; close it first'
        raise HoldRefused(msg)
    argv = [sys.executable, '-m', 'dev_lab.dev._sshholder', dest, '--hours', str(hours), '--ssh', json.dumps(ssh)]
    pipes = {'stdin': subprocess.PIPE, 'stdout': subprocess.PIPE, 'stderr': subprocess.DEVNULL}
    if sys.platform != 'win32':
        child = _door.popen(argv, start_new_session=True, **pipes)
    else:
        child = _door.popen(argv, creationflags=0x08000000 | 0x00000200, **pipes)  # no window, own group
    started = time.monotonic()
    child.stdin.write(code.encode('utf-8') + b'\n')
    child.stdin.close()
    said: list[bytes] = []
    reader = threading.Thread(target=lambda: said.append(child.stdout.readline()), daemon=True)
    reader.start()
    reader.join(_OPEN_WAIT_S)
    word = json.loads(said[0]) if said and said[0] else {'error': 'the holder ended without a word'}
    if 'error' in word:
        if reader.is_alive():
            child.kill()
        msg = f'{dest} did not authenticate: {word["error"]}'
        raise HoldRefused(msg)
    audit('open', dest, command=f'--hours {hours:g}', status=0, duration_s=time.monotonic() - started)
    return f'{dest}: session open for {hours:g} h (holder pid {word["pid"]})'


def run_command(dest: str, command: str, timeout_s: float = DEFAULT_TIMEOUT_S) -> tuple[str, int]:
    """Run *command* on *dest*'s held connection: ``(merged output, remote status)``."""
    session = _live(dest)
    started = time.monotonic()
    try:
        reply = request(session, {'verb': 'run', 'command': command, 'timeout_s': timeout_s}, timeout_s + 30)
    except OSError as exc:
        state_path(dest).unlink(missing_ok=True)
        msg = f'the holder of {dest} is gone ({exc}); open a new session'
        raise HoldRefused(msg) from exc
    status = reply.get('status')
    audit('run', dest, command=command, status=status, duration_s=time.monotonic() - started)
    if reply.get('fatal'):
        state_path(dest).unlink(missing_ok=True)  # the holder is ending; its file goes now, not after its exit
    if 'error' in reply:
        msg = f'{dest}: {reply["error"]}'
        raise HoldRefused(msg)
    return reply['output'], int(status)


def close_session(dest: str) -> str:
    """End *dest*'s session; its state file goes either way."""
    session = _live(dest)
    started = time.monotonic()
    with contextlib.suppress(OSError):  # already dead: the file still goes
        request(session, {'verb': 'close'}, 60)
    for _ in range(50):  # the holder removes its own file on the way out
        if not state_path(dest).exists():
            break
        time.sleep(0.1)
    state_path(dest).unlink(missing_ok=True)
    audit('close', dest, status=0, duration_s=time.monotonic() - started)
    return f'{dest}: session closed'


def _ping(session: Session) -> bool:
    try:
        return request(session, {'verb': 'ping'}, _CONNECT_S).get('ok') is True
    except (OSError, ValueError):
        return False


def status_lines() -> list[str]:
    """One line per recorded session: its time left, or ``dead`` (and its state file removed)."""
    lines = []
    for path in sorted(state_dir().glob('*.json')) if state_dir().is_dir() else ():
        dest = json.loads(path.read_text(encoding='utf-8')).get('dest', path.stem)
        session = read_session(dest)
        if session is None or not _ping(session):
            path.unlink(missing_ok=True)
            lines.append(f'{dest}: dead (holder gone); state removed')
            continue
        left = max(0.0, session.expires - time.time()) / 60
        lines.append(f'{dest}: {left:.0f} min left (pid {session.pid})')
    return lines or ['no held sessions']


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog='python -m dev_lab.dev.sshhold', description=__doc__.split('\n')[0])
    verbs = parser.add_subparsers(dest='verb', required=True)
    opening = verbs.add_parser('open', help='authenticate once and hold the connection')
    opening.add_argument('dest')
    opening.add_argument('--hours', type=float, required=True)
    opening.add_argument('--code', help='the code the user gave; read from stdin when omitted')
    running = verbs.add_parser('run', help='run one command on the held connection')
    running.add_argument('dest')
    running.add_argument('--timeout', type=float, default=DEFAULT_TIMEOUT_S)
    running.add_argument('command', nargs=argparse.REMAINDER)
    verbs.add_parser('close', help='end a held session').add_argument('dest')
    verbs.add_parser('status', help='list held sessions and their time left')
    return parser


def main(argv: list[str] | None = None) -> int:
    """The CLI; ``run`` exits with the remote status, a refusal with 2, a lost session with 255."""
    args = _parser().parse_args(argv)
    try:
        if args.verb == 'open':
            code = args.code if args.code is not None else sys.stdin.readline().strip()
            emit(open_session(args.dest, args.hours, code))
        elif args.verb == 'run':
            words = args.command[1:] if args.command[:1] == ['--'] else args.command
            output, status = run_command(args.dest, ' '.join(words), args.timeout)
            if output:
                emit(output.removesuffix('\n'))  # emit ends the line itself
            return status
        elif args.verb == 'close':
            emit(close_session(args.dest))
        else:
            emit('\n'.join(status_lines()))
    except HoldRefused as exc:
        emit(f'sshhold: {exc}', err=True)
        return 255 if args.verb == 'run' and 'ssh connection ended' in str(exc) else 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
