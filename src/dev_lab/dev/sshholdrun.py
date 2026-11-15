"""SSHHOLD RUN: a command, or a forge credential, sent through a held session -- and what the audit keeps of it.

Split out of :mod:`dev_lab.dev.sshhold` (the session's policy and CLI). A ``run`` is audited VERBATIM, so a secret
never rides the command: it is stdin heredoc DATA (:func:`stdin_script`) or a credential (:func:`store_credential`).
"""

from __future__ import annotations

import base64
import hashlib
import re
import secrets
import time
from typing import Any, Final
from urllib.parse import urlsplit

from dev_lab.dev.sshholdstate import audit, forget
from dev_lab.dev.sshholdwire import HoldRefused, live, request

__all__ = ['DEFAULT_TIMEOUT_S', 'credential_script', 'run_command', 'stdin_script', 'store_credential']

#: One command's bound; past it the session closes, since a half-read stream cannot be trusted.
DEFAULT_TIMEOUT_S: Final = 600.0
#: The remote status of a credential refused for want of a git credential helper.
_NO_HELPER: Final = 3


def _exchange(dest: str, command: str, timeout_s: float) -> dict[str, Any]:
    """Send *command* through *dest*'s holder; the reply, or :class:`HoldRefused` when the holder is gone."""
    session = live(dest)
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
