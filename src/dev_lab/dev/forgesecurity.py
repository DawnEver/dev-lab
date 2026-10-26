"""SECURITY IS A PER-HEAD FORGE STATUS: ``tests/security``, posted once per head by a serve step, a merge condition.

User ruling 2026-10-26: the security check is a property of a HEAD, judged once on the serving host -- not a
test that every part's shards re-run on compute nodes. :func:`step` runs on the elected poller each tick
(:func:`dev_lab.dev.forgeserve._repo_wide`) over every open, non-draft PR into integration and over the
integration head itself; a head already carrying a settled :data:`SECURITY_CONTEXT` status is not judged
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

The table is read from ``origin/<integration>``, never from the head being judged: a branch cannot widen the
exemptions that judge it, so a new exemption lands on its own PR first. It is ``tool.dev_lab`` and not
``tool.lab_commons`` because it is read by this step alone, never by a reader of the commit's kit tables.
"""

from __future__ import annotations

import io
import subprocess
import tarfile
import tempfile
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Final

import lab_commons.launch as _door

from dev_lab.dev.forgepulls import ListingIncomplete, pr_list
from dev_lab.dev.forgestatus import DESCRIPTION_LIMIT, status_list, status_post
from dev_lab.dev.forgework import ForgeCallFailed
from dev_lab.dev.lanepolicy import load_policy
from dev_lab.dev.netverb import run_network_verb
from dev_lab.dev.platformparts import SECURITY_CONTEXT
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

__all__ = ['KEYS', 'Declaration', 'Judgement', 'declared', 'judge', 'security_wait', 'step']

#: The keys ``[tool.dev_lab.security]`` may declare; any other key is refused by name.
KEYS: Final = ('exclude', 'ignore', 'allowed', 'accepted')

#: How many findings a status description names before the count.
_NAMED: Final = 3

#: A settled security status: judged, not judged again on that head.
_SETTLED: Final = frozenset({'success', 'failure'})


class DeclarationInvalid(ValueError):
    """``[tool.dev_lab.security]`` is malformed; the message names the key."""


@dataclass(frozen=True)
class Declaration:
    """A repo's differences from the family default, each ``{name: reason}``."""

    exclude: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))
    ignore: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))
    allowed: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))
    accepted: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))


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
        policy = load_policy(root)
        base = f'origin/{policy.integration}'
        declaration = declared(_git(root, 'show', f'{base}:pyproject.toml').decode('utf-8'))
        heads = [
            (f'#{pull.number}', pull.head_sha)
            for pull in pr_list(client)
            if pull.base == policy.integration and not pull.draft
        ]
        heads = [(name, sha) for name, sha in heads if sha] + [
            (policy.integration, _git(root, 'rev-parse', base).decode().strip())
        ]
        for name, head in heads:
            if any(one.context == SECURITY_CONTEXT and one.state in _SETTLED for one in status_list(client, head)):
                continue
            found = judged(root, head, declaration)
            status_post(client, head, context=SECURITY_CONTEXT, state=found.state, description=found.description)
            say(f'[serve] security: {name} {head[:12]} {found.state}: {found.description}')
    except (ForgeCallFailed, ListingIncomplete, OSError, ValueError, subprocess.CalledProcessError) as failed:
        say(f'[serve] security: not judged this tick: {failed}')
