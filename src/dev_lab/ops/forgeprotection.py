"""``forge protect plan|apply --repo <owner/name> [--ref R]``: a repo's DECLARED branch protection, written by the host.

``python -m dev_lab.dev.forge protect apply`` needs a REPOSITORY admin, and no agent credential is one (user rulings
2026-11-09). The forge host is: its ``ops`` door reaches the local API as the site admin (:class:`GiteaCli`, a
short-lived token minted per use and deleted after it). So the host applies what the repo declares:

* the declaration is ``[tool.dev_lab.protection]`` in the repo's ``pyproject.toml`` AT ``--ref``, read through the
  local API (:func:`dev_lab.dev.reviewgate.manifest_at`) -- never a working tree;
* it is rendered by the client's own door (:func:`dev_lab.dev.forgeprotect.targets`,
  :func:`~dev_lab.dev.forgeprotect.plan`, :func:`~dev_lab.dev.forgeprotect.apply`) -- ONE renderer; this module
  renders nothing itself;
* the forge it renders for is this host's public one, ``[server] ROOT_URL`` in Gitea's ``app.ini``
  (:func:`public_host`), so the declaration's ``[tool.dev_lab.protection.forges."<host>"]`` row is the one it names;
* only a repo ``[ops.forge.accounts]`` names (:func:`declared_repos`) may be targeted -- an undeclared one is refused
  before the forge is asked anything.

``plan`` is read-only and needs no consent. ``apply`` redeems ONE :data:`ACTION` credential whose subject
(:meth:`Protection.subject`) binds the repo, the ref and the rendered protection's digest, so a grant cannot be
spent on another repo, ref or protection; ``--subject`` prints it, and nothing is written. Every apply is audited to
``[ops.forge] log``.
"""

from __future__ import annotations

import configparser
import dataclasses
import hashlib
import json
import os
import urllib.parse
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from lab_commons.log import emit

from dev_lab.dev import forgeprotect
from dev_lab.dev.forge import Forge as Remote
from dev_lab.dev.forgefailure import ForgeCallFailed
from dev_lab.dev.reviewgate import DeclarationUnread, manifest_at
from dev_lab.ops.consent.credential import ConsentRefused
from dev_lab.ops.forgerequests import digest
from dev_lab.ops.giteaadmin import ForgeRefused, GiteaCli, audit, local_api, run_argv

if TYPE_CHECKING:
    import argparse

    from dev_lab.dev._protect_steps import Step
    from dev_lab.ops.giteaadmin import Forge

__all__ = [
    'ACTION',
    'LocalRepo',
    'Protection',
    'add_parser',
    'apply',
    'declared_repos',
    'plan',
    'public_host',
    'rendered',
    'run',
]

#: The consent action of one ``forge protect apply`` (:mod:`dev_lab.ops.consent.actions`).
ACTION: Final = 'ops.forge.protect'
#: The ref whose declaration is applied when ``--ref`` names none.
DEFAULT_REF: Final = 'integrate/main'
_REFUSED: Final = 400

#: Redeems a credential on one subject (:func:`dev_lab.ops.consent.client.redeem`); raises when it does not.
type Redeem = Callable[[Mapping[str, Any], str], object]
#: One local API call ``(method, path, body=) -> (status, json)``: :meth:`GiteaCli.api`.
type LocalApi = Callable[..., tuple[int, Any]]


@dataclass(frozen=True)
class LocalRepo:
    """:class:`dev_lab.dev.forgeprotect.Api` on the host's local API; an error status raises :class:`ForgeRefused`."""

    name: str
    api: LocalApi

    @property
    def repo(self) -> str:
        """The repository's API collection path."""
        return f'/repos/{self.name}'

    def call(self, method: str, path: str, body: Mapping[str, Any] | None = None) -> object:
        """One local API call; its parsed body."""
        status, found = self.api(method, path, body=body)
        if status >= _REFUSED:
            msg = f'{method} {path}: HTTP {status}'
            raise ForgeRefused(msg)
        return found


