"""``ops github whoami --file P``: whose GitHub token a DECLARED secret file holds, and its scopes -- never its value.

A host's GitHub credentials are files its config declares (:func:`dev_lab.ops.secretplace.declared`). Before one is
retired or replaced, the operator must know what it IS: a classic personal token (``GET /user`` names the login and
GitHub answers its scopes in ``X-OAuth-Scopes``), a fine-grained one (no scope header), or an App installation token
(GitHub refuses ``/user`` to an integration). The value is presented to GitHub once and never said; a refusal names
GitHub's status and message, which carry no credential.
"""

from __future__ import annotations

import json
from http import HTTPStatus
from pathlib import Path
from typing import TYPE_CHECKING, Final

from lab_commons.log import emit

from dev_lab.dev.forge import forge_transport
from dev_lab.ops.secretplace import declared

if TYPE_CHECKING:
    import argparse
    from collections.abc import Iterable

    from dev_lab.dev.forge import Transport
    from dev_lab.ops.config import OpsConfig

__all__ = ['WhoRefused', 'add_parser', 'declared_file', 'run', 'say', 'whoami']

_API: Final = 'api.github.com'
_INTEGRATION: Final = 'not accessible by integration'


class WhoRefused(RuntimeError):
    """The file is undeclared, or GitHub refused the token: what was refused, never the value."""


def declared_file(declared: Iterable[str], path: str) -> Path:
    """*path* when the host declares it as a secret file; refused before anything reads it otherwise."""
    if path not in set(declared):
        msg = f'{path} is not a secret file this host declares; declared: {sorted(declared) or "none"}'
        raise WhoRefused(msg)
    return Path(path)


def whoami(path: Path, *, transport: Transport = forge_transport) -> str:
    """What the token in *path* is, value-free: ``user <login>; scopes: <list>`` or an App installation token."""
    token = path.read_text(encoding='utf-8').strip()
    connection = transport(_API, 30.0)
    try:
        headers = {'Authorization': f'Bearer {token}', 'Accept': 'application/vnd.github+json', 'User-Agent': 'dev-lab'}
        connection.request('GET', '/user', headers=headers)
        answer = connection.getresponse()
        status, raw = answer.status, answer.read()
        scopes = answer.getheader('X-OAuth-Scopes')
    finally:
        connection.close()
    body = json.loads(raw or b'{}')
    message = str(body.get('message', '')) if isinstance(body, dict) else ''
    if status == HTTPStatus.OK and isinstance(body, dict):
        listed = sorted(one.strip() for one in scopes.split(',') if one.strip()) if scopes else []
        return f'user {body.get("login")}; scopes: {", ".join(listed) or "none listed"}'
    if status == HTTPStatus.FORBIDDEN and _INTEGRATION in message:
        return 'an App installation token (GitHub refuses /user to an integration)'
    msg = f'GitHub refused the token in {path}: {status} {message}'
    raise WhoRefused(msg)


def say(text: str) -> None:
    """Say *text* (already value-free) through the kit's one console writer."""
    emit(text)


def add_parser(verbs: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """``github whoami --file P``: read-only; no consent, as it changes nothing and says no value."""
    asked = verbs.add_parser('github', help='say whose GitHub token a declared secret file holds, never its value')
    asked.add_argument('action', choices=('whoami',))
    asked.add_argument('--file', required=True, help='a secret file this host config declares')


def run(config: OpsConfig, args: argparse.Namespace) -> int:
    """The ``github`` verb: 0 with the answer said, 2 when the file is undeclared or GitHub refused the token."""
    try:
        say(whoami(declared_file(declared(config), args.file)))
    except (WhoRefused, OSError) as refused:
        emit(f'refused: {refused}', err=True)
        return 2
    return 0
