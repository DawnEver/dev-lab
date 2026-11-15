"""``forge token whoami --role R [--forge HOST]``: which Gitea login a configured token file authenticates as.

A role's token per forge is a root-600 file named in its ``tokens`` table (``[ops.breakglass.tokens]``,
``[ops.probe.tokens]``, ``[ops.judge.tokens]``); nothing records whose token it is, so the login's access cannot be
declared under ``[ops.forge.accounts]``. Run as root through the fixed ``forge *`` sudo line, this reads the file,
asks Gitea ``GET /api/v1/user`` for the login, and ``GET /api/v1/repos/{owner}/{repo}`` for each of the role's repos
on that forge: ``readable`` or ``not readable (<status>)``. Read-only, so no consent. The token is presented to Gitea
and never said: the answer names the login and a sha256 prefix of the token at most.
"""

from __future__ import annotations

import hashlib
import json
from http import HTTPStatus
from pathlib import Path
from typing import TYPE_CHECKING, Final

from lab_commons.log import emit

from dev_lab.dev.forge import forge_of_url, forge_transport

if TYPE_CHECKING:
    import argparse
    from collections.abc import Mapping

    from dev_lab.dev.forge import Transport
    from dev_lab.ops.config import Breakglass, Judge, OpsConfig, Probe

__all__ = ['ROLES', 'WhoRefused', 'run', 'whoami']

#: The ops roles whose config table holds ``repos`` and a ``tokens`` file per forge host.
ROLES: Final = ('breakglass', 'probe', 'judge')


class WhoRefused(RuntimeError):
    """The role or forge is not configured, or Gitea refused the token: what was refused, never the value."""


def _get(host: str, path: str, token: str, transport: Transport) -> tuple[int, object]:
    """One authenticated GET on *host*; its status and parsed body (``None`` when it does not parse)."""
    connection = transport(host, 30.0)
    try:
        connection.request('GET', path, headers={'Authorization': f'token {token}', 'Accept': 'application/json'})
        answer = connection.getresponse()
        status, raw = answer.status, answer.read()
    finally:
        connection.close()
    try:
        return status, json.loads(raw or b'null')
    except ValueError:
        return status, None


def _host(tokens: Mapping[str, str], forge: str | None, role: str) -> str:
    """*forge* when *role* holds a token for it, else the one host it holds; refused otherwise."""
    if forge is None and len(tokens) == 1:
        return next(iter(tokens))
    if forge is not None and forge in tokens:
        return forge
    msg = f'[ops.{role}.tokens] holds {sorted(tokens) or "no forge"}; name one with --forge'
    raise WhoRefused(msg)


def whoami(
    tokens: Mapping[str, str], repos: tuple[str, ...], *, role: str, forge: str | None = None,
    transport: Transport = forge_transport,
) -> list[str]:  # fmt: skip
    """The login *role*'s token on *forge* authenticates as, then each of its repos there: readable or not.

    Raises:
        WhoRefused: no token for that forge, or Gitea refused ``/user``.
        OSError: the token file cannot be read.

    """
    host = _host(tokens, forge, role)
    token = Path(tokens[host]).read_text(encoding='utf-8').strip()
    status, body = _get(host, '/api/v1/user', token, transport)
    if status != HTTPStatus.OK or not isinstance(body, dict):
        msg = f'{host} refused the {role} token in {tokens[host]}: {status}'
        raise WhoRefused(msg)
    digest = hashlib.sha256(token.encode('utf-8')).hexdigest()[:8]
    lines = [f'{host}: {role} token (sha256 {digest}) is login {body.get("login")}']
    for url in repos:
        place = forge_of_url(url)
        if place.host != host:
            continue
        seen, _ = _get(host, f'/api/v1/repos/{place.owner}/{place.repo}', token, transport)
        said = 'readable' if seen == HTTPStatus.OK else f'not readable ({seen})'
        lines.append(f'  {place.owner}/{place.repo}: {said}')
    return lines


def _placement(config: OpsConfig, role: str) -> Breakglass | Probe | Judge | None:
    """The config table of *role* (one of :data:`ROLES`)."""
    return {'breakglass': config.breakglass, 'probe': config.probe, 'judge': config.judge}[role]


def run(config: OpsConfig, args: argparse.Namespace) -> int:
    """``forge token whoami``: 0 with the login said, 2 when not configured or refused."""
    placement = _placement(config, args.role)
    if placement is None:
        emit(f'refused: {config.path} enables no [ops.{args.role}]', err=True)
        return 2
    try:
        for line in whoami(placement.tokens, placement.repos, role=args.role, forge=args.forge):
            emit(line)
    except (WhoRefused, OSError) as refused:
        emit(f'refused: {refused}', err=True)
        return 2
    return 0
