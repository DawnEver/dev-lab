"""THE ONE SSH TRANSPORT the remote doors share: how a command reaches a host, never what it runs or where.

User ruling 2026-11-07: ssh has two kinds of target, and each has its own honestly named door --
:mod:`dev_lab.dev.hpcaccount` (a cluster account: deploy, tick, cron) and :mod:`dev_lab.dev.opsserver` (a server
the integrator deploys: the ops door's fixed verbs). Both build their argv and start it here, so the ssh options,
the quoting and the detached launch exist once. A hand-written ssh WRITE to a remote host is refused by the deny
row ``REMOTE-WRITE-THROUGH-A-DOOR``, which names those two doors; read-only ssh stays open.
"""

from __future__ import annotations

import os
import shlex
import subprocess
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import IO, Any, Final

import lab_commons.launch as _door
from lab_commons.config import section
from lab_commons.temp import TEMP_PREFIX

__all__ = [
    'CONNECT_TIMEOUT_S',
    'HOST_KEYS_DECLARATION',
    'HOST_KEY_RULE',
    'HOST_KEY_UNFILLED',
    'HostKeyUndeclared',
    'declared_known_hosts',
    'declared_piped',
    'detached',
    'host_key_line',
    'host_key_options',
    'named',
    'piped',
    'run',
    'ssh_argv',
]

#: How long ssh waits for a host before it gives up.
CONNECT_TIMEOUT_S: Final = 20

#: The rule a declared endpoint's host key is checked under: declared once, checked strictly, never learned on use.
HOST_KEY_RULE: Final = 'SSH-HOST-KEY-DECLARED'
#: Where an endpoint host's key is declared: one line per host, ``"<host>" = "<type> <base64>"``.
HOST_KEYS_DECLARATION: Final = 'hosts-config family.toml [ssh.host_keys]'
#: The placeholder a not-yet-filled host key holds: never a plausible key, refused by name on use.
HOST_KEY_UNFILLED: Final = 'FILL-FROM-A-TRUSTED-SOURCE'
#: What ssh prints when the presented host key is not the one it was told to expect.
_MISMATCH: Final = 'Host key verification failed'
#: The key types a declaration may hold.
_KEY_TYPES: Final = ('ssh-ed25519', 'ecdsa-sha2-nistp256', 'ecdsa-sha2-nistp384', 'ecdsa-sha2-nistp521', 'ssh-rsa')


class HostKeyUndeclared(ValueError):
    """An endpoint's host key is missing, a placeholder, or not a key line: the door refuses before ssh runs."""


def _host(target: str) -> str:
    return target.rsplit('@', 1)[-1]


def _fill(host: str) -> str:
    return (
        f'declare it as {HOST_KEYS_DECLARATION} "{host}" = "<type> <base64>", copied from a TRUSTED source -- the '
        "server's /etc/ssh/ssh_host_ed25519_key.pub read over an already-trusted session, or a trusted machine's "
        f'known_hosts entry (`ssh-keygen -F {host}`) -- never an ssh-keyscan from this machine; merge that change, '
        'then run `python -m dev_lab.dev.devhost render` here'
    )


def host_key_line(target: str, declared: Mapping[str, object]) -> str:
    """The known_hosts line for *target*'s host (``user@host``) from *declared* (host -> ``"<type> <base64>"``).

    Raises:
        HostKeyUndeclared: no key, the :data:`HOST_KEY_UNFILLED` placeholder, or not a ``<type> <base64>`` line.

    """
    host = _host(target)
    key = declared.get(host)
    parts = key.split() if isinstance(key, str) else []
    if not parts:
        why = 'is not declared'
    elif HOST_KEY_UNFILLED in key:
        why = f'is still the placeholder {HOST_KEY_UNFILLED}'
    elif not parts[1:] or parts[0] not in _KEY_TYPES:  # a type and its base64
        why = f'{key!r} is not a "<type> <base64>" key line ({", ".join(_KEY_TYPES)})'
    else:
        return f'{host} {parts[0]} {parts[1]}'
    msg = f'{HOST_KEY_RULE}: the ssh host key of {host} {why}; nothing was sent: {_fill(host)}'
    raise HostKeyUndeclared(msg)


def named(target: str, said: str) -> str:
    """*said*, ssh's own words about *target*, with a host-key mismatch named: the rule, the declaration, the fill."""
    if _MISMATCH not in said:
        return said
    host = _host(target)
    return (
        f'{said}\n{HOST_KEY_RULE}: {host} presented a host key that is not the declared one -- the declaration is '
        f'wrong or this is not {host}; check it, never accept the presented key: {_fill(host)}'
    )


def declared_known_hosts(target: str, host_keys: Mapping[str, object]) -> str | None:
    """The known_hosts file holding only *target*'s DECLARED host key, or None when its host declares none.

    The file (one per host, under the temp root) is rewritten from the declaration on every call, so ssh never
    checks against a key it learned elsewhere (:data:`HOST_KEY_RULE`). It outlives the call: a detached ssh reads it.

    Raises:
        HostKeyUndeclared: the host is declared but its entry is a placeholder or not a key line.

    """
    if _host(target) not in host_keys:
        return None
    entry = host_key_line(target, host_keys)
    folder = Path(tempfile.gettempdir()) / f'{TEMP_PREFIX}known-hosts'
    folder.mkdir(parents=True, exist_ok=True)
    known = folder / _host(target)
    known.write_text(entry + '\n', encoding='utf-8')
    return str(known)


