"""The forge key file: one ``<username>@<host> <token>`` line per credential, read whole or refused whole.

Split out of :mod:`dev_lab.dev.forgeauth` (2026-11-10, MODULE-SIZE-ALARM): ``auth export`` writes this file and
``auth login --from-file`` reads it; the format and its refusals are one fact, kept here.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Final, NamedTuple

__all__ = ['KeyLine', 'format_key_file', 'parse_key_file']

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
