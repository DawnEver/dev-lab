"""A DECLARED WORKSTATION POSTS ITS FULL PART -- the one exception to ``VERDICTS-FROM-THE-FORGE`` (ruling D50-1).

A verdict is a fact about a CONTENT KEY (:class:`ContentKey`): the committed tree (``HEAD^{tree}``, what ``git
write-tree`` of a clean checkout writes), the environment key ``verify`` prints (:func:`lab_commons.envkey.env_key`)
and the part. Which machine produced it is not part of the fact, so a workstation the repo's serving setup
already declares a producer may post it -- under every condition below, each one REFUSING when unmet
(:func:`posting_refusal`):

* DECLARED: this box's machine file ``[serve]`` table lists the repo in ``repos`` and its ``parts`` rule claims
  the part (:class:`lab_commons.compute.serves.Serves`) -- the same declaration ``workstation deploy`` writes and
  ``forge serve`` claims by; there is no second roster. The box has the part's needs (its OS row included).
* NOT REVOKED: the box is not on :data:`REVOKED_NAME` in the run-records store (an unreadable store refuses).
* CLEAN AND PUSHED: no dirt, and HEAD is on an ``origin`` branch -- so the tree is a pushed sha's tree.
* FULL: ``verify --part <part>`` naming no pytest argument; a selection is a measure and never posts.
* CURRENT ENV: the lock is fresh (:func:`dev_lab.dev.lockpins.lock_freshness`).

The run then posts exactly as a producer's does (:func:`dev_lab.dev.localpart.post_part`: the record to the
run-records store, the status through the outbox and :func:`~dev_lab.dev.forgestatus.status_post`), its record
naming the box (:data:`WORKSTATION_KEY`) and the tree, so it is audited like any producer record.

DEDUPE BY KEY (:func:`lookup`, :func:`cite`). Before a producer runs a full part it reads the store: a settled
full record of the same part whose sha's tree is this tree and whose ``env`` is this env key is the verdict --
posted on this sha with that record as its ``target_url``, nothing re-run. A different tree or another env key
is never a hit. (REACH-CARRY, :mod:`dev_lab.dev.forgecarry`, carries ACROSS trees by footprint; this is the
exact-tree case.)

SPOT CHECK (:func:`spot_checked`, :func:`revoke`). A hit on a WORKSTATION record is re-run instead of cited with
probability :data:`SPOT_CHECK_FRACTION`, drawn by the checking producer at check time -- never derivable from the
key, so a box cannot know which of its records will be checked. A re-run whose conclusion differs from the
record's revokes the box: it is added to :data:`REVOKED_NAME` with the two conclusions, and every later post from
it is refused.
"""

from __future__ import annotations

import gzip
import json
import random
import subprocess
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

import lab_commons.launch as _door
from lab_commons.compute.serves import SERVE_TABLE, Serves
from lab_commons.config import section
from lab_commons.hpc.needsets import needs_of
from lab_commons.outcomes import Conclusion

from dev_lab.dev.forge import forge_from_remote
from dev_lab.dev.forgeclaim import this_machine
from dev_lab.dev.forgerecords import listing, read_named, replace_named
from dev_lab.dev.forgestatus import status_post
from dev_lab.dev.forgework import client_for
from dev_lab.dev.localpart import present_here
from dev_lab.dev.lockpins import lock_freshness
from dev_lab.dev.partrows import row_part
from dev_lab.dev.platformparts import PartRefusal, part_context, part_of
from dev_lab.dev.treedirt import status_paths

if TYPE_CHECKING:
    from dev_lab.dev.forgerecords import Attachment
    from dev_lab.dev.forgework import Client

__all__ = [
    'REVOKED_NAME',
    'SPOT_CHECK_FRACTION',
    'WORKSTATION_KEY',
    'ContentKey',
    'Facts',
    'Found',
    'after_run',
    'before_run',
    'cite',
    'declared_refusal',
    'head_tree',
    'lookup',
    'posting_refusal',
    'pushed',
    'revoke',
    'revoked',
    'spot_checked',
    'trees_of',
    'workstation_fields',
    'workstation_refusal',
]

#: The record key naming the workstation that produced it; absent on a forge producer's record.
WORKSTATION_KEY: Final = 'workstation'

#: The one mutable file in the run-records store listing revoked workstations: ``{host: why}``.
REVOKED_NAME: Final = 'workstation-revoked.json'

#: The fraction of workstation-record hits a forge producer re-runs instead of citing.
SPOT_CHECK_FRACTION: Final = 0.2

