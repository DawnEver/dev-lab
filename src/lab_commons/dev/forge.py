"""FORGE-BRANCH-PROTECTION: what the git host enforces on a branch, measured against a DECLARATION.

WHY A MECHANISM AND NOT A PAGE. The rule every repo in this family believes it has -- ``main`` takes
no direct push from an unnamed account, and no force-push ever -- lived as clicks in a web UI and a
paragraph describing them. Prose cannot fire: MEASURED 2026-08-27 on one forge, the rule everyone
believed was applied was NOT, and nobody could have noticed by reading the page. A second machine
joining the same forge needs the same settings, and a checklist re-typed by hand is how two machines
end up differently protected.

WHAT IS FAMILY AND WHAT IS ONE REPO'S ANSWER, and the split is the whole point of this module. The
API shape, the credential route, the clause vocabulary and -- the part that was paid for -- the
distinction between a rule that is UNAPPLIED and one that is INERT are true of every repo on a
Gitea-shaped forge. WHICH BRANCH, WHICH ACCOUNTS, whether force-push is permitted and which status
contexts are required are facts about ONE repository, so they arrive together in :class:`Protection`
and **every field of it is required**. A default here would judge every other repo against one
repo's trunk name and one repo's account list, and report the result as if it had been asked.

THE DECLARATION IS A TARGET, AND DRIFT IN EITHER DIRECTION IS DRIFT. :func:`assess` compares the live
rule to the declaration rather than to a floor, so a forge that is STRICTER than the declaration is
reported too. A repo that wants the stricter setting says so in its declaration; a difference nobody
declared is a difference nobody decided.

AN EMPTY ACCOUNT LIST IS REFUSED AT DECLARATION, and :meth:`Protection.__post_init__` says why: the
empty set is a subset of every whitelist, so a target naming nobody is met by every rule on every
forge -- the vacuous green in its arithmetic form.

AN ABSENT KEY IS NOT A FALSE AND AN INERT LIST IS NOT AN UNAPPLIED ONE. :data:`UNREADABLE` and
:data:`INERT` are their own standings because their REMEDIES differ, and each constant carries its
own measurement; a report that collapses either into ``NOT_APPLIED`` sends a reader to the wrong one.

A STATUS CONTEXT IS REPORTED AND, WHEN DECLARED EMPTY, NEVER WRITTEN -- ``status_contexts=()`` is a
declared absence :func:`protection_body` honours, because a branch protected against a status nobody
publishes is indistinguishable from a broken gate.

THE TRANSPORT IS HTTPS BY CONSTRUCTION. :func:`https_transport` speaks exactly one protocol, so no
URL here can be redirected onto another scheme and no comment has to assert that a URL is fine -- an
assertion no checker can verify is the declaration that lies.
"""

from __future__ import annotations

import http.client
import json
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping
    from pathlib import Path

__all__ = [
    'APPLIED',
    'INERT',
    'NOT_APPLIED',
    'UNREADABLE',
    'Clause',
    'Forge',
    'NoCredential',
    'Protection',
    'Transport',
    'UnreadableRemote',
    'apply_protection',
    'assess',
    'forge_from_remote',
    'https_transport',
    'protection_body',
    'read_rule',
]

#: The clause matches the declaration.
APPLIED = 'applied'

#: The clause does not match the declaration, and the forge answered the question.
NOT_APPLIED = 'not applied'

#: The clause's DATA is right and the switch that enforces it is off. Its own standing because its
#: remedy is one flag, where ``NOT_APPLIED`` may need the whole rule rewritten -- and because the
#: state reads as success to anyone checking the data and not the switch, which is the 2026-08-27
#: miss exactly.
INERT = 'inert'

#: The forge did not answer this question. NEVER folded into ``NOT_APPLIED``: a missing key is a fact
#: about the forge's API, and re-applying a rule is the wrong remedy for it.
UNREADABLE = 'unreadable'

#: Resolved once: a bare name is a PATH lookup at every call site, and a PATH that answers differently
#: between a terminal and a detached launcher describes an environment nobody meant.
_GIT = shutil.which('git') or 'git'

#: Reading a remote URL touches no network; a git that has not answered in half a minute is hung.
_GIT_TIMEOUT_S = 30

#: The lowest HTTP status that is an error. Named so the comparison is not a magic number, and so a
#: reader can see that a 3xx is NOT treated as one -- a redirect the client did not follow returns a
#: body that parses as nothing, which is the shape that reads as "no rules".
_HTTP_ERROR_FLOOR = 400

#: ``git@host:owner/repo.git`` -- an scp-style remote, which is NOT a URL. A URL parser reads it as a
#: path with no host, so a repository cloned over ssh would be reported on under an empty hostname.
_SCP_REMOTE = re.compile(r'^(?:(?P<user>[^@/]+)@)?(?P<host>[^:/]+):(?P<path>.+)$')


