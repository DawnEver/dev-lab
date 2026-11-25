"""CLIENT KEYS ARE DERIVED: the ssh keys a host's approval accounts accept come from the machines that declare them.

A development machine declares its own ssh client key(s) ONCE, in its host file (``[dev] client_keys``, checked by
:mod:`dev_lab.dev.devschema`). A host whose ``[ops.config]`` declares ``clients = "<dir>"`` never lists those keys
by hand: :func:`dev_lab.ops.configdoor.fetch` reads every ``<dir>/*.toml`` of the same reviewed clone, :func:`derive`
collects the development machines' keys (only a development machine's file has ``[dev]``), and :func:`fold`
appends them to the candidate as the DERIVED ``[ops.clients]`` table. :func:`dev_lab.ops.config.load` adds that set
to ``[ops.breakglass] keys`` and ``[ops.consent] keys`` (each keeps its own declared keys, e.g. a server's), and
``ops install`` writes the accounts' key files from the result.

So a new or migrated workstation is authorized by ONE reviewed line in its own host file; the change reaches the
server as a boundary change (``ops.clients.keys`` is not routine), applied with an ``ops.config`` consent like any
other key that decides who may log in. A host file that writes ``[ops.clients]`` itself is refused: the table is the
door's output, never an input.
"""

from __future__ import annotations

import json
import re
import tomllib
from collections.abc import Mapping
from typing import Final

__all__ = ['DEV_KEY', 'TABLE', 'defects', 'derive', 'fold']

#: The derived ``[ops.<TABLE>]`` table a fetch appends to the candidate.
TABLE: Final = 'clients'
#: The ``[dev]`` key a development machine declares its ssh client public keys under.
DEV_KEY: Final = 'client_keys'

#: One OpenSSH public key line: a key type, its base64 blob, an optional comment.
_PUBLIC_KEY: Final = re.compile(r'^(ssh-ed25519|ssh-rsa|ecdsa-sha2-nistp(256|384|521)|sk-ssh-ed25519@openssh\.com) '
                                r'[A-Za-z0-9+/]+={0,3}( \S.*)?$')  # fmt: skip


def defects(keys: object, where: str) -> list[str]:
    """Why *keys* is not a list of OpenSSH public key lines (no private key, no blank); ``[]`` when it is."""
    if not isinstance(keys, list) or not keys:
        return [f'{where} must be a non-empty list of OpenSSH public key lines']
    return [
        f'{where}[{index}] is not an OpenSSH public key line ("<type> <base64> [comment]")'
        for index, key in enumerate(keys)
        if not isinstance(key, str) or not _PUBLIC_KEY.match(key)
    ]


def derive(files: Mapping[str, str]) -> tuple[str, ...]:
    """Every development machine's declared client key, from *files* (file name -> text), ordered by name, once each.

    Raises:
        ValueError: a file is not TOML or declares a malformed key -- naming the file; nothing is derived.

    """
    keys: list[str] = []
    for name in sorted(files):
        try:
            parsed = tomllib.loads(files[name])
        except tomllib.TOMLDecodeError as bad:
            msg = f'{name} is not TOML ({bad}): no client key is derived'
            raise ValueError(msg) from bad
        dev = parsed.get('dev')
        if not isinstance(dev, Mapping) or DEV_KEY not in dev:  # an HPC account's file has no [dev]
            continue
        if found := defects(dev[DEV_KEY], f'{name} [dev] {DEV_KEY}'):
            raise ValueError('; '.join(found))
        keys += [key for key in dev[DEV_KEY] if key not in keys]
    return tuple(keys)


def fold(text: str, keys: tuple[str, ...], where: str) -> str:
    """*text* (a host file) with the derived ``[ops.clients] keys`` appended, from *where* (the directory read).

    Raises:
        ValueError: *text* declares ``[ops.clients]`` itself -- the table is derived, never written by hand.

    """
    if TABLE in tomllib.loads(text).get('ops', {}):
        msg = (f'the host file declares [ops.{TABLE}] by hand: it is DERIVED from {where}/*.toml [dev] {DEV_KEY}; '
               f'declare a machine key in its own host file instead')  # fmt: skip
        raise ValueError(msg)
    rows = ''.join(f'  {json.dumps(key)},\n' for key in keys)
    header = f'# DERIVED by config fetch from {where}/*.toml [dev] {DEV_KEY}: never edit'
    return f'{text.rstrip()}\n\n{header}\n[ops.{TABLE}]\nkeys = [\n{rows}]\n'