_GIT_TIMEOUT_S: Final = 60

#: How many hex digits a full commit sha has.
_SHA_HEX: Final = 40


@dataclass(frozen=True)
class ContentKey:
    """What a part's verdict is a fact about: the committed tree, the env key and the part."""

    tree: str
    env: str
    part: str


@dataclass(frozen=True)
class Facts:
    """What :func:`posting_refusal` judges, read off this box (``declared``/``revoked``: ``''`` when fine)."""

    part: str
    full: bool
    declared: str
    revoked: str
    dirt: tuple[str, ...] | None
    pushed: bool
    stale: str


def declared_refusal(serve: Mapping[str, Any], *, repo: str, part: str, present: Collection[str]) -> str:
    """Why this box is no declared producer of *part* of *repo* by its ``[serve]`` table; ``''`` when it is."""
    if repo not in (serve.get('repos') or []):
        return f'this box does not serve {repo} (machine file [{SERVE_TABLE}] repos)'
    try:
        skipped = Serves.of(serve).skips(needs_of(row_part(part)))
    except ValueError as why:
        return str(why)
    if skipped:
        return f'its [{SERVE_TABLE}] rule does not claim {part_context(part)} ({skipped})'
    if missing := sorted(needs_of(row_part(part)) - set(present)):
        return f'this box lacks {", ".join(missing)}, which {part_context(part)} needs'
    return ''


def posting_refusal(facts: Facts) -> str | None:
    """``None`` when a workstation may post *facts.part*; else every unmet condition, named. PURE."""
    why = [
        *([facts.declared] if facts.declared else []),
        *([f'this box is revoked: {facts.revoked}'] if facts.revoked else []),
        *([] if facts.full else ['the run is a selection, not the full part']),
        *(['the tree could not be read'] if facts.dirt is None else []),
        *([f'the tree is dirty ({len(facts.dirt)} path(s))'] if facts.dirt else []),
        *([] if facts.pushed else ['HEAD is on no origin branch: push it first']),
        *([f'the env key is stale: {facts.stale}'] if facts.stale else []),
    ]
    if not why:
        return None
    return f'a workstation may post {part_context(facts.part)} only when ' + '; '.join(why)


def revoked(client: Client) -> dict[str, str]:
    """``{host: why}`` from :data:`REVOKED_NAME`; none stored reads empty. An unreadable store RAISES."""
    data = read_named(client, REVOKED_NAME)
    return {} if data is None else {str(k): str(v) for k, v in json.loads(data.decode('utf-8')).items()}


def revoke(client: Client, host: str, why: str) -> str:
    """Add *host* to :data:`REVOKED_NAME` naming *why*; the line saying so."""
    table = {**revoked(client), host: why}
    replace_named(client, REVOKED_NAME, json.dumps(table, sort_keys=True).encode('utf-8'))
    return f'[workstationverdict] REVOKED workstation {host}: {why}'


def _git(root: Path, *args: str) -> str:
    done = _door.run(
        ['git', *args], cwd=root, capture_output=True, text=True, encoding='utf-8', check=False,
        timeout=_GIT_TIMEOUT_S,
    )  # fmt: skip
    return done.stdout if done.returncode == 0 else ''


def head_tree(root: Path) -> str:
    """The tree HEAD commits -- what ``git write-tree`` writes for a clean checkout; ``''`` when unreadable."""
    return _git(root, 'rev-parse', 'HEAD^{tree}').strip()


def pushed(root: Path) -> bool:
    """Whether HEAD is on an ``origin`` remote-tracking branch."""
    return bool(_git(root, 'for-each-ref', '--contains', 'HEAD', '--format=%(refname)', 'refs/remotes/origin').strip())


def trees_of(root: Path, shas: Collection[str]) -> dict[str, str]:
    """``{sha: its tree}`` for each of *shas* this checkout holds; an unknown sha is left out."""
    if not shas:
        return {}
    try:
        out = _git(root, 'log', '--no-walk', '--ignore-missing', '--format=%H %T', *sorted(shas))
    except (OSError, subprocess.TimeoutExpired):
        return {}
    return dict(line.split(' ', 1) for line in out.splitlines() if ' ' in line)


@dataclass(frozen=True)
class Found:
    """A stored record proving *key*: its attachment, its record and the part it proves."""

    attachment: Attachment
    record: Mapping[str, Any]

    @property
    def workstation(self) -> str:
        """The box that produced it, ``''`` for a forge producer."""
        return str(self.record.get(WORKSTATION_KEY, ''))

    @property
    def result(self) -> Conclusion:
        """The conclusion it proves."""
        return part_of(self.record).result


