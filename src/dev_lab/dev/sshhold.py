"""SSHHOLD: authenticate to a key + TOTP host ONCE per work session; every later command rides that connection.

User ruling 2026-11-09. Windows OpenSSH has no ControlMaster (measured: "Failed to connect to new control
master") and WSL was ruled out, so the session is a DETACHED holder process (:mod:`dev_lab.dev._sshholder`)
owning ONE ``ssh -T <dest> bash --noprofile --norc -s``. It listens on 127.0.0.1 behind a random token; this
module is the client and the CLI::

    python -m dev_lab.dev.sshhold open <dest> --hours H [--code CODE]   # code on stdin when omitted
    python -m dev_lab.dev.sshhold open --hours H --plan <plan.json> --digest <D> [--code CODE]   # every plan host
    python -m dev_lab.dev.sshhold open <dest> --hours H --jump <bastion> [...]   # through a ProxyJump
    python -m dev_lab.dev.sshhold run <dest> -- <command...>            # exits with the remote status
    python -m dev_lab.dev.sshhold credential <dest> --url <https url> --login <login>   # token on stdin
    python -m dev_lab.dev.sshhold close <dest>
    python -m dev_lab.dev.sshhold status

* The keyboard-interactive answer is the user's single-use code from THIS conversation
  (CONSENT-CODE-FROM-THE-USER). It reaches the holder on a pipe and the ssh child through ``SSH_ASKPASS``;
  never argv, disk or a log. An empty code is allowed (a host's trusted window accepts an empty answer).
* ONE CODE, ONE PLAN (user ruling 2026-11-10; topology.md 5.1): with ``--plan`` the same code first buys one
  single-use consent credential per grant of the plan the user was shown
  (:func:`dev_lab.ops.consent.client.grant_plan`; the digest is ``python -m dev_lab.ops.consent plan <plan.json>``'s),
  then opens EVERY host the plan names, concurrently, inside :data:`OPEN_WINDOW_S` of the code -- the cluster's one
  TOTP secret is verified by the issuer and each host's pam_oath, each once (:mod:`dev_lab.ops.consent.plan`). A host
  that fails or misses the window is REPORTED, never retried with the code: granting spends no credential, so no
  grant on any host is spent, and that host alone is re-opened with a new code (``open <dest> --hours H``).
* ``--jump <bastion>``: a host reachable only through a bastion. ssh asks each hop's keyboard-interactive
  prompt through the same ``SSH_ASKPASS``, so ONE code answers both -- valid only where the hops share one TOTP
  secret (each pam_oath records the step it accepted, so the code is spent once per host, never twice on one).
  A host's route is DECLARED in the machine file -- ``[ssh] jump = {"<dest>" = "<bastion>"}`` (:func:`route`) -- so a
  plan whose hosts route differently (one direct, one through a bastion) opens each on its own; ``--jump`` names the
  bastion of every host the table does not.
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
import base64
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
from pathlib import Path
from typing import Any, Final
from urllib.parse import urlsplit

import lab_commons.launch as _door
from lab_commons.config import section
from lab_commons.log import emit

from dev_lab.dev.sshholdstate import Session, audit, forget, read_session, state_dir, state_path
from dev_lab.ops.consent.client import given_code, grant_plan
from dev_lab.ops.consent.credential import ConsentRefused
from dev_lab.ops.consent.plan import STALE_CLIENT, parsed, stale_client
from dev_lab.ops.totp import STEP

__all__ = [
    'DEFAULT_MAX_HOURS',
    'DEFAULT_TIMEOUT_S',
    'OPEN_WINDOW_S',
    'HoldRefused',
    'ceiling',
    'check_hours',
    'close_session',
    'credential_script',
    'frame',
    'idle_s',
    'main',
    'open_planned',
    'open_session',
    'request',
    'route',
    'run_command',
    'session_over',
    'split_marker',
    'status_lines',
    'store_credential',
]

#: The ceiling on ``--hours`` when the machine file names none (user ruling 2026-11-09: 4 h).
DEFAULT_MAX_HOURS: Final = 4.0
#: One command's bound; past it the session closes, since a half-read stream cannot be trusted.
DEFAULT_TIMEOUT_S: Final = 600.0
_OPEN_WAIT_S: Final = 120.0
#: How long after the code a plan's host session may still be STARTED: one TOTP step. A host not started inside it
#: is reported, never sent the code (topology.md 5.1).
OPEN_WINDOW_S: Final = float(STEP)
_CONNECT_S: Final = 5.0
#: The remote status of a credential refused for want of a git credential helper.
_NO_HELPER: Final = 3


class HoldRefused(RuntimeError):
    """A session verb that cannot proceed; the message says why and what to do."""


def _table(table: dict[str, Any] | None) -> dict[str, Any]:
    if table is not None:
        return table
    hold = section('ssh').get('hold', {})
    return hold if isinstance(hold, dict) else {}


def route(dest: str, jump: str | None = None, table: dict[str, Any] | None = None) -> tuple[str, ...]:
    """The ssh words opening *dest*: through its declared bastion (``[ssh] jump``, *table* overrides), else *jump*."""
    declared = (section('ssh') if table is None else table).get('jump', {})
    bastion = (declared.get(dest) if isinstance(declared, dict) else None) or jump
    return ('ssh', '-J', bastion) if bastion else ('ssh',)


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
        msg = (
            f'no held session for {dest}. A key-only host (Ada) needs no code and no session: use the '
            '`python -m lab_commons.hpc` doors (plan|submit|status|gather|retry|run, and '
            '`clean --root <abs> [--dry-run] --at <user@host> <name>...`). A key+TOTP host: '
            f'`python -m dev_lab.dev.sshhold open {dest} --hours N --code <code>`, the code the user gave.'
        )
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
    hours: float, code: str, plan: Path, shown: str, *, routes: Callable[[str], tuple[str, ...]] = route,
    grant: Callable[[Path, str, str, str], list[Path]] = grant_plan,
    opener: Callable[..., str] = open_session,
    clock: Callable[[], float] = time.monotonic,
) -> tuple[bool, list[str]]:  # fmt: skip
    """Spend ONE *code* on *plan* (the one *shown*), then on every plan host's session: ``(all open, lines)``.

    The issuer grant comes first; then each host opens concurrently, started only inside :data:`OPEN_WINDOW_S` of
    the code, each on its own *routes* (:func:`route`). A host that fails is a line naming it and how to re-open it --
    the code is never sent twice.
    """
    check_hours(hours, ceiling())  # before the code is spent on the grants
    found = parsed(json.loads(plan.read_text(encoding='utf-8')))
    if stale := stale_client(found):
        msg = f'the plan was not granted, no code sent: {stale} unknown to this client: {STALE_CLIENT}'
        raise HoldRefused(msg)
    given = clock()
    try:
        written = grant(plan, shown, code, found.hosts[0])
    except ConsentRefused as refused:
        msg = f'the plan was not granted: {refused}'
        raise HoldRefused(msg) from refused
    audit('plan', ','.join(found.hosts), command=shown, status=0, grants=len(written))
    lines = [f'consent granted: {path}' for path in written]
    said: dict[str, str] = {}

    def one(dest: str) -> None:
        try:
            said[dest] = opener(dest, hours, code, ssh=routes(dest))
        except (HoldRefused, OSError) as refused:
            said[dest] = f'{dest}: NOT opened ({refused})'

    late = clock() - given > OPEN_WINDOW_S
    threads = [threading.Thread(target=one, args=(dest,), daemon=True) for dest in found.hosts if not late]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    for dest in found.hosts:
        if late:
            said[dest] = f'{dest}: NOT opened (the grant took past the {OPEN_WINDOW_S:g} s window; code not sent)'
        if 'NOT opened' in said[dest]:
            said[dest] += (f'; no credential is spent -- re-open it alone with a new code: '
                           f'python -m dev_lab.dev.sshhold open {dest} --hours {hours:g}')  # fmt: skip
        lines.append(said[dest])
    return all('NOT opened' not in said[dest] for dest in found.hosts), lines


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


def stdin_script(command: str, stdin: bytes, end: str) -> str:
    """*command* reading *stdin* exactly: base64 heredoc DATA in the held shell's stream, never a file or an argv."""
    data = base64.encodebytes(stdin).decode('ascii').rstrip('\n')
    return f"base64 -d <<'{end}' | {command}\n{data}\n{end}"


