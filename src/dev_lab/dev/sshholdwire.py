"""SSHHOLD WIRE: the client's half of the holder's protocol -- one JSON request on 127.0.0.1, and the marker frame.

Split out of :mod:`dev_lab.dev.sshhold` (the session's policy and CLI); the holder (:mod:`dev_lab.dev._sshholder`)
writes :func:`frame` and reads :func:`split_marker`, the client sends :func:`request` behind the session's token.
"""

from __future__ import annotations

import json
import re
import socket
from typing import Any, Final

from dev_lab.dev.sshholdstate import Session, read_session

__all__ = ['HoldRefused', 'frame', 'live', 'ping', 'request', 'split_marker']

CONNECT_S: Final = 5.0


class HoldRefused(RuntimeError):
    """A session verb that cannot proceed; the message says why and what to do."""


def frame(command: str, nonce: str) -> str:
    """*command* as the holder writes it to the remote shell: merged streams, then the marker with ``$?``."""
    return f'{{ {command}\n}} 2>&1; printf \'\\n__SSHHOLD_{nonce}_%s\\n\' "$?"\n'


def split_marker(text: str, nonce: str) -> tuple[str, int] | None:
    """``(output, status)`` once *text* ends on *nonce*'s marker line; ``None`` while it has not."""
    found = re.search(rf'\n__SSHHOLD_{re.escape(nonce)}_(\d+)\r?\n\Z', text)
    return None if found is None else (text[: found.start()], int(found.group(1)))


def request(session: Session, payload: dict[str, Any], timeout_s: float) -> dict[str, Any]:
    """Send *payload* with the token and read the one JSON reply; :class:`OSError` when the holder is gone."""
    with socket.create_connection(('127.0.0.1', session.port), timeout=CONNECT_S) as conn:
        conn.settimeout(timeout_s)
        conn.sendall(json.dumps({**payload, 'token': session.token}).encode('utf-8') + b'\n')
        with conn.makefile('rb') as reply:
            line = reply.readline()
    if not line:
        msg = 'the holder closed the connection without a reply'
        raise OSError(msg)
    return json.loads(line)


def live(dest: str) -> Session:
    """*dest*'s recorded session, or :class:`HoldRefused` naming the door for each host kind."""
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


def ping(session: Session) -> bool:
    """Whether *session*'s holder answers."""
    try:
        return request(session, {'verb': 'ping'}, CONNECT_S).get('ok') is True
    except (OSError, ValueError):
        return False