class UnreadableRemote(OSError):
    """``origin`` is absent, or names no owner and repository. Not an empty answer: there is no forge."""


class NoCredential(OSError):
    """The git transport holds no credential for this host, so there is nothing to authenticate with."""


#: How a request reaches the forge: ``(host, timeout) -> connection``. The shipped default speaks
#: HTTPS and nothing else; a caller substituting one has made that choice in CODE, which is what a
#: comment asserting that a URL is fine never was.
type Transport = Callable[[str, float], http.client.HTTPConnection]


def https_transport(host: str, timeout: float) -> http.client.HTTPSConnection:
    """The shipped transport: one protocol, structurally."""
    return http.client.HTTPSConnection(host, timeout=timeout)


@dataclass(frozen=True)
class Forge:
    """Where a repository lives, DERIVED from its remote rather than written down twice."""

    host: str
    owner: str
    repo: str

    @property
    def api(self) -> str:
        """The API root this forge family publishes."""
        return '/api/v1'

    @property
    def protections(self) -> str:
        """The collection of branch protection rules for this repository."""
        return f'{self.api}/repos/{self.owner}/{self.repo}/branch_protections'


@dataclass(frozen=True)
class Protection:
    """ONE REPOSITORY'S TARGET STATE for one branch. Every field is required; see the module docstring.

    Attributes:
        branch: the branch the rule is about -- a repo's trunk name, never guessed.
        push_accounts: who may push it directly. At least one, and the floor is why.
        allow_force_push: whether the forge should permit rewriting it.
        status_contexts: required checks. ``()`` is a DECLARED absence and writes nothing.

    """

    branch: str
    push_accounts: tuple[str, ...]
    allow_force_push: bool
    status_contexts: tuple[str, ...] = field()

    def __post_init__(self) -> None:
        """Refuse a declaration that cannot mean anything, at the moment it is written."""
        if not self.branch.strip():
            msg = 'a protection names the branch it is about; the empty string is a branch no forge holds'
            raise ValueError(msg)
        if not self.push_accounts:
            msg = (
                'a push whitelist must name at least one account: the empty set is a subset of every '
                'whitelist, so a target naming nobody is met by every rule on every forge'
            )
            raise ValueError(msg)


@dataclass(frozen=True)
class Clause:
    """One question asked of the live rule, its standing, and what a reader needs to act."""

    name: str
    standing: str
    detail: str


def forge_from_remote(root: Path, *, remote: str = 'origin') -> Forge:
    """Host, owner and repository, read from *root*'s remote; both URL and scp spellings.

    *remote* carries a default because ``origin`` is git's own convention rather than a repo's answer.
    """
    done = subprocess.run(
        [_GIT, 'remote', 'get-url', remote],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=_GIT_TIMEOUT_S,
        check=False,
    )
    if done.returncode != 0 or not done.stdout.strip():
        msg = f'no `{remote}` remote in {root}: there is no forge to report on'
        raise UnreadableRemote(msg)
    return _parse_remote(done.stdout.strip(), remote=remote)


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


def token_for(host: str, *, cwd: Path, env: Mapping[str, str] | None = None) -> str:
    """The credential the git transport already holds for *host*; never returned to a log.

    An EMPTY password is refused rather than returned: a header would carry it, the forge would
    reject it, and a missing credential would be reported as a forge problem.
    """
    done = subprocess.run(
        [_GIT, 'credential', 'fill'],
        input=f'protocol=https\nhost={host}\n\n',
        cwd=cwd,
        env=None if env is None else {**dict(env), 'PATH': ''},
        capture_output=True,
        text=True,
        timeout=_GIT_TIMEOUT_S,
        check=False,
    )
    for line in done.stdout.splitlines():
        key, _, value = line.partition('=')
        if key == 'password' and value:
            return value
    msg = f'no stored credential for {host}: the git transport must be able to authenticate first'
    raise NoCredential(msg)


def _read(rule: Mapping[str, Any], key: str) -> object:
    """The forge's answer, or :data:`UNREADABLE` when it did not give one."""
    return rule.get(key, UNREADABLE)


def _clause(name: str, *, live: object, wanted: object, detail: str) -> Clause:
    """One comparison, with the unreadable case kept out of the equality."""
    if live is UNREADABLE:
        return Clause(name, UNREADABLE, f'the forge did not answer {detail}')
    standing = APPLIED if live == wanted else NOT_APPLIED
    return Clause(name, standing, f'{detail}: live={live!r} declared={wanted!r}')


