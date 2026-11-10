"""SSHHOLD: authenticate to a key + TOTP host ONCE per work session; every later command rides that connection.

User ruling 2026-11-09. Windows OpenSSH has no ControlMaster (measured: "Failed to connect to new control
master") and WSL was ruled out, so the session is a DETACHED holder process (:mod:`dev_lab.dev._sshholder`)
owning ONE ``ssh -T <dest> bash --noprofile --norc -s``. It listens on 127.0.0.1 behind a random token; this
module is the client and the CLI::

    python -m dev_lab.dev.sshhold open <dest> --hours H [--code CODE]   # code on stdin when omitted
    python -m dev_lab.dev.sshhold open <dest> --hours H --plan <plan.json> --digest <D> [--code CODE]
    python -m dev_lab.dev.sshhold run <dest> -- <command...>            # exits with the remote status
    python -m dev_lab.dev.sshhold credential <dest> --url <https url> --login <login>   # token on stdin
    python -m dev_lab.dev.sshhold close <dest>
    python -m dev_lab.dev.sshhold status

* The keyboard-interactive answer is the user's single-use code from THIS conversation
  (CONSENT-CODE-FROM-THE-USER). It reaches the holder on a pipe and the ssh child through ``SSH_ASKPASS``;
  never argv, disk or a log. An empty code is allowed (a host's trusted window accepts an empty answer).
* ONE CODE, ONE PLAN (user ruling 2026-11-10): with ``--plan`` the same code first buys one single-use consent
  credential per grant of the plan the user was shown (:func:`dev_lab.ops.consent.client.grant_plan`; the digest
  is ``python -m dev_lab.ops.consent plan <plan.json>``'s), then opens the session. The host's one TOTP secret is
  verified by its issuer and its pam_oath, each once (:mod:`dev_lab.ops.consent.plan`).
* ``--hours`` above the ceiling (``[ssh.hold] max_hours`` in the machine file, default
  :data:`DEFAULT_MAX_HOURS`) is REFUSED, never clamped. A quiet session lives to that ceiling (keepalives hold the
  connection, :func:`dev_lab.dev._sshholder.ssh_argv`); it ends early on idle only when the machine file names
  ``[ssh.hold] idle_minutes`` -- a 30 min default ended a 4 h session, measured 2026-11-10.
* A dropped connection is said by name and the user re-opens: never a silent re-authentication.
* Every open/run/credential/close appends one JSONL line to :func:`audit_path` -- a ``run`` records its command
  VERBATIM, so A SECRET NEVER GOES THROUGH ``run``. A forge token goes through ``credential`` alone: read from
  stdin, sent as heredoc data to the remote ``git credential approve``, audited as host, login and a sha256
  prefix -- never in an argv, the audit or the state file.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import re
import secrets
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Final
from urllib.parse import urlsplit

import lab_commons.launch as _door
from lab_commons.config import section
from lab_commons.home import part
from lab_commons.log import emit

from dev_lab.ops.consent.client import given_code, grant_plan
from dev_lab.ops.consent.credential import ConsentRefused
from dev_lab.ops.totp import write_private

__all__ = [
    'DEFAULT_MAX_HOURS',
    'DEFAULT_TIMEOUT_S',
    'HoldRefused',
    'Session',
    'audit',
    'audit_path',
    'ceiling',
    'check_hours',
    'close_session',
    'credential_script',
    'forget',
    'frame',
    'idle_s',
    'main',
    'open_planned',
    'open_session',
    'read_session',
    'request',
    'run_command',
    'session_over',
    'split_marker',
    'state_dir',
    'state_path',
    'status_lines',
    'store_credential',
    'write_session',
]

#: The ceiling on ``--hours`` when the machine file names none (user ruling 2026-11-09: 4 h).
DEFAULT_MAX_HOURS: Final = 4.0
#: One command's bound; past it the session closes, since a half-read stream cannot be trusted.
DEFAULT_TIMEOUT_S: Final = 600.0
_OPEN_WAIT_S: Final = 120.0
_CONNECT_S: Final = 5.0
#: The remote status of a credential refused for want of a git credential helper.
_NO_HELPER: Final = 3


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


def idle_s(table: dict[str, Any] | None = None) -> float | None:
    """``[ssh.hold] idle_minutes`` in seconds, else ``None``: no idle limit, the session lives to its ceiling."""
    minutes = _table(table).get('idle_minutes')
    return None if minutes is None else float(minutes) * 60


def session_over(*, now: float, expires: float, quiet_s: float, idle: float | None) -> bool:
    """Whether a session ends: its ceiling *expires* reached, or *quiet_s* past a configured *idle* limit."""
    return now >= expires or (idle is not None and quiet_s >= idle)


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


def forget(dest: str) -> None:
    """Remove *dest*'s state file; already gone, or being removed by the other side (Windows: delete pending), is fine.

    The client and the ending holder both remove it, so one of them loses that race with PermissionError.
    """
    with contextlib.suppress(FileNotFoundError, PermissionError):
        state_path(dest).unlink()


def read_session(dest: str) -> Session | None:
    """The recorded session of *dest*, or ``None``."""
    path = state_path(dest)
    try:
        return Session(**json.loads(path.read_text(encoding='utf-8')))
    except (OSError, ValueError, TypeError):
        return None


def audit(
    verb: str, dest: str, *, command: str = '', status: int | None = None, duration_s: float = 0.0, **fields: object
) -> None:
    """Append one audit line: what the caller passes, never more. A secret is never a field (a digest may be)."""
    line = {'time': time.time(), 'dest': dest, 'verb': verb, 'command': command, 'status': status, **fields}
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


def open_planned(
    dest: str, hours: float, code: str, plan: Path, shown: str, *, ssh: tuple[str, ...] = ('ssh',),
    grant: Callable[[Path, str, str, str], list[Path]] = grant_plan,
) -> list[str]:  # fmt: skip
    """Spend ONE *code* on *plan* (the one *shown*) and then on *dest*'s session; what it granted, then the session.

    The plan's host must be *dest*: a code the user gave for one host's plan never opens another.
    """
    check_hours(hours, ceiling())  # before the code is spent on the grants
    try:
        written = grant(plan, shown, code, dest)
    except ConsentRefused as refused:
        msg = f'the plan was not granted: {refused}'
        raise HoldRefused(msg) from refused
    audit('plan', dest, command=shown, status=0, grants=len(written))
    return [*(f'{dest}: consent granted: {path}' for path in written), open_session(dest, hours, code, ssh=ssh)]


def _exchange(dest: str, command: str, timeout_s: float) -> dict[str, Any]:
    """Send *command* through *dest*'s holder; the reply, or :class:`HoldRefused` when the holder is gone."""
    session = _live(dest)
    try:
        reply = request(session, {'verb': 'run', 'command': command, 'timeout_s': timeout_s}, timeout_s + 30)
    except OSError as exc:
        forget(dest)
        msg = f'the holder of {dest} is gone ({exc}); open a new session'
        raise HoldRefused(msg) from exc
    if reply.get('fatal'):
        forget(dest)  # the holder is ending; its file goes now, not after its exit
    return reply