@dataclass(frozen=True)
class Protection:
    """One repo's protection as rendered from its declaration at *ref*, on the host's public forge *remote*."""

    repo: str
    ref: str
    remote: Remote
    wanted: tuple[forgeprotect.Target, ...]

    def digest(self) -> str:
        """The SHA-256 of the rendered targets: every field the forge's rules are written from."""
        rows = [dataclasses.asdict(target) for target in self.wanted]
        return hashlib.sha256(json.dumps(rows, sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()

    def subject(self) -> str:
        """The digest an :data:`ACTION` credential's subject must equal: the repo, the ref and :meth:`digest`."""
        return digest(ACTION, {'repo': self.repo, 'ref': self.ref, 'protection': self.digest()})


def declared_repos(role: Forge) -> frozenset[str]:
    """Every ``owner/name`` ``[ops.forge.accounts]`` names: the repos this host serves, and so may protect."""
    return frozenset(str(repo) for row in role.accounts.values() for repo in row.get('repos', ()))


def public_host(role: Forge) -> str:
    """The host Gitea is served as: ``[server] ROOT_URL`` in its ``app.ini``, else ``DOMAIN``.

    Raises:
        ForgeRefused: the ``app.ini`` names neither.

    """
    ini = configparser.ConfigParser(interpolation=None)
    ini.read_string('[root]\n' + Path(role.config).read_text(encoding='utf-8'))
    root = ini.get('server', 'ROOT_URL', fallback='').strip().strip('"')
    host = urllib.parse.urlsplit(root).hostname or ini.get('server', 'DOMAIN', fallback='').strip().strip('"')
    if not host:
        msg = f'{role.config} names no [server] ROOT_URL or DOMAIN: the forge whose declaration applies is unknown'
        raise ForgeRefused(msg)
    return host


def rendered(role: Forge, api: forgeprotect.Api, repo: str, ref: str) -> Protection:
    """*repo*'s :class:`Protection` from its ``pyproject.toml`` at *ref*, read through *api*.

    Raises:
        ForgeRefused: *repo* is not declared (refused before *api* is asked), its declaration cannot be read at
            *ref*, or it does not render for this host.

    """
    if repo not in declared_repos(role):
        msg = f'{repo} is not declared in [ops.forge.accounts]; declared: {sorted(declared_repos(role))}'
        raise ForgeRefused(msg)
    owner, _, name = repo.partition('/')
    remote = Remote(public_host(role), owner, name)
    try:
        text = manifest_at(api, ref)
        wanted = forgeprotect.targets(text, f'{repo}@{ref}:pyproject.toml', remote)
    except (DeclarationUnread, ForgeRefused) as unread:
        msg = f'{repo}: pyproject.toml at {ref} cannot be read: {unread}'
        raise ForgeRefused(msg) from unread
    except ValueError as refused:
        raise ForgeRefused(str(refused)) from refused
    return Protection(repo, ref, remote, wanted)


def plan(api: forgeprotect.Api, found: Protection) -> list[Step]:
    """Every difference between the forge and *found*: the client's plan, read-only."""
    return forgeprotect.plan(api, found.remote, found.wanted)


def apply(
    api: forgeprotect.Api, found: Protection, *, redeem: Redeem, credential: Mapping[str, Any], log: str, by: str
) -> list[Step]:
    """Write *found* once the credential consents to exactly it; what the forge still lacks after (empty: all taken).

    Nothing differs: nothing is written and the credential is not spent.

    Raises:
        ConsentRefused: the credential does not consent to exactly this repo, ref and protection.

    """
    steps = plan(api, found)
    if not steps:
        return []
    redeem(credential, found.subject())
    left = forgeprotect.apply(api, found.remote, found.wanted)
    audit(log, by, {'action': ACTION, 'repo': found.repo, 'ref': found.ref, 'protection': found.digest(),
                    'wrote': len(steps), 'left': len(left)})  # fmt: skip
    return left


def add_parser(kinds: argparse._SubParsersAction) -> None:
    """``forge protect plan|apply`` on the ``ops forge`` parser."""
    protect = kinds.add_parser('protect', help="write a declared repo's branch protection as the site admin")
    protect.add_argument('action', choices=('plan', 'apply'))
    protect.add_argument('--repo', required=True, help='owner/name, as [ops.forge.accounts] names it')
    protect.add_argument('--ref', default=DEFAULT_REF, help='the ref whose pyproject.toml declaration is applied')
    protect.add_argument('--credential', default='', help='apply: a single-use ops.forge.protect consent credential')
    protect.add_argument('--subject', action='store_true', help='apply: print the digest the consent must name')


def run(
    role: Forge,
    args: argparse.Namespace,
    redeem_for: Callable[[], Callable[[str], Redeem]],
    *,
    api_for: Callable[[str], forgeprotect.Api] | None = None,
) -> int:
    """Run the parsed ``forge protect`` verb; exit 0 as declared, 1 a difference left, 2 refused.

    *redeem_for* is called only when ``apply`` spends a credential; *api_for* builds the repo's API (default: the
    local API as the site admin, its token deleted after).
    """
    if api_for is not None:
        return _run(role, args, redeem_for, api_for(args.repo))
    gitea = GiteaCli(role, run=run_argv, http=local_api)
    try:
        return _run(role, args, redeem_for, LocalRepo(args.repo, gitea.api))
    finally:
        gitea.close()


def _run(
    role: Forge, args: argparse.Namespace, redeem_for: Callable[[], Callable[[str], Redeem]], api: forgeprotect.Api
) -> int:
    try:
        found = rendered(role, api, args.repo, args.ref)
        if args.action == 'apply' and args.subject:
            emit(found.subject())
            return 0
        if args.action == 'plan':
            return _said(found, plan(api, found), left=False)
        if not args.credential:
            emit(f'refused: {ACTION} needs --credential (its subject: {found.subject()})', err=True)
            return 2
        granted = json.loads(Path(args.credential).read_text(encoding='utf-8'))
        by = os.environ.get('SUDO_USER', '') or 'root'
        left = apply(api, found, redeem=redeem_for()(ACTION), credential=granted, log=role.log, by=by)
    except (ForgeRefused, ConsentRefused, ForgeCallFailed, OSError, ValueError) as refused:
        emit(f'refused: {refused}', err=True)
        return 2
    return _said(found, left, left=True)


def _said(found: Protection, steps: Sequence[Step], *, left: bool) -> int:
    where = f'{found.remote.identity}@{found.ref}'
    emit(f'[ops forge protect] {where}: ' + (f'{len(steps)} difference(s)' if steps else 'as declared'))
    for line in forgeprotect.render(steps):
        emit(f'  {line}')
    if not left:
        emit(f'[ops forge protect] apply consent subject: {found.subject()}')
    return 1 if steps and left else 0
