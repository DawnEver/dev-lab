"""The forge key file: one ``<username>@<host> <token>`` line per credential, read whole or refused whole.

Split out of :mod:`dev_lab.dev.forgeauth` (2026-11-10, MODULE-SIZE-ALARM): ``auth export`` writes this file and
``auth login --from-file`` reads it; the format and its refusals are one fact, kept here, with both verbs.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Final, NamedTuple, TextIO

from lab_commons.log import emit

from dev_lab.dev.forge import Forge, NoCredential, credential_for, store_credential
from dev_lab.dev.forgefailure import ForgeCallFailed
from dev_lab.dev.forgework import Client

if TYPE_CHECKING:
    from pathlib import Path

    from dev_lab.dev.forge import Transport

__all__ = ['USAGE', 'KeyLine', 'digest', 'export_keys', 'format_key_file', 'import_keys', 'parse_key_file']

#: The exit status of a refused invocation (argparse's).
USAGE: Final = 2

#: A key file line's fields: ``<username>@<host>`` and the token.
_KEY_FIELDS: Final = 2
# A host the token is SENT to: a DNS name, an IPv4 or a bracketed IPv6, with an optional numeric port -- never a path,
# query, fragment or userinfo, which would turn a key file into a forwarder of the token to any URL.
_LABEL: Final = r'[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?'
_HOST: Final = re.compile(rf'(?:{_LABEL}(?:\.{_LABEL})*|\[[0-9A-Fa-f:.]+\])(?::[0-9]{{1,5}})?')


class KeyLine(NamedTuple):
    """One credential of a key file: ``<username>@<host> <token>``."""

    host: str
    username: str
    token: str


def format_key_file(keys: Sequence[KeyLine]) -> str:
    """The key file :func:`parse_key_file` reads back: one ``<username>@<host> <token>`` line per key."""
    head = '# forge credentials: python -m dev_lab.dev.forge auth login --from-file <this file|->\n'
    return head + ''.join(f'{k.username}@{k.host} {k.token}\n' for k in keys)


def parse_key_file(text: str) -> tuple[KeyLine, ...]:
    """Every key of *text*; a malformed or repeated line refuses the WHOLE file, naming its number only.

    Raises:
        ValueError: a line is not ``<username>@<host> <token>``, its host is not a bare name with an optional
            port, or it names one username of a host twice.

    """
    keys: dict[tuple[str, str], KeyLine] = {}
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        fields = line.split()
        username, at, host = fields[0].rpartition('@')
        if len(fields) != _KEY_FIELDS or not (at and username and host):
            msg = f'key file line {number}: expected `<username>@<host> <token>`'
            raise ValueError(msg)
        if not _HOST.fullmatch(host):
            msg = f'key file line {number}: host is not a bare name with an optional port'
            raise ValueError(msg)
        if (host, username) in keys:
            msg = f'key file line {number}: {username}@{host} named twice'
            raise ValueError(msg)
        keys[host, username] = KeyLine(host, username, fields[1])
    return tuple(keys.values())


def digest(token: str) -> str:
    """A token's sha256 prefix: what output names instead of the secret."""
    return hashlib.sha256(token.encode()).hexdigest()[:8]


def export_keys(hosts: Sequence[str], root: Path, env: Mapping[str, str] | None, out: TextIO) -> int:
    """``auth export``: every stored credential of *hosts* as a key file on *out*, never a terminal."""
    if out.isatty():
        emit('[forge] auth export writes secrets: pipe or redirect it, never to a terminal', err=True)
        return USAGE
    keys, missing = [], []
    for host in dict.fromkeys(hosts):
        try:
            username, token = credential_for(host, cwd=root, env=env)
        except NoCredential:
            missing.append(host)
            continue
        keys.append(KeyLine(host, username, token))
    out.write(format_key_file(keys))
    out.flush()
    named = ', '.join(f'{k.username}@{k.host} sha256:{digest(k.token)}' for k in keys)
    emit(f'[forge] exported {len(keys)} credential(s): {named or "none"}', err=True)
    if missing:
        emit(f'[forge] no credential stored for: {", ".join(missing)}', err=True)
    return 0 if keys else 1


def import_keys(text: str, root: Path, env: Mapping[str, str] | None, transport: Transport) -> int:
    """``auth login --from-file``: verify every token of *text*, then store them all, or none."""
    try:
        keys = parse_key_file(text)
    except ValueError as malformed:
        emit(f'[forge] {malformed}; nothing was stored', err=True)
        return USAGE
    if not keys:
        emit('[forge] the key file holds no credential; nothing was stored', err=True)
        return USAGE
    for key in keys:
        try:
            Client(Forge(key.host, '', ''), key.token, transport=transport).whoami()
        except ForgeCallFailed as failed:
            emit(
                f'[forge] {key.host} refused the token of {key.username}: NOT stored, nor any other. {failed}', err=True
            )
            return 1
    try:
        for key in keys:
            store_credential(key.host, key.username, key.token, cwd=root, env=env)
    except NoCredential as refused:
        emit(f'[forge] {refused}', err=True)
        return 1
    emit(f'[forge] stored {len(keys)} credential(s): {", ".join(f"{k.username}@{k.host}" for k in keys)}')
    return 0