def run_command(dest: str, command: str, timeout_s: float = DEFAULT_TIMEOUT_S) -> tuple[str, int]:
    """Run *command* on *dest*'s held connection: ``(merged output, remote status)``.

    The audit records *command* VERBATIM, so a secret never travels here: it goes through :func:`store_credential`.
    """
    started = time.monotonic()
    reply = _exchange(dest, command, timeout_s)
    audit('run', dest, command=command, status=reply.get('status'), duration_s=time.monotonic() - started)
    if 'error' in reply:
        msg = f'{dest}: {reply["error"]}'
        raise HoldRefused(msg)
    return reply['output'], int(reply['status'])


def credential_script(url: str, login: str, token: str, nonce: str) -> str:
    """The remote script storing *login*/*token* for *url*'s host with ``git credential approve``.

    The token is heredoc DATA, never a command word; a value that could start a new line is refused, and so is
    an account with no git credential helper (status :data:`_NO_HELPER`), by name.
    """
    host = urlsplit(url).hostname or ''
    if urlsplit(url).scheme != 'https' or not host:
        msg = f'{url!r} is not an https url with a host'
        raise HoldRefused(msg)
    if not token or any(not value or re.search(r'\s', value) for value in (login, token)):
        msg = 'the login and the token are one non-empty word each (no whitespace, no newline)'
        raise HoldRefused(msg)
    end = f'__SSHHOLD_CRED_{nonce}'
    lines = f'protocol=https\nhost={host}\nusername={login}\npassword={token}\n'
    return (
        'if [ -z "$(git config --global --get credential.helper)" ]; then\n'
        "  echo 'sshhold: no git credential helper is configured on this account'; ( exit 3 )\n"
        f"else git credential approve <<'{end}'\n{lines}\n{end}\nfi"
    )


