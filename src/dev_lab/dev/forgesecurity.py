"""SECURITY IS A PER-HEAD FORGE STATUS: ``tests/security``, posted once per head by a serve step, a merge condition.

User ruling 2026-10-26: the security check is a property of a HEAD, judged once on the serving host -- not a
test that every part's shards re-run on compute nodes. :func:`step` runs on the elected poller each tick
(:func:`dev_lab.dev.forgeserve._repo_wide`) over every open, non-draft PR into integration and over the
integration head itself (on GitHub a workflow job judges its event's PR, ``forge security run --pr <N>``, through
the same :func:`judge_one`); a head already carrying a settled :data:`SECURITY_CONTEXT` status is not judged
again. The head's TRACKED tree is exported (``git archive``) and judged by :mod:`dev_lab.dev.security`'s
three scans: ruff ``S``, the tracked-credential scan, and ``uv.lock`` against OSV.

THE STATUS SAYS WHAT WAS ANSWERED, never more:

* ``success`` -- every scan answered and found nothing beyond the declared differences;
* ``failure`` -- the findings, named by ``file:line`` (a credential by its digest, never its value) or
  ``package==version: advisory``, the first few in the description and the count always;
* ``error`` -- a scan gave no answer (OSV unreachable, ruff or git erring, the declaration malformed). Never
  ``success`` without an answer; an ``error`` is judged again on a later tick.

:func:`dev_lab.dev.forgemerge.decide` waits until the head's latest ``tests/security`` is ``success``.

THE DIFFERENCES ARE DECLARED DATA, ONE PLACE. The family default lives in :mod:`dev_lab.dev.security`
(:data:`~dev_lab.dev.security.FAMILY_IGNORE`, :data:`~dev_lab.dev.security.FAMILY_EXCLUDE`); a repo declares
only what differs, every entry with its reason::

    [tool.dev_lab.security]
    exclude = { attic = "read-only migrated archive, never imported" }   # trees kept out of ruff S
    ignore = { S311 = "plot colours and seeded study samples" }           # ruff S rules waived
    allowed = { "sha256:1175475b7402" = "a fake test credential" }       # credential digests allowed
    accepted = { "GHSA-xxxx-xxxx-xxxx" = "the vulnerable path is unused" }  # advisories accepted

The table that JUDGES a head is read from ``origin/<integration>``, never from the head: a branch cannot widen
the exemptions that judge it. A PR that CHANGES the table is released once, explicitly, and on the record:

* the step judges such a head twice -- with the integration table (the posted findings) and with the head's own.
  When the head's table leaves nothing, the ``failure`` says so and names the door, :data:`RELEASE_DOOR`;
* ``python -m dev_lab.dev.forge security release <pr> --why "<reason>"`` (:func:`release`)
  re-judges the head with ITS table and, only when that finds nothing, records the reason and the exemption
  delta as ONE keyed PR comment (``Marker.SECURITY_RELEASE``) and posts ``success`` citing it. Refused without a
  reason, when the head leaves the table unchanged, and when the head's own table still leaves findings. A raw
  ``status post`` on this context is refused to agents (``STATUS-VIA-DOORS``). Nothing checks WHO runs the
  door: what makes a release safe is that it is RECORDED -- the comment names the host, the delta and the reason --
  so it is auditable, and that the reason must be substantive (:data:`_MIN_WHY` characters at least).

It is ``tool.dev_lab`` and not
``tool.lab_commons`` because it is read by this step alone, never by a reader of the commit's kit tables.
"""

from __future__ import annotations

import argparse
import io
import subprocess
import sys
import tarfile
import tempfile
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Final

import lab_commons.launch as _door
from lab_commons.log import emit

