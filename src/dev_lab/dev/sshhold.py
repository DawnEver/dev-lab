"""SSHHOLD: authenticate to a key + TOTP host ONCE per work session; every later command rides that connection.

User ruling 2026-11-09. Windows OpenSSH has no ControlMaster (measured: "Failed to connect to new control
master") and WSL was ruled out, so the session is a DETACHED holder process (:mod:`dev_lab.dev._sshholder`)
owning ONE ``ssh -T <dest> bash --noprofile --norc -s``. It listens on 127.0.0.1 behind a random token; this
module is the client and the CLI::

    python -m dev_lab.dev.sshhold open <dest> --hours H [--code CODE]   # code on stdin when omitted
    python -m dev_lab.dev.sshhold open --hours H --plan <plan.json> --digest <D> [--steps S] [--code CODE]
    python -m dev_lab.dev.sshhold open <dest> --hours H --jump <bastion> [...]   # through a ProxyJump
    python -m dev_lab.dev.sshhold run <dest> -- <command...>            # exits with the remote status
    python -m dev_lab.dev.sshhold credential <dest> --url <https url> --login <login>   # token on stdin
    python -m dev_lab.dev.sshhold close <dest>
    python -m dev_lab.dev.sshhold status

* The keyboard-interactive answer is the user's single-use code from THIS conversation
  (CONSENT-CODE-FROM-THE-USER). It reaches the holder on a pipe and the ssh child through ``SSH_ASKPASS``;
  never argv, disk or a log. An empty code is allowed (a host's trusted window accepts an empty answer).
* ONE CODE, ONE PLAN (``--plan``): :mod:`dev_lab.dev.sshholdplan` -- the code buys the plan's credentials, then
  opens every plan host not already held. Before the code is read the door runs the plan's preflight ITSELF (the
  steps file its last green preflight recorded, or ``--steps``); not green now refuses ``no code used``.
* THE KEY IS ASKED FIRST, with no code (:mod:`dev_lab.dev.sshholdprobe`): a host that refuses this machine's public
  key refuses the open before the code is read, naming where the account's keys are managed.
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
import contextlib
import json
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Final

import lab_commons.launch as _door
from lab_commons.config import section
from lab_commons.log import emit

from dev_lab.dev import msyspath, remote, sshholdplan, sshholdprobe
from dev_lab.dev.sshholdrun import DEFAULT_TIMEOUT_S, run_command, store_credential
from dev_lab.dev.sshholdstate import audit, forget, read_session, state_dir, state_path
from dev_lab.dev.sshholdwire import HoldRefused, held, live, ping, request
from dev_lab.ops.consent.client import given_code
from dev_lab.ops.consent.credential import ConsentRefused

__all__ = [
    'DEFAULT_MAX_HOURS',
    'ceiling',
    'check_hours',
    'close_session',
    'idle_s',
    'main',
    'open_session',
    'route',
    'session_over',
    'status_lines',
]

#: The ceiling on ``--hours`` when the machine file names none (user ruling 2026-11-09: 4 h).
DEFAULT_MAX_HOURS: Final = 4.0
_OPEN_WAIT_S: Final = 120.0


def _table(table: dict[str, Any] | None) -> dict[str, Any]:
    if table is not None:
        return table
    hold = section('ssh').get('hold', {})
    return hold if isinstance(hold, dict) else {}


def route(dest: str, jump: str | None = None, table: dict[str, Any] | None = None) -> tuple[str, ...]:
    """The ssh words opening *dest*: through its declared bastion (``[ssh] jump``, *table* overrides), else *jump*.

    A *dest* whose host key is declared (``[ssh] host_keys``) is checked strictly against that key alone, through
    the one resolver (:func:`dev_lab.dev.remote.host_key_options`); a placeholder is refused BEFORE the code is read.
    """
    ssh = section('ssh') if table is None else table
    declared, keys = ssh.get('jump', {}), ssh.get('host_keys', {})
    bastion = (declared.get(dest) if isinstance(declared, dict) else None) or jump
    try:
        checked = remote.host_key_options(dest, keys if isinstance(keys, dict) else {})
    except remote.HostKeyUndeclared as undeclared:
        raise HoldRefused(str(undeclared)) from undeclared
    return ('ssh', *(('-J', bastion) if bastion else ()), *checked)


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


def open_session(dest: str, hours: float, code: str, *, ssh: tuple[str, ...] = ('ssh',)) -> str:
    """Start the holder for *dest*, answer the prompt with *code*, and return once it authenticated."""
    check_hours(hours, ceiling())
    if held(dest):  # a dead hold's record is removed here, so the open below is clean
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
        msg = remote.named(dest, f'{dest} did not authenticate: {word["error"]}')
        raise HoldRefused(msg)
    audit('open', dest, command=f'--hours {hours:g}', status=0, duration_s=time.monotonic() - started)
    return f'{dest}: session open for {hours:g} h (holder pid {word["pid"]})'


def close_session(dest: str) -> str:
    """End *dest*'s session; its state file goes either way."""
    session = live(dest)
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


