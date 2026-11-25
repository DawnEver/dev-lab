"""The detached holder behind :mod:`dev_lab.dev.sshhold`: one ssh connection, served on 127.0.0.1 by token.

Started by ``sshhold open`` with the code on its stdin. It hands the code to the ssh child ALONE, through
``SSH_ASKPASS`` (a helper that prints an environment variable -- the helper file carries no secret), proves the
login with one framed probe, then says one JSON word on stdout (``{"ok": true}`` or ``{"error": ...}``) and
serves until ``close``, its ceiling, a configured idle limit, a command timeout, or the ssh child's end.
"""

from __future__ import annotations

import argparse
import contextlib
import hmac
import json
import os
import queue
import secrets
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Final

import lab_commons.launch as _door

from dev_lab.dev import sshhold, sshholdrun, sshholdstate, sshholdwire
from dev_lab.dev.harness import child_env

_ANSWER_ENV: Final = 'SSHHOLD_ANSWER'
_PROBE_S: Final = 120.0
_TICK_S: Final = 1.0


def askpass_helper() -> Path:
    """The ``SSH_ASKPASS`` program: prints ``$SSHHOLD_ANSWER``. It holds no secret, so it may sit on disk."""
    folder = sshholdstate.state_dir()
    folder.mkdir(parents=True, exist_ok=True)
    if sys.platform == 'win32':
        helper = folder / 'askpass.cmd'
        code = f"import os;print(os.environ.get('{_ANSWER_ENV}',''))"
        helper.write_text(f'@echo off\r\n"{sys.executable}" -I -c "{code}"\r\n', encoding='utf-8')
    else:
        helper = folder / 'askpass.sh'
        helper.write_text(f'#!/bin/sh\nprintf \'%s\\n\' "${_ANSWER_ENV}"\n', encoding='utf-8')
        helper.chmod(0o700)
    return helper


def ssh_argv(ssh: list[str], dest: str) -> list[str]:
    """The one held connection: no tty, keepalives, ONE answer tried, a bare bash, on PATH's ssh.

    The ssh word is resolved by :func:`.sshholdwire.resolved`.
    """
    keep = ['-o', 'ServerAliveInterval=30', '-o', 'ServerAliveCountMax=4', '-o', 'NumberOfPasswordPrompts=1']
    return sshholdwire.resolved([*ssh, '-T', *keep, dest, 'bash', '--noprofile', '--norc', '-s'])


class Holder:
    """The ssh child, its output queue, and the framed exchange over it."""

    def __init__(self, argv: list[str], code: str) -> None:
        env = child_env({'SSH_ASKPASS': str(askpass_helper()), 'SSH_ASKPASS_REQUIRE': 'force'})
        env.setdefault('DISPLAY', ':0')  # an ssh before 8.4 consults askpass only with a DISPLAY
        env[_ANSWER_ENV] = code
        pipe = subprocess.PIPE
        self.child = _door.popen(argv, stdin=pipe, stdout=pipe, stderr=pipe, env=env)
        self.chunks: queue.Queue[bytes | None] = queue.Queue()
        self.errors: list[bytes] = []
        threading.Thread(target=self._pump, daemon=True).start()
        threading.Thread(target=lambda: self.errors.extend(self.child.stderr), daemon=True).start()

    def _pump(self) -> None:
        while chunk := self.child.stdout.read1(65536):
            self.chunks.put(chunk)
        self.chunks.put(None)

    def exchange(self, command: str, timeout_s: float) -> dict[str, Any]:
        """Run *command*: ``{'output', 'status'}``, or ``{'error', 'fatal': True}`` once the stream is lost."""
        nonce = secrets.token_hex(8)
        try:
            self.child.stdin.write(sshholdwire.frame(command, nonce).encode('utf-8'))
            self.child.stdin.flush()
        except OSError:
            return self._ended()
        deadline, got = time.monotonic() + timeout_s, b''
        while (left := deadline - time.monotonic()) > 0:
            try:
                chunk = self.chunks.get(timeout=left)
            except queue.Empty:
                break
            if chunk is None:
                return self._ended()
            got += chunk
            if (done := sshholdwire.split_marker(got.decode('utf-8', 'replace'), nonce)) is not None:
                return {'output': done[0], 'status': done[1]}
        why = f'no reply within {timeout_s:g} s; the session is closed (a half-read stream cannot be trusted)'
        return {'error': why, 'fatal': True}

    def _ended(self) -> dict[str, Any]:
        with contextlib.suppress(subprocess.TimeoutExpired):
            self.child.wait(timeout=5)
        said = b''.join(self.errors[-5:]).decode('utf-8', 'replace').strip()
        why = f'the ssh connection ended (exit {self.child.poll()}){": " + said if said else ""}; open a new session'
        return {'error': why, 'fatal': True}

    def stop(self) -> None:
        """Ask the remote shell to exit, then make sure the child is gone."""
        with contextlib.suppress(OSError):
            self.child.stdin.write(b'exit\n')
            self.child.stdin.close()
        try:
            self.child.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.child.kill()
            self.child.wait(timeout=10)