from dev_lab.dev.forgeclaim import this_machine
from dev_lab.dev.forgecontexts import SECURITY_CONTEXT
from dev_lab.dev.forgepulls import ListingIncomplete, Marker, comment_upsert, pr_list
from dev_lab.dev.forgestatus import DESCRIPTION_LIMIT, status_list, status_post
from dev_lab.dev.forgework import ForgeCallFailed, client_for
from dev_lab.dev.lanepolicy import load_policy
from dev_lab.dev.netverb import run_network_verb
from dev_lab.dev.security import (
    AdvisoriesUnreachable,
    ScanFailed,
    advisories,
    code_findings,
    locked_packages,
    secret_findings,
    vulnerable,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from dev_lab.dev.forgestatus import CommitStatus
    from dev_lab.dev.forgework import Client

__all__ = [
    'KEYS',
    'RELEASE_DOOR',
    'Declaration',
    'Judgement',
    'ReleaseRefused',
    'declared',
    'delta',
    'judge',
    'judge_one',
    'main',
    'release',
    'run_pull',
    'security_wait',
    'step',
]

#: The keys ``[tool.dev_lab.security]`` may declare; any other key is refused by name.
KEYS: Final = ('exclude', 'ignore', 'allowed', 'accepted')

#: How many findings a status description names before the count.
_NAMED: Final = 3

#: A settled security status: judged, not judged again on that head.
_SETTLED: Final = frozenset({'success', 'failure'})

#: The door run on a head whose own new exemptions cover its findings; ``{pr}`` is its number.
RELEASE_DOOR: Final = 'python -m dev_lab.dev.forge security release {pr} --why "<reason>"'

_MIN_WHY: Final = 10  # characters: a reason, not a shrug


class DeclarationInvalid(ValueError):
    """``[tool.dev_lab.security]`` is malformed; the message names the key."""


class ReleaseRefused(ValueError):
    """The release door will not release this head, and says why."""


@dataclass(frozen=True)
class Declaration:
    """A repo's differences from the family default, each ``{name: reason}``."""

    exclude: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))
    ignore: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))
    allowed: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))
    accepted: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))

    def tables(self) -> dict[str, Mapping[str, str]]:
        """Each declared table by its key (:data:`KEYS`)."""
        return {'exclude': self.exclude, 'ignore': self.ignore, 'allowed': self.allowed, 'accepted': self.accepted}


@dataclass(frozen=True)
class Judgement:
    """The status one head earns: its state and description."""

    state: str
    description: str


def declared(pyproject: str) -> Declaration:
    """The ``[tool.dev_lab.security]`` differences in pyproject text; absent is none.

    Raises:
        DeclarationInvalid: an unknown key, or a value that is not a table of non-empty reasons.

    """
    table = tomllib.loads(pyproject).get('tool', {}).get('dev_lab', {}).get('security', {})
    if unknown := sorted(set(table) - set(KEYS)):
        msg = f'[tool.dev_lab.security] declares {unknown}; the keys are {list(KEYS)}'
        raise DeclarationInvalid(msg)
    for key, value in table.items():
        if not isinstance(value, dict) or not all(isinstance(r, str) and r.strip() for r in value.values()):
            msg = f'[tool.dev_lab.security] {key} must be a table of {{name = "reason"}}, every reason non-empty'
            raise DeclarationInvalid(msg)
    return Declaration(**{key: MappingProxyType(dict(value)) for key, value in table.items()})


def delta(old: Declaration, new: Declaration) -> tuple[str, ...]:
    """Each entry *new* adds (``+key.name``), changes (``~``) or drops (``-``) against *old*; empty is unchanged."""
    out: list[str] = []
    for key in KEYS:
        was, now = old.tables()[key], new.tables()[key]
        out += [f'+{key}.{name}' for name in sorted(set(now) - set(was))]
        out += [f'~{key}.{name}' for name in sorted(set(now) & set(was)) if now[name] != was[name]]
        out += [f'-{key}.{name}' for name in sorted(set(was) - set(now))]
    return tuple(out)


def _site(finding: str) -> str:
    """``path:line Sxxx`` of a ruff ``path:line:col: Sxxx message`` line: the description has room for sites only."""
    where, _, rest = finding.partition(': ')
    return f'{where.rsplit(":", 1)[0]} {rest.split(" ", 1)[0]}'


def _named(kind: str, found: Sequence[str]) -> str:
    shown = '; '.join(found[:_NAMED]) + ('; ...' if len(found) > _NAMED else '')
    return f'{len(found)} {kind}: {shown}'


def judge(
    tree: Path,
    tracked: Sequence[str],
    declaration: Declaration,
    *,
    lookup: Callable[[Mapping[str, str]], Mapping[str, tuple[str, ...]]] = advisories,
) -> Judgement:
    """The status the tree at *tree* (its tracked paths *tracked*) earns under *declaration*."""
    try:
        found = code_findings(tree, exclude=declaration.exclude, ignore=declaration.ignore, tracked=tracked)
        code = [_site(line) for line in found]
        secrets = secret_findings(tree, allowed=declaration.allowed, tracked=tracked)
        lock = tree / 'uv.lock'
        pinned = locked_packages(lock) if 'uv.lock' in tracked else {}
        advisories_found = vulnerable(lookup(pinned), accepted=declaration.accepted) if pinned else []
    except (ScanFailed, AdvisoriesUnreachable, OSError, tomllib.TOMLDecodeError) as unanswered:
        return Judgement('error', f'no answer, judged again next tick: {unanswered}'[:DESCRIPTION_LIMIT])
    parts = [
        _named(kind, found)
        for kind, found in (('ruff S', code), ('credential(s)', secrets), ('advisory(ies)', advisories_found))
        if found
    ]
    if not parts:
        return Judgement('success', f'ruff S, credentials and {len(pinned)} locked pin(s): nothing found')
    return Judgement('failure', ' | '.join(parts)[:DESCRIPTION_LIMIT])