def host_key_options(
    target: str, host_keys: Mapping[str, object] | None = None, *, required: bool = False
) -> list[str]:
    """The ssh options checking *target*'s host key strictly against its DECLARED key alone: THE ONE RESOLVER.

    *host_keys* is the declared ``[ssh] host_keys`` (None: this machine's own declaration). A host declared there
    gets a known_hosts holding that key only (:func:`declared_known_hosts`); an undeclared host keeps ssh's default
    (no option) unless *required* -- a door to a server, whose key must be declared -- which refuses it by name.

    Raises:
        HostKeyUndeclared: a placeholder or malformed declaration, or none at all when *required*; ssh never ran.

    """
    if host_keys is None:
        declared = section('ssh').get('host_keys')
        host_keys = declared if isinstance(declared, dict) else {}
    if required:
        host_key_line(target, host_keys)
    known = declared_known_hosts(target, host_keys)
    return ['-o', f'UserKnownHostsFile={known}', '-o', 'StrictHostKeyChecking=yes'] if known else []


def ssh_argv(
    target: str, command: str, *, batch: bool, host_keys: Mapping[str, object] | None = None, required: bool = False
) -> list[str]:
    """The ssh argv running *command* (a POSIX shell line) as a login shell on *target* (``user@host``).

    *batch* true never prompts (a key-only account: a cluster); false allocates a terminal for an account whose
    login asks a second factor (a server's ops account: key AND a one-time code typed by the user).

    The host key is checked as :func:`host_key_options` says, *host_keys* and *required* passed through.

    Raises:
        HostKeyUndeclared: as :func:`host_key_options`; nothing was started.

    """
    hosts = host_key_options(target, host_keys, required=required)
    mode = ['-o', 'BatchMode=yes'] if batch else ['-t']
    timeout = ['-o', f'ConnectTimeout={CONNECT_TIMEOUT_S}']
    return ['ssh', *mode, *timeout, *hosts, target, f'bash -lc {shlex.quote(command)}']


def detached(argv: Sequence[str], log: IO[Any]) -> object:
    """Start *argv* detached from this session, everything it prints into *log*; returns the process."""
    # The door adds CREATE_NO_WINDOW; DETACHED_PROCESS would leave the windowless console the serve child inherits.
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0
    return _door.popen(
        list(argv),
        stdin=subprocess.DEVNULL,
        stdout=log,
        stderr=subprocess.STDOUT,
        creationflags=flags,
        start_new_session=os.name != 'nt',
    )


def run(argv: Sequence[str], *, timeout_s: float) -> int:
    """Run *argv* in the foreground, attached to this terminal (a second factor is typed there); its exit code."""
    return _door.run(list(argv), check=False, timeout=timeout_s).returncode


def piped(
    target: str, line: str, *, identity: str | None, timeout_s: float, known_hosts: str | None = None
) -> tuple[int, str]:
    """Send *line* on stdin to *target*'s forced command over ``ssh -T`` (key-only, never prompts).

    ``(exit status, its answer)``; the remote account's forced command decides what runs, never the caller.
    A success answers its stdout ALONE: the remote's notices go to stderr and never ride into the answer (2026-11-11,
    an upgrade-on-read notice beside the consent issuer's JSON lost a spent code's credentials). A failure keeps
    stderr too, because its reason (``refused: ...``) is written there.

    *known_hosts* is the file the target's host key is checked against, strictly (a root door on a host whose root
    keeps no ``~/.ssh``); ``None`` leaves ssh's own default.
    """
    key = ['-i', identity] if identity else []
    hosts = ['-o', f'UserKnownHostsFile={known_hosts}', '-o', 'StrictHostKeyChecking=yes'] if known_hosts else []
    argv = ['ssh', '-T', '-o', 'BatchMode=yes', '-o', f'ConnectTimeout={CONNECT_TIMEOUT_S}', *key, *hosts, target]
    done = _door.run(argv, input=line, capture_output=True, text=True, encoding='utf-8', check=False, timeout=timeout_s)
    if done.returncode == 0:
        return 0, done.stdout.strip()
    return done.returncode, named(target, (done.stdout + done.stderr).strip())


def declared_piped(
    target: str, line: str, *, identity: str | None, timeout_s: float, host_keys: Mapping[str, object]
) -> tuple[int, str]:
    """:func:`piped` to *target*, its host key checked strictly against the DECLARED one in *host_keys*.

    The known_hosts ssh reads is built from the declaration for this one call and holds nothing else, so a key ssh
    learned elsewhere never vouches for a declared endpoint (:data:`HOST_KEY_RULE`).

    Raises:
        HostKeyUndeclared: *target*'s host has no usable declaration (:func:`host_key_line`); ssh never ran.

    """
    entry = host_key_line(target, host_keys)
    with tempfile.TemporaryDirectory(prefix=f'{TEMP_PREFIX}known-hosts-') as tmp:
        known = Path(tmp) / 'known_hosts'
        known.write_text(entry + '\n', encoding='utf-8')
        return piped(target, line, identity=identity, timeout_s=timeout_s, known_hosts=str(known))