def store_credential(dest: str, url: str, login: str, token: str, timeout_s: float = 60) -> str:
    """Store *token* on *dest* for *url* through the held channel; audited as host, login and a sha256 prefix."""
    started = time.monotonic()
    script = credential_script(url, login, token, secrets.token_hex(8))
    reply = _exchange(dest, script, timeout_s)
    host, digest = urlsplit(url).hostname, hashlib.sha256(token.encode()).hexdigest()[:12]
    status = reply.get('status')
    audit('credential', dest, status=status, duration_s=time.monotonic() - started, host=host, login=login,
          sha256=digest)  # fmt: skip
    if 'error' in reply:
        msg = f'{dest}: {reply["error"]}'
        raise HoldRefused(msg)
    if status == _NO_HELPER:
        msg = f'{dest} has no git credential helper: run `git config --global credential.helper store` there first'
        raise HoldRefused(msg)
    if status:
        msg = f'{dest}: git credential approve exited {status}'
        raise HoldRefused(msg)
    return f'{dest}: credential stored for {login}@{host} (sha256 {digest})'


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
    forget(dest)
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
            forget(dest)
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
    opening.add_argument(
        '--plan', type=Path, help='a plan the same code consents to (python -m dev_lab.ops.consent plan)'
    )
    opening.add_argument('--digest', default='', help="the plan's digest, as shown to the user")
    running = verbs.add_parser('run', help='run one command on the held connection')
    running.add_argument('dest')
    running.add_argument('--timeout', type=float, default=DEFAULT_TIMEOUT_S)
    running.add_argument('command', nargs=argparse.REMAINDER)
    storing = verbs.add_parser('credential', help='store a forge token on the held account (token on stdin)')
    storing.add_argument('dest')
    storing.add_argument('--url', required=True, help='an https url on the forge host')
    storing.add_argument('--login', required=True, help="the token's forge login")
    verbs.add_parser('close', help='end a held session').add_argument('dest')
    verbs.add_parser('status', help='list held sessions and their time left')
    return parser


def main(argv: list[str] | None = None) -> int:
    """The CLI; ``run`` exits with the remote status, a refusal with 2, a lost session with 255."""
    args = _parser().parse_args(argv)
    try:
        if args.verb == 'open':
            code = given_code(args.code)
            planned = args.plan is not None
            opened = open_planned(args.dest, args.hours, code, args.plan, args.digest) if planned else None
            emit('\n'.join(opened) if opened else open_session(args.dest, args.hours, code))
        elif args.verb == 'run':
            words = args.command[1:] if args.command[:1] == ['--'] else args.command
            output, status = run_command(args.dest, ' '.join(words), args.timeout)
            if output:
                emit(output.removesuffix('\n'))  # emit ends the line itself
            return status
        elif args.verb == 'credential':
            emit(store_credential(args.dest, args.url, args.login, sys.stdin.readline().strip()))
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
