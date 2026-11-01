"""A DECLARED WORKSTATION POSTS ITS FULL PART -- the one exception to ``VERDICTS-FROM-THE-FORGE`` (ruling D50-1).

A verdict is a fact about a content key (:class:`dev_lab.dev.verdictstore.ContentKey`: tree, env key, part), not
about which machine produced it, so a workstation the repo's serving setup already declares a producer may post
it -- under every condition below, each one REFUSING when unmet (:func:`posting_refusal`):

* DECLARED: this box's machine file ``[serve]`` table lists the repo in ``repos`` and its ``parts`` rule claims
  the part (:class:`lab_commons.compute.serves.Serves`) -- the same declaration ``workstation deploy`` writes and
  ``forge serve`` claims by; there is no second roster. The box has the part's needs (its OS row included).
* NOT REVOKED: the box has fewer than :data:`~dev_lab.dev.workstationrevoke.STRIKES_TO_REVOKE` strikes
  (:mod:`dev_lab.dev.workstationrevoke`). An unreadable store, a malformed strike file, an unreadable origin or
  machine file each REFUSE, never crash.
* CLEAN AND PUSHED: no dirt, and HEAD is on an ``origin`` branch -- so the tree is a pushed sha's tree.
* FULL: ``verify --part <part>`` naming no pytest argument; a selection is a measure and never posts.
* CURRENT ENV: the lock is fresh (:func:`dev_lab.dev.lockpins.lock_freshness`).

The run then posts exactly as a producer's does (:func:`dev_lab.dev.localpart.post_part`: the record to the
run-records store, the status through the outbox and :func:`~dev_lab.dev.forgestatus.status_post`), its record
naming the box and the tree, so it is audited like any producer record.

DEDUPE BY KEY (:func:`before_run`): before a producer runs a full part it asks the store
(:func:`dev_lab.dev.verdictstore.lookup`) for a PASS of the same key from no revoked box, and cites it.

SPOT CHECK (:func:`spot_checked`, :func:`after_run`). ANY hit -- whatever box its record names or omits, so
coverage never rests on a self-asserted field -- is re-run instead of cited with probability
:data:`SPOT_CHECK_FRACTION`, drawn by the checking producer at check time, so a box cannot know which of its
records will be checked. A re-run that FAILS where the record PASSED strikes the box the record names
(:func:`dev_lab.dev.workstationrevoke.strike`); enough strikes revoke it.
"""

from __future__ import annotations

import random
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
from dev_lab.dev.forgework import client_for
from dev_lab.dev.localpart import present_here
from dev_lab.dev.lockpins import lock_freshness
from dev_lab.dev.partrows import row_part
from dev_lab.dev.platformparts import part_context
from dev_lab.dev.treedirt import status_paths
from dev_lab.dev.verdictstore import WORKSTATION_KEY, ContentKey, Found, cite, lookup
from dev_lab.dev.workstationrevoke import revoked, strike, strikes_name

if TYPE_CHECKING:
    from dev_lab.dev.forgework import Client

__all__ = [
    'SPOT_CHECK_FRACTION',
    'Decision',
    'Facts',
    'after_run',
    'before_run',
    'declared_refusal',
    'head_tree',
    'posting_refusal',
    'pushed',
    'spot_checked',
    'workstation_fields',
    'workstation_refusal',
]

#: The fraction of store hits a producer re-runs instead of citing.
SPOT_CHECK_FRACTION: Final = 0.2

_GIT_TIMEOUT_S: Final = 60


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


def _declared(root: Path, part: str) -> str:
    """:func:`declared_refusal` of this box; an unreadable origin or machine file is a refusal naming it."""
    try:
        repo = forge_from_remote(root).repo
        return declared_refusal(section(SERVE_TABLE), repo=repo, part=part, present=present_here(root))
    except (OSError, ValueError) as unread:
        return f'its declaration could not be read ({unread})'


def _revoked_here(client: Client | None, root: Path) -> str:
    """Why this box may not post by its strikes: ``''`` when it may; FAIL CLOSED on anything unreadable."""
    try:
        gone = strikes_name(this_machine()) in revoked(client or client_for(root))
    except (OSError, ValueError) as failed:
        return f'the revocation list could not be read ({failed})'
    return 'its contradicted spot checks reached the limit' if gone else ''


def workstation_refusal(root: Path, part: str, *, full: bool, client: Client | None = None) -> str | None:
    """:func:`posting_refusal` of THIS box posting *part* of *root*'s HEAD (module docstring); ``None``: it may."""
    facts = Facts(
        part=part, full=full, declared=_declared(root, part), revoked=_revoked_here(client, root),
        dirt=status_paths(root), pushed=pushed(root), stale=lock_freshness(root) or '',
    )  # fmt: skip
    return posting_refusal(facts)


def workstation_fields(root: Path) -> dict[str, str]:
    """The keys a declared workstation's record adds: the box and the tree it judged."""
    return {WORKSTATION_KEY: this_machine(), 'tree': head_tree(root)}


@dataclass(frozen=True)
class Decision:
    """A producer's reading of the store: *found* (a hit), whether it was *cited*, and the *line* to say."""

    found: Found | None = None
    cited: bool = False
    line: str = ''


def spot_checked(found: Found, *, me: str, draw: Callable[[], float] = random.random) -> bool:
    """Whether producer *me* re-runs *found* instead of citing it: any hit not naming *me*, sampled at check time."""
    return found.workstation != me and draw() < SPOT_CHECK_FRACTION


def before_run(
    root: Path, sha: str, key: ContentKey, *, me: str, client: Client, draw: Callable[[], float] = random.random
) -> Decision:
    """A producer's look at the store before it runs *key* (module docstring); an unreadable store: run, saying so."""
    try:
        found = lookup(root, client, key, revoked=revoked(client))
    except (OSError, ValueError) as unread:
        return Decision(line=f'[workstationverdict] the store was not read ({unread}); running')
    if found is None:
        return Decision()
    if spot_checked(found, me=me, draw=draw):
        return Decision(found, line=f'[workstationverdict] spot check: re-running {found.attachment.name}')
    return Decision(found, cited=True, line=cite(client, sha, found))


def after_run(client: Client, found: Found, result: Conclusion) -> str:
    """Compare a spot-check re-run's *result* with the PASS record *found*; a FAIL strikes the box it names."""
    if result is not Conclusion.FAIL:
        return f'[workstationverdict] spot check of {found.attachment.name}: {result.name}, no contradiction'
    why = f'{found.attachment.name} said PASS; a re-run said FAIL'
    if not found.workstation:
        return f'[workstationverdict] spot check CONTRADICTED: {why} -- the record names no box to strike'
    return strike(client, found.workstation, why)