def status_lines() -> list[str]:
    """One line per recorded session: its time left, or ``dead`` (and its state file removed)."""
    lines = []
    for path in sorted(state_dir().glob('*.json')) if state_dir().is_dir() else ():
        dest = json.loads(path.read_text(encoding='utf-8')).get('dest', path.stem)
        session = read_session(dest)
        if session is None or not ping(session):
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
        '--steps', type=Path, help="the plan's steps file, preflighted here before the code is used (default: the "
        'one its last green preflight recorded)'
    )  # fmt: skip
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


def _unopenable(dest: str | None, plan: Path | None) -> str:
    """Why ``open`` is refused before any code is read; ``''`` when it may ask for one.

    It names neither or both of a dest and a plan, or a dest naming no account (ssh would log in as THIS machine's
    user: measured 2026-11-20, a TOTP code spent on a refused key).
    """
    if (plan is None) == (dest is None):
        return 'sshhold: open names <dest> or --plan (which opens every host it names), exactly one'
    if dest is None or '@' in dest:
        return ''
    return (
        f"sshhold: refused -- {dest} names no account, so ssh would log in as THIS machine's user and spend the code "
        f'on a refused key: open <user>@{dest} (the account its [[hpc.grant]] or host file declares)'
    )


def _open(args: argparse.Namespace) -> int:
    """``open``: everything that can refuse does so BEFORE the code is read; then one host, or a plan's hosts."""
    jump, started = args.jump, time.monotonic()  # a code given in advance is already counting down
    if args.plan is not None:  # the preflight (it probes the plan's hosts); a fresh recorded green stands in for it
        emit(sshholdplan.offered(args.plan, args.steps, code_given=args.code is not None))
    check_hours(args.hours, ceiling())
    if args.plan is None:
        sshholdprobe.probe(args.dest, route(args.dest, jump))  # the key, asked with no code
        emit(open_session(args.dest, args.hours, given_code(args.code), ssh=route(args.dest, jump)))
        return 0
    code = given_code(args.code)
    opened, lines = sshholdplan.open_planned(
        args.hours, code, args.plan, args.digest, routes=lambda dest: route(dest, jump), opener=open_session,
        received=started if args.code is not None else time.monotonic(),
    )  # fmt: skip
    emit('\n'.join(lines))
    return 0 if opened else 2


def main(argv: list[str] | None = None) -> int:
    """The CLI; ``run`` exits with the remote status, a refusal with 2, a lost session with 255."""
    args = _parser().parse_args(argv)
    if args.verb == 'open' and (why := _unopenable(args.dest, args.plan)):
        emit(why, err=True)
        return 2
    try:
        if args.verb == 'open':
            return _open(args)
        if args.verb == 'run':
            words = args.command[1:] if args.command[:1] == ['--'] else args.command
            if why := msyspath.refusal(words):
                emit(f'sshhold: {why}', err=True)
                return 2
            output, status = run_command(args.dest, ' '.join(words), args.timeout)
            if output:
                emit(output.removesuffix('\n'))  # emit ends the line itself
            return status
        if args.verb == 'credential':
            emit(store_credential(args.dest, args.url, args.login, sys.stdin.readline().strip()))
        elif args.verb == 'close':
            emit(close_session(args.dest))
        else:
            emit('\n'.join(status_lines()))
    except (HoldRefused, ConsentRefused) as exc:  # a refused or unreadable code is named, never a traceback
        emit(f'sshhold: {exc}', err=True)
        return 255 if args.verb == 'run' and 'ssh connection ended' in str(exc) else 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