def security_wait(statuses: Sequence[CommitStatus]) -> str | None:
    """Why a merge of the commit waits on its security check, or ``None``: its latest status is ``success``."""
    latest = next((one for one in statuses if one.context == SECURITY_CONTEXT), None)
    if latest is not None and latest.state == 'success':
        return None
    standing = 'not yet judged' if latest is None else f'{latest.state}: {latest.description}'
    return f'{SECURITY_CONTEXT} is {standing}'


def _git(root: Path, *argv: str) -> bytes:
    return _door.run(['git', *argv], cwd=root, capture_output=True, check=True).stdout


def _judge_head(root: Path, head: str, declaration: Declaration) -> Judgement:
    """Export *head*'s tracked tree and judge it; a head git cannot read is an ``error``."""
    try:
        if _door.run(['git', 'cat-file', '-e', f'{head}^{{commit}}'], cwd=root, check=False).returncode:
            run_network_verb(['git', 'fetch', 'origin', head], cwd=root)
        tracked = [name for name in _git(root, 'ls-tree', '-r', '-z', '--name-only', head).decode().split('\0') if name]
        archive = _git(root, 'archive', '--format=tar', head)
    except (OSError, subprocess.CalledProcessError) as unread:
        return Judgement('error', f'no answer, judged again next tick: git could not read {head[:12]}: {unread}')
    with tempfile.TemporaryDirectory(prefix='security-') as scratch, tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        tar.extractall(scratch, filter='data')
        return judge(Path(scratch), tracked, declaration)


def _declared_at(root: Path, rev: str) -> Declaration:
    """The declaration in *rev*'s ``pyproject.toml`` (fetched when absent here); no pyproject declares none."""
    try:
        text = _git(root, 'show', f'{rev}:pyproject.toml')
    except subprocess.CalledProcessError:
        run_network_verb(['git', 'fetch', 'origin', rev], cwd=root)
        try:
            text = _git(root, 'show', f'{rev}:pyproject.toml')
        except subprocess.CalledProcessError:
            return Declaration()
    return declared(text.decode('utf-8'))


def _covered(
    root: Path, number: int, head: str, base: Declaration, found: Judgement, *,
    judged: Callable[[Path, str, Declaration], Judgement],
) -> Judgement:  # fmt: skip
    """*found*, saying so and naming the door when the head's OWN changed table leaves no finding.

    Best effort: a head whose own table cannot be read or judged keeps *found* -- an invalid table named in it --
    and never stops the step from judging the heads after it.
    """
    try:
        own = _declared_at(root, head)
        if not delta(base, own) or judged(root, head, own).state != 'success':
            return found
    except DeclarationInvalid as invalid:
        said = f"{found.description} | the head's own table is DeclarationInvalid: {invalid}"
        return Judgement('failure', said[:DESCRIPTION_LIMIT])
    except (ValueError, OSError, subprocess.CalledProcessError):
        return found
    said = f"all covered by the head's new exemptions: {RELEASE_DOOR.format(pr=number)} | {found.description}"
    return Judgement('failure', said[:DESCRIPTION_LIMIT])


def step(
    root: Path,
    client: Client,
    *,
    say: Callable[[str], None],
    judged: Callable[[Path, str, Declaration], Judgement] = _judge_head,
) -> None:
    """Post ``tests/security`` on every unjudged open PR head into integration and on the integration head.

    A failure to read the forge or the declaration is said, never raised: the next tick tries afresh.
    """
    try:
        into = load_policy(root).pr_base
        base = f'origin/{into}'
        declaration = declared(_git(root, 'show', f'{base}:pyproject.toml').decode('utf-8'))
        heads: list[tuple[int | None, str]] = [
            (pull.number, pull.head_sha)
            for pull in pr_list(client)
            if pull.base == into and not pull.draft and pull.head_sha
        ]
        heads.append((None, _git(root, 'rev-parse', base).decode().strip()))
        for number, head in heads:
            if (line := judge_one(root, client, number, head, declaration, judged=judged)) is not None:
                say(f'[serve] security: {into if number is None else ""}{line}')
    except (ForgeCallFailed, ListingIncomplete, OSError, ValueError, subprocess.CalledProcessError) as failed:
        say(f'[serve] security: not judged this tick: {failed}')


