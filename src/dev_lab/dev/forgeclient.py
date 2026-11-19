"""FORGE CLIENTS, MADE: the one place a :class:`~dev_lab.dev.forgework.Client` is built for a checkout or a forge.

:func:`client_for` builds the client for a checkout's remote (or another repository's URL) with its provenance
stamp, write journal and caches; :func:`stored_client` presents the credential git's store holds for a forge (or a
workflow job's token), refreshed as git does on a 401.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

from dev_lab.dev import forge as _forge
from dev_lab.dev._forge_journal import journal_at, outbox_dir
from dev_lab.dev._forgebackends import actions_token, backend_for
from dev_lab.dev.forge import Forge, Transport, forge_from_remote, forge_of_url, forge_transport
from dev_lab.dev.forgecred import CredentialRefresh
from dev_lab.dev.forgestamp import provenance
from dev_lab.dev.forgework import Client

__all__ = ['client_for', 'stored_client']


def client_for(
    root: Path,
    *,
    env: Mapping[str, str] | None = None,
    transport: Transport = forge_transport,
    remote: str = 'origin',
    url: str = '',
    token: str = '',
    outbox: Path | None = None,
) -> Client:
    """The client for *root*'s *remote* (or another repository's *url*), its token and provenance stamp.

    A *token* given is the job token a workflow handed over by file (the review door, :mod:`reviewgitauth`).
    Its journal and caches live in *outbox*: given by a role that holds no checkout (the judge's declared state),
    else *root*'s main checkout's (:func:`~dev_lab.dev._forge_journal.outbox_dir`).
    """
    forge = forge_of_url(url) if url else forge_from_remote(root, remote=remote)
    stamp = provenance(root, os.environ if env is None else env)
    built = stored_client(forge, cwd=root, env=env, transport=transport, stamp=stamp, token=token)
    built.cache_dir = outbox_dir(root) if outbox is None else outbox
    built.journal = journal_at(built.cache_dir)
    return built


def stored_client(
    forge: Forge,
    *,
    cwd: Path,
    env: Mapping[str, str] | None = None,
    transport: Transport = forge_transport,
    stamp: str | None = None,
    token: str = '',
) -> Client:
    """A client presenting the credential git's store holds for *forge*, refreshed as git does on a 401.

    Inside a workflow job on the forge's own Actions the job token is the credential, never refreshed: the
    *token* given, else the job's env (:func:`actions_token`).

    Raises:
        NoCredential: the store holds no credential for the host.

    """
    if job := token or actions_token(forge, os.environ if env is None else env):
        return Client(forge, job, transport=transport, username=backend_for(forge).actions_login, stamp=stamp)
    username, secret = _forge.credential_for(forge.host, cwd=cwd, env=env)

    def refresh(refused_user: str, refused: str) -> CredentialRefresh:
        return _forge.refresh_credential(forge.host, (refused_user, refused), cwd=cwd, env=env)

    return Client(forge, secret, transport=transport, username=username, stamp=stamp, refresh=refresh)