def assess(rule: Mapping[str, Any] | None, target: Protection) -> tuple[Clause, ...]:
    """Every clause of *target*, against the live *rule*; ``None`` means no rule exists at all."""
    if rule is None:
        detail = f'no protection rule for `{target.branch}` exists: any account may push anything'
        return tuple(Clause(name, NOT_APPLIED, detail) for name in ('push_whitelist', 'force_push', 'status_checks'))
    return (
        _push_clause(rule, target),
        _clause(
            'force_push',
            live=_read(rule, 'enable_force_push'),
            wanted=target.allow_force_push,
            detail='whether the branch may be rewritten',
        ),
        _status_clause(rule, target),
    )


def _push_clause(rule: Mapping[str, Any], target: Protection) -> Clause:
    """Who may push, and whether the switch that enforces the list is on."""
    enabled, switch = _read(rule, 'enable_push'), _read(rule, 'enable_push_whitelist')
    listed = _read(rule, 'push_whitelist_usernames')
    if UNREADABLE in (enabled, switch, listed):
        return Clause('push_whitelist', UNREADABLE, 'the forge did not answer the push whitelist clause')
    named = set(target.push_accounts) <= set(listed or ())
    if named and not switch:
        return Clause(
            'push_whitelist',
            INERT,
            'the whitelist names the declared accounts and enable_push_whitelist is off, so it is '
            'decorative: anyone with write access may push',
        )
    if enabled and switch and named:
        return Clause('push_whitelist', APPLIED, f'push restricted to {sorted(target.push_accounts)}')
    return Clause(
        'push_whitelist',
        NOT_APPLIED,
        f'declared {sorted(target.push_accounts)}, live enable_push={enabled!r} '
        f'enable_push_whitelist={switch!r} whitelist={sorted(listed or ())}',
    )


def _status_clause(rule: Mapping[str, Any], target: Protection) -> Clause:
    """Required status checks, against a declaration whose empty value is a measured absence."""
    enabled, contexts = _read(rule, 'enable_status_check'), _read(rule, 'status_check_contexts')
    if UNREADABLE in (enabled, contexts):
        return Clause('status_checks', UNREADABLE, 'the forge did not answer the status check clause')
    live = tuple(sorted(contexts or ())) if enabled else ()
    wanted = tuple(sorted(target.status_contexts))
    standing = APPLIED if live == wanted else NOT_APPLIED
    return Clause('status_checks', standing, f'required contexts: live={list(live)} declared={list(wanted)}')


def protection_body(target: Protection, *, with_branch: bool = False) -> dict[str, Any]:
    """The payload that makes *target* true. Pure, so a caller can read it before sending it.

    ``with_branch`` is for the CREATE call only: a PATCH addresses the branch in its path, and
    repeating it in the body is a second place to be wrong.
    """
    body: dict[str, Any] = {
        'enable_push': True,
        'enable_push_whitelist': True,
        'push_whitelist_usernames': list(target.push_accounts),
        'enable_force_push': target.allow_force_push,
    }
    if target.status_contexts:
        body |= {'enable_status_check': True, 'status_check_contexts': list(target.status_contexts)}
    return {'branch_name': target.branch, **body} if with_branch else body


def call(
    forge: Forge,
    path: str,
    token: str,
    *,
    method: str = 'GET',
    body: Mapping[str, Any] | None = None,
    transport: Transport = https_transport,
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
            headers={'Authorization': f'token {token}', 'Content-Type': 'application/json'},
        )
        response = conn.getresponse()
        payload = response.read()
        if response.status >= _HTTP_ERROR_FLOOR:
            msg = f'{method} {path} on {forge.host} -> HTTP {response.status}: {payload.decode(errors="replace")[:300]}'
            raise OSError(msg)
        return json.loads(payload) if payload else None
    finally:
        conn.close()


def read_rule(forge: Forge, token: str, target: Protection, *, transport: Transport = https_transport) -> dict | None:
    """The live rule for *target*'s branch, MATCHED rather than taken as the first rule.

    A repo with several protected branches would otherwise be reported on under the wrong one.
    """
    payload = call(forge, forge.protections, token, transport=transport)
    rules: list[dict[str, Any]] = payload if isinstance(payload, list) else []
    return next((rule for rule in rules if rule.get('branch_name') == target.branch), None)


def apply_protection(
    forge: Forge, token: str, target: Protection, *, transport: Transport = https_transport
) -> tuple[Clause, ...]:
    """Make *target* true, and return the assessment of the state AFTER.

    A write the forge silently declined otherwise reports as applied, because the call returned 200.
    """
    existing = read_rule(forge, token, target, transport=transport)
    if existing is None:
        call(
            forge,
            forge.protections,
            token,
            method='POST',
            body=protection_body(target, with_branch=True),
            transport=transport,
        )
    else:
        call(
            forge,
            f'{forge.protections}/{target.branch}',
            token,
            method='PATCH',
            body=protection_body(target),
            transport=transport,
        )
    return assess(read_rule(forge, token, target, transport=transport), target)