def judge_one(
    root: Path, client: Client, number: int | None, head: str, declaration: Declaration, *,
    judged: Callable[[Path, str, Declaration], Judgement] = _judge_head,
) -> str | None:  # fmt: skip
    """Post ``tests/security`` on *head* (PR *number*'s, or the base's for ``None``) unless settled; the line, if any.

    The one judgement both triggers share: the serve tick's :func:`step` over every head, and a GitHub workflow
    job's ``forge security run --pr <N>`` over its event's PR (:func:`run_pull`).
    """
    if any(one.context == SECURITY_CONTEXT and one.state in _SETTLED for one in status_list(client, head)):
        return None
    found = judged(root, head, declaration)
    if number is not None and found.state == 'failure':
        found = _covered(root, number, head, declaration, found, judged=judged)
    status_post(client, head, context=SECURITY_CONTEXT, state=found.state, description=found.description)
    return f'{"" if number is None else f"#{number}"} {head[:12]} {found.state}: {found.description}'


def run_pull(
    root: Path, client: Client, number: int, *, judged: Callable[[Path, str, Declaration], Judgement] = _judge_head
) -> str:
    """:func:`judge_one` on PR *number*'s head, under the table ``origin/<PR base>`` declares; the line said."""
    into = load_policy(root).pr_base
    pull = client.pr_view(number)
    if pull.base != into or not pull.head_sha:
        return f'#{number}: not judged -- only a PR into {into} is'
    declaration = declared(_git(root, 'show', f'origin/{into}:pyproject.toml').decode('utf-8'))
    said = judge_one(root, client, number, pull.head_sha, declaration, judged=judged)
    return said or f'#{number} {pull.head_sha[:12]}: already judged'


def release(
    root: Path, client: Client, number: int, why: str, *, host: str,
    judged: Callable[[Path, str, Declaration], Judgement] | None = None,
) -> str:  # fmt: skip
    """Release PR *number*'s head, judged clean under its OWN changed table, with *why*; the line said.

    Raises:
        ReleaseRefused: no reason, no such open PR, an unchanged table, or findings the head's own table leaves.

    """
    if len(why.strip()) < _MIN_WHY:
        msg = f'a release needs its reason: --why "<at least {_MIN_WHY} characters>"'
        raise ReleaseRefused(msg)
    integration = load_policy(root).pr_base
    pull = next((one for one in pr_list(client) if one.number == number and one.base == integration), None)
    if pull is None or not pull.head_sha:
        msg = f'#{number} is not an open PR into {integration}'
        raise ReleaseRefused(msg)
    head, own = pull.head_sha, _declared_at(root, pull.head_sha)
    if not (changed := delta(_declared_at(root, f'origin/{integration}'), own)):
        msg = f'#{number} {head[:12]} does not change [tool.dev_lab.security]: there is nothing to release; fix it'
        raise ReleaseRefused(msg)
    found = (judged or _judge_head)(root, head, own)
    if found.state != 'success':
        msg = f'#{number} {head[:12]} under its own table is {found.state}: {found.description}'
        raise ReleaseRefused(msg)
    text = (
        f'{SECURITY_CONTEXT} released for {head} by {host}: {why.strip()}\n\n'
        f'exemption delta against {integration}: {", ".join(changed)}'
    )
    _, comment = comment_upsert(client, number, kind=Marker.SECURITY_RELEASE, key=head, text=text)
    said = f'released by {host} under its own new exemptions ({", ".join(changed)}): {why.strip()}'
    status_post(client, head, context=SECURITY_CONTEXT, state='success', description=said[:DESCRIPTION_LIMIT],
                target_url=comment.url if comment else '')  # fmt: skip
    return f'#{number} {head[:12]}: {SECURITY_CONTEXT} success'


def main(argv: Sequence[str] | None = None, *, cwd: Path | None = None, client: Client | None = None) -> int:
    """``forge security release <pr> --why "<reason>"``, ``forge security run --pr <N>``. Exit 0 done, 2 refused."""
    parser = argparse.ArgumentParser(prog='dev_lab.dev.forge security', description=__doc__.splitlines()[0])
    verbs = parser.add_subparsers(dest='verb', required=True)
    door = verbs.add_parser(
        'release', help='release a head clean under its own new exemptions; records host, delta, reason'
    )
    door.add_argument('pr', type=int)
    door.add_argument('--why', required=True, help='why the new exemptions are right: refused when short')
    running = verbs.add_parser('run', help="judge one PR's head: what a GitHub workflow job runs for its event")
    running.add_argument('--pr', type=int, required=True)
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    root = Path.cwd() if cwd is None else cwd
    try:
        origin = client or client_for(root)
        if args.verb == 'run':
            said = run_pull(root, origin, args.pr)
        else:
            said = release(root, origin, args.pr, args.why, host=this_machine())
    except (ReleaseRefused, ForgeCallFailed, OSError, ValueError, subprocess.CalledProcessError) as failed:
        emit(f'[security] refused: {failed}', err=True)
        return 2
    emit(f'[security] {said}')
    return 0
