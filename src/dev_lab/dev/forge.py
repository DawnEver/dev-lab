"""The forge a checkout lives on: where it is (:class:`Forge`, from the remote), how a request reaches it, one API call.

Branch protection measured against a declaration is :mod:`dev_lab.dev.forgerule`; the forge's other verbs are its
``forge*`` siblings, dispatched by ``python -m dev_lab.dev.forge`` (:mod:`dev_lab.dev.forgecli`).

THE TRANSPORT IS HTTPS TO EVERY NON-LOOPBACK HOST. :func:`forge_transport` speaks HTTPS to every host but a loopback one
(a Gitea Actions job's own forge), chosen by the host alone, so no URL here can be redirected onto another scheme
and no comment has to assert that a URL is fine -- an assertion no checker can verify is the declaration that lies.
"""

from __future__ import annotations

import getpass
import http.client
import json
import os
import pathlib
import re
import socket
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final, Protocol

import lab_commons.launch as _door
from lab_commons.credentials import _GIT, _GIT_TIMEOUT_S, NoCredential, credential_for, store_credential

from dev_lab.dev.forgecred import (
    AUTH_GONE,
    AUTH_KEPT,
    AUTH_REFUSED,
    AUTH_REMEDY,
    AUTH_TRANSIENT,
    authorization,
    refresh_credential,
    token_for,
)
from dev_lab.dev.netverb import run_network_verb

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping
    from pathlib import Path

__all__ = [
    'AUTH_GONE',
    'AUTH_KEPT',
    'AUTH_REFUSED',
    'AUTH_REMEDY',
    'AUTH_TRANSIENT',
    'Connection',
    'Forge',
    'NoCredential',
    'Transport',
    'UnreadableRemote',
    'authorization',
    'call',
    'credential_for',
    'fetch_origin',
    'forge_from_remote',
    'forge_of_url',
    'forge_transport',
    'on_origin',
    'refresh_credential',
    'store_credential',
    'token_for',
    'user_agent',
]

#: The lowest HTTP status that is an error. Named so the comparison is not a magic number, and so a
#: reader can see that a 3xx is NOT treated as one -- a redirect the client did not follow returns a
#: body that parses as nothing, which is the shape that reads as "no rules".
_HTTP_ERROR_FLOOR = 400

#: ``git@host:owner/repo.git`` -- an scp-style remote, which is NOT a URL. A URL parser reads it as a
#: path with no host, so a repository cloned over ssh would be reported on under an empty hostname.
_SCP_REMOTE = re.compile(r'^(?:(?P<user>[^@/]+)@)?(?P<host>[^:/]+):(?P<path>.+)$')


class UnreadableRemote(OSError):
    """``origin`` is absent, or names no owner and repository. Not an empty answer: there is no forge."""


class Connection(Protocol):
    """What a forge call uses of a connection: a request, its answer, the close; an ``HTTPConnection`` is one."""

    def request(self, method: str, url: str, body: bytes | None = ..., headers: Mapping[str, str] = ...) -> None:
        """Send *method* *url* with *body* and *headers*."""

    def getresponse(self) -> http.client.HTTPResponse:
        """The answer to the request sent."""

    def close(self) -> None:
        """Close the connection."""


#: How a request reaches the forge: ``(host, timeout) -> connection``. The shipped default speaks
#: HTTPS and nothing else; a caller substituting one has made that choice in CODE, which is what a
#: comment asserting that a URL is fine never was.
type Transport = Callable[[str, float], Connection]


def user_agent(forge: Forge) -> str:
    """``dev-lab (<login>@<machine>; <owner>/<repo>)``: who sent a request, so the forge's log can attribute its load.

    Measured 2026-10-24: 9425 requests in ten minutes reached the forge from two login nodes with no
    User-Agent, so which of five accounts and seven repos sent them could not be read off the log. The
    machine is ``$HARNESS_MACHINE``, else the short hostname (as :func:`dev_lab.dev.forgeclaim.this_machine`).
    """
    try:
        login = getpass.getuser()
    except (OSError, KeyError):
        login = '?'
    machine = os.environ.get('HARNESS_MACHINE', '').strip() or socket.gethostname().split('.')[0]
    return f'dev-lab ({login}@{machine}; {forge.owner}/{forge.repo})'


#: Loopback host names: a request to one never leaves the machine, so they are the only hosts spoken plain HTTP.
_LOOPBACK_HOSTS: Final = frozenset({'127.0.0.1', 'localhost', '[::1]'})


def forge_transport(host: str, timeout: float) -> http.client.HTTPConnection:
    """The shipped transport: HTTPS, except plain HTTP to a LOOPBACK *host* (``127.0.0.1:9000``).

    A Gitea Actions job reaches its forge at the runner's registered instance, a loopback HTTP port: the public
    name is refused from inside the host's network. A loopback request never crosses a wire, so it carries the
    token no further than the forge process beside it; every other host is HTTPS, structurally.
    """
    if host.rpartition(':')[0] in _LOOPBACK_HOSTS or host in _LOOPBACK_HOSTS:
        return http.client.HTTPConnection(host, timeout=timeout)
    return http.client.HTTPSConnection(host, timeout=timeout)


@dataclass(frozen=True)
class Forge:
    """Where a repository lives, DERIVED from its remote rather than written down twice."""

    host: str
    owner: str
    repo: str

    @property
    def identity(self) -> str:
        """``<host>/<owner>/<repo>``: the repository's one name across every forge (a mirror's twin differs by host)."""
        return f'{self.host}/{self.owner}/{self.repo}'

    @property
    def api(self) -> str:
        """The API root this forge family publishes."""
        return '/api/v1'

    @property
    def protections(self) -> str:
        """The collection of branch protection rules for this repository."""
        return f'{self.api}/repos/{self.owner}/{self.repo}/branch_protections'