def _say(word: dict[str, Any]) -> None:
    os.write(sys.stdout.fileno(), (json.dumps(word) + '\n').encode('ascii'))  # a pipe to the opener, not a console
    devnull = os.open(os.devnull, os.O_WRONLY)
    os.dup2(devnull, sys.stdout.fileno())  # the opener stops reading; nothing more goes to its pipe


def _answer(conn: socket.socket, token: str, holder: Holder, one_run: threading.Lock) -> tuple[dict[str, Any], bool]:
    with conn.makefile('rb') as lines:
        asked = json.loads(lines.readline() or b'{}')
    if not hmac.compare_digest(str(asked.get('token', '')), token):
        return {'error': 'refused: wrong token'}, False
    verb = asked.get('verb')
    if verb == 'ping':  # live means the ssh child still runs: a holder outliving its connection is a dead hold
        alive = holder.child.poll() is None
        return {'ok': alive}, not alive
    if verb == 'close':
        return {'ok': True}, True
    if verb == 'run':
        with one_run:  # one ssh connection carries one command at a time; a ping never waits behind it
            reply = holder.exchange(
                str(asked.get('command', '')), float(asked.get('timeout_s', sshholdrun.DEFAULT_TIMEOUT_S))
            )
        return reply, bool(reply.get('fatal', False))
    return {'error': f'unknown verb {verb!r}'}, False


def serve(dest: str, hours: float, holder: Holder, listener: socket.socket) -> None:
    """Record the session, then answer each client on its own thread until a verb, the ceiling or an idle limit.

    Runs share the one ssh connection under a lock; a ping or a close answers at once, so a holder busy with a
    long run is never read as dead (measured 2026-11-20: pings waited behind a deploy, timed out, and the live
    session's state was deleted).
    """
    opened = time.time()
    token = secrets.token_urlsafe(32)
    session = sshholdstate.Session(dest, os.getpid(), listener.getsockname()[1], token, opened, opened + hours * 3600)
    sshholdstate.write_session(session)
    idle, last = sshhold.idle_s(), [time.monotonic()]
    ending, one_run = threading.Event(), threading.Lock()

    def client(conn: socket.socket) -> None:
        with conn:
            conn.settimeout(None)
            reply, ends = _answer(conn, token, holder, one_run)
            with contextlib.suppress(OSError):
                conn.sendall(json.dumps(reply).encode('utf-8') + b'\n')
        last[0] = time.monotonic()
        if ends:
            ending.set()

    _say({'ok': True, 'pid': session.pid})
    listener.settimeout(_TICK_S)
    try:
        while not ending.is_set() and not sshhold.session_over(
            now=time.time(), expires=session.expires, quiet_s=time.monotonic() - last[0], idle=idle
        ):
            try:
                conn, _ = listener.accept()
            except TimeoutError:
                continue
            threading.Thread(target=client, args=(conn,), daemon=True).start()
        if not ending.is_set():
            sshholdstate.audit('expire', dest, status=0)
    finally:
        holder.stop()
        sshholdstate.forget(dest)


def main(argv: list[str] | None = None) -> int:
    """Hold one connection to the given dest; see the module docstring."""
    parser = argparse.ArgumentParser(prog='python -m dev_lab.dev._sshholder')
    parser.add_argument('dest')
    parser.add_argument('--hours', type=float, required=True)
    parser.add_argument('--ssh', default='["ssh"]', help='the ssh program argv, JSON (a test injects a fake)')
    args = parser.parse_args(argv)
    code = sys.stdin.buffer.readline().decode('utf-8').rstrip('\r\n')
    holder = Holder(ssh_argv(json.loads(args.ssh), args.dest), code)
    del code
    probe = holder.exchange('echo ready', _PROBE_S)
    if 'error' in probe:
        holder.stop()
        _say({'error': f'not authenticated: {probe["error"]}'})
        return 1
    with socket.create_server(('127.0.0.1', 0)) as listener:
        serve(args.dest, args.hours, holder, listener)
    return 0


if __name__ == '__main__':
    sys.exit(main())