def run_command(
    dest: str, command: str, timeout_s: float = DEFAULT_TIMEOUT_S, *, stdin: bytes | None = None
) -> tuple[str, int]:
    """Run *command* on *dest*'s held connection: ``(merged output, remote status)``.

    The audit records *command* VERBATIM, so a secret never rides *command*: it is *stdin*, sent by
    :func:`stdin_script` and audited as a sha256 prefix only (a forge token goes through :func:`store_credential`).
    """
    started = time.monotonic()
    sent = command if stdin is None else stdin_script(command, stdin, f'__SSHHOLD_IN_{secrets.token_hex(8)}')
    reply = _exchange(dest, sent, timeout_s)
    fields = {} if stdin is None else {'stdin_sha256': hashlib.sha256(stdin).hexdigest()[:12]}
    audit('run', dest, command=command, status=reply.get('status'), duration_s=time.monotonic() - started, **fields)
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
    opening.add_argument('dest', nargs='?', help='the host to open; omitted with --plan, which names its hosts')
    opening.add_argument('--hours', type=float, required=True)
    opening.add_argument('--code', help='the code the user gave; read from stdin when omitted')
    opening.add_argument(
        '--plan', type=Path, help='a plan the same code consents to (python -m dev_lab.ops.consent plan)'
    )
    opening.add_argument('--digest', default='', help="the plan's digest, as shown to the user")
    opening.add_argument(
        '--jump', help='a bastion (ssh -J) for every host [ssh] jump does not route; the one code answers both'
    )
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
    if args.verb == 'open' and (args.plan is None) == (args.dest is None):
        emit('sshhold: open names <dest> or --plan (which opens every host it names), exactly one', err=True)
        return 2
    try:
        if args.verb == 'open':
            code, jump = given_code(args.code), args.jump
            if args.plan is not None:
                opened, lines = open_planned(
                    args.hours, code, args.plan, args.digest, routes=lambda dest: route(dest, jump)
                )
                emit('\n'.join(lines))
                return 0 if opened else 2
            emit(open_session(args.dest, args.hours, code, ssh=route(args.dest, jump)))
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