_REMOTES: dict[tuple[str, str, int, int], Forge] = {}


def _git_config(root: Path) -> Path | None:
    """The config *root*'s checkout reads its remotes from (a worktree's: its common dir's); ``None``: unknown."""
    for here in (root, *root.parents):
        dot = here / '.git'
        if dot.is_dir():
            return dot / 'config'
        if dot.is_file():
            gitdir = here / dot.read_text(encoding='utf-8').partition(':')[2].strip()
            common = gitdir / 'commondir'
            return (gitdir / common.read_text(encoding='utf-8').strip() if common.is_file() else gitdir) / 'config'
    return None


def forge_from_remote(root: Path, *, remote: str = 'origin') -> Forge:
    """Host, owner and repository, read from *root*'s remote; both URL and scp spellings.

    *remote* carries a default because ``origin`` is git's own convention rather than a repo's answer.
    Kept per version of the checkout's git config (one ``forge queue`` asked git 54 times): ``remote
    set-url`` rewrites that file, so it is read again; a checkout whose config cannot be found is never kept.
    """
    here = pathlib.Path(root).resolve()
    try:
        config = _git_config(here)
        stat = config.stat() if config is not None else None
    except OSError:
        stat = None
    key = None if stat is None else (str(here), remote, stat.st_mtime_ns, stat.st_size)
    if key is not None and key in _REMOTES:
        return _REMOTES[key]
    found = _read_remote(root, remote)
    if key is not None:
        _REMOTES[key] = found
    return found


def _read_remote(root: Path, remote: str) -> Forge:
    done = _door.run(
        [_GIT, 'remote', 'get-url', remote],
        cwd=root,
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
        timeout=_GIT_TIMEOUT_S,
        check=False,
    )
    if done.returncode != 0 or not done.stdout.strip():
        msg = f'no `{remote}` remote in {root}: there is no forge to report on'
        raise UnreadableRemote(msg)
    return _parse_remote(done.stdout.strip(), remote=remote)


def forge_of_url(url: str) -> Forge:
    """Host, owner and repository of a remote *url* with no checkout to read it from (a deploy before its clone)."""
    return _parse_remote(url, remote=url)


def _parse_remote(url: str, *, remote: str) -> Forge:
    """Split a remote into host/owner/repo, refusing a partial parse rather than travelling with one."""
    host, path = '', ''
    if '://' in url:
        scheme, _, rest = url.partition('://')
        authority, _, tail = rest.partition('/')
        if scheme in {'ssh', 'git', 'http', 'https'}:
            host, path = authority.rpartition('@')[2], tail
    else:
        found = _SCP_REMOTE.match(url)
        if found is not None:
            host, path = found.group('host'), found.group('path')
    owner, _, repo = path.strip('/').removesuffix('.git').partition('/')
    if not host or not owner or not repo or '/' in repo:
        msg = f'the `{remote}` remote {url!r} does not name a host, an owner and a repository'
        raise UnreadableRemote(msg)
    return Forge(host=host, owner=owner, repo=repo)


#: The remote-tracking namespace every "does the forge hold it" reading uses.
_ORIGIN_TRACKING = 'refs/remotes/origin'


def on_origin(root: Path, sha: str) -> bool:
    """Whether *sha* is reachable from an ``origin`` remote-tracking ref -- the forge holds it.

    Offline: a push updates the remote-tracking ref the moment it lands, and a fetch for anyone else's.
    """
    done = _door.run(
        [
            _GIT,
            '-C',
            str(root),
            'for-each-ref',
            '--count=1',
            '--contains',
            sha,
            '--format=%(refname)',
            _ORIGIN_TRACKING,
        ],
        capture_output=True,
        text=True,
        encoding='utf-8',
        check=False,
        timeout=_GIT_TIMEOUT_S,
    )
    return done.returncode == 0 and bool(done.stdout.strip())


def fetch_origin(root: Path, *, timeout: float = 300.0, deadline: float | None = None) -> None:
    """``git fetch --prune origin``, each attempt bounded by *timeout* s, retried then reported; raises on failure.

    *deadline* (a :func:`time.monotonic` instant) bounds every attempt and backoff together.
    """
    argv = [_GIT, 'fetch', '--prune', '--quiet', 'origin']
    report = run_network_verb(argv, cwd=root, timeout=timeout, deadline=deadline)
    if not report.ok:
        raise OSError(report.remedy)


def call(
    forge: Forge,
    path: str,
    token: str,
    *,
    method: str = 'GET',
    body: Mapping[str, Any] | None = None,
    transport: Transport = forge_transport,
    timeout: float = 30.0,
) -> object:
    """One API call; an error status RAISES.

    An error with an empty payload otherwise parses as "no rules" and reads as clean.
    """
    data = json.dumps(dict(body)).encode() if body is not None else None
    conn = transport(forge.host, timeout)
    try:
        conn.request(
            method,
            path,
            body=data,
            headers={
                'Authorization': f'token {token}',
                'Content-Type': 'application/json',
                'User-Agent': user_agent(forge),
            },
        )
        response = conn.getresponse()
        payload = response.read()
        if response.status >= _HTTP_ERROR_FLOOR:
            msg = f'{method} {path} on {forge.host} -> HTTP {response.status}: {payload.decode(errors="replace")[:300]}'
            raise OSError(msg)
        return json.loads(payload) if payload else None
    finally:
        conn.close()


if __name__ == '__main__':
    # The noun dispatch imports the ``forge*`` siblings, which import THIS module, so it is deferred
    # to the entry point: at the top it would be circular (NO-LAZY-IMPORT's written exception).
    import sys

    from dev_lab.dev import forgecli

    raise SystemExit(forgecli.main(sys.argv[1:]))