def _sha_part(name: str) -> tuple[str, str] | None:
    """``(sha, part)`` of a run record's name ``run-<sha>-<part>-<req>[-<hash>].json.gz``; ``None`` otherwise."""
    if not name.startswith('run-') or not name.endswith('.json.gz'):
        return None
    sha, _, rest = name[4:].partition('-')
    part, _, _ = rest.partition('-')
    return (sha, part) if len(sha) == _SHA_HEX and part else None


def lookup(
    root: Path, client: Client, key: ContentKey, *, download: Callable[[str], bytes] | None = None
) -> Found | None:
    """The newest stored settled FULL record of *key*'s part at *key*'s tree and env; ``None`` on no hit."""
    named = [(item, found) for item in listing(client) if (found := _sha_part(item.name)) and found[1] == key.part]
    trees = trees_of(root, {sha for _, (sha, _) in named})
    fetch = download or client.download
    for item, (sha, _) in reversed(named):
        if trees.get(sha) != key.tree:
            continue
        record = json.loads(gzip.decompress(fetch(item.url)).decode('utf-8'))
        if record.get('env') != key.env or record.get('scope') != 'full' or record.get('platform') != key.part:
            continue
        try:
            part_of(record)
        except PartRefusal:
            continue
        return Found(item, record)
    return None


def spot_checked(found: Found, *, me: str, draw: Callable[[], float] = random.random) -> bool:
    """Whether a producer *me* re-runs *found* instead of citing it: a workstation's record, not its own, sampled."""
    return bool(found.workstation) and found.workstation != me and draw() < SPOT_CHECK_FRACTION


def cite(client: Client, sha: str, found: Found) -> str:
    """Post *found*'s part on *sha* through the status door, its record as the target; the line."""
    part = part_of(found.record)
    status_post(
        client, sha, context=part_context(part.platform), state=part.state, description=part.description(),
        target_url=found.attachment.url,
    )  # fmt: skip
    by = f'workstation {found.workstation}' if found.workstation else 'a forge producer'
    return f'[workstationverdict] {part.platform} part {part.result.name} CITED from {found.attachment.name} ({by})'


def workstation_refusal(root: Path, part: str, *, full: bool, client: Client | None = None) -> str | None:
    """:func:`posting_refusal` of THIS box posting *part* of *root*'s HEAD (module docstring); ``None``: it may."""
    repo = forge_from_remote(root).repo
    declared = declared_refusal(section(SERVE_TABLE), repo=repo, part=part, present=present_here(root))
    try:
        why = revoked(client or client_for(root)).get(this_machine(), '')
    except OSError as failed:  # fail CLOSED: an unread revocation list is no permission
        why = f'the revocation list could not be read ({failed})'
    facts = Facts(
        part=part, full=full, declared=declared, revoked=why, dirt=status_paths(root), pushed=pushed(root),
        stale=lock_freshness(root) or '',
    )  # fmt: skip
    return posting_refusal(facts)


def workstation_fields(root: Path) -> dict[str, str]:
    """The keys a declared workstation's record adds: the box (:data:`WORKSTATION_KEY`) and the tree it judged."""
    return {WORKSTATION_KEY: this_machine(), 'tree': head_tree(root)}


def before_run(root: Path, sha: str, key: ContentKey, *, me: str, client: Client) -> tuple[Found | None, str]:
    """A producer's look at the store before it runs *key*: ``(found, line)``; cite when the line says CITED.

    No hit, or an unreadable store: ``(None, '')`` -- run. A spot-checked workstation hit: ``(found, '')`` --
    run, then :func:`after_run` compares. Any other hit is cited on *sha*: ``(found, <the cite line>)``.
    """
    try:
        found = lookup(root, client, key)
    except (OSError, ValueError):
        return None, ''
    if found is None:
        return None, ''
    if spot_checked(found, me=me):
        return found, ''
    return found, cite(client, sha, found)


def after_run(client: Client, found: Found, result: Conclusion) -> str:
    """Compare a spot-check re-run's *result* with the workstation record *found*; revoke the box on a mismatch."""
    if result is Conclusion.INCONCLUSIVE or result is found.result:
        return f'[workstationverdict] spot check of {found.attachment.name}: {result.name} agrees'
    why = f'{found.attachment.name} said {found.result.name}; a re-run said {result.name}'
    return revoke(client, found.workstation, why)
