"""HPC ACCOUNT AFFINITY -- which cluster accounts produce a verify part (user ruling 2026-10-30).

WHO IS AFFINED IS DECLARED ONCE PER ACCOUNT, on its own deploy table: a verify account's ``[deploy] repos`` row
carries ``verify = ["tests/*"]``, the status contexts of that repo it is the producer of
(:class:`dev_lab.dev.hpchost.spec.Repo`). Its tick reads that row (:func:`declared`) and publishes it on its host
card (``HostCard.verify``), so every other seat learns the affined accounts from the cards it already reads each
tick. No account name is written anywhere else.

BY DEFAULT RESEARCH AND VERIFY ACCOUNTS NEVER BORROW FROM EACH OTHER, in either direction. On a cluster seat (a
workstation and a request are never gated):

* an AFFINED seat orders a covered part before every other candidate (:func:`covers`, OR'd into its
  ``[priority]`` ordering, which stays as each machine file declares it), and claims it at once;
* any other seat -- the research accounts -- never claims a part some LIVE affined card covers: it waits, named
  :data:`DEFERRED`, for the verify accounts, however long it has waited and however many are queued
  (:func:`defers`). With NO live affined card nothing is deferred, so a dark verify fleet never deadlocks the forge.

The one way past it is the user's opt-in: ``verify->research`` in the expiring allocation record
(:data:`lab_commons.hpc.allocation.VERIFY_BORROWS_RESEARCH`, written by ``python -m dev_lab.dev.hpchost allocate
--until <iso> --borrow verify->research``). While it is unexpired a research seat claims a covered part as any.

An affined seat's own uncovered work -- another repo, research -- is never deferred. Nothing is reserved or
preempted.

THE RESEARCH SIDE reads the same cards. A workstation's ``python -m lab_commons.hpc plan|submit|retry`` loads
:func:`research_affinity` (entry point :data:`lab_commons.hpc.affinity.READER`): the verify accounts, so
:func:`lab_commons.hpc.affinity.place` keeps research off them unless the record opts ``research->verify`` in.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Final

from lab_commons.compute.model import REQUEST, Candidate
from lab_commons.hpc.allocation import VERIFY_BORROWS_RESEARCH
from lab_commons.hpc.grants import Affinity

from dev_lab.dev.forgehosts import HostCard, read_cards
from dev_lab.dev.forgework import client_for
from dev_lab.dev.hpchost.spec import load
from dev_lab.dev.platformparts import part_context

__all__ = [
    'DEFERRED',
    'context_of',
    'covers',
    'declared',
    'deferral',
    'defers',
    'research_affinity',
    'research_affinity_of',
]

#: How a covered part a non-affined seat waits on is blocked: on its queue row and its host card.
DEFERRED: Final = 'deferred to the verify accounts'


def covers(patterns: Sequence[str], context: str) -> bool:
    """Whether *context* matches one of an affinity's *patterns* (fnmatch); ``''`` (a request) never does."""
    return bool(context) and any(fnmatchcase(context, one) for one in patterns)


def context_of(one: Candidate) -> str:
    """The status context of a part candidate; ``''`` for a request, which no affinity covers."""
    return '' if one.kind == REQUEST else part_context(one.platform)


def declared(path: Path, repo_url: str) -> tuple[str, ...]:
    """The ``verify`` patterns this account's ``[deploy]`` row for *repo_url* declares; ``()`` when none."""
    spec = load(path)
    want = _bare(repo_url)
    return next((repo.verify for repo in spec.repos if _bare(repo.url) == want), ()) if spec else ()


def _bare(url: str) -> str:
    return url.strip().rstrip('/').removesuffix('.git').lower()


def defers(*, hosts: Sequence[str], borrow: bool) -> str:
    """Why a non-affined seat does not claim a part the live affined *hosts* cover, ``''`` when it may.

    *borrow* is the user's unexpired ``verify->research`` opt-in. No live affined host defers nothing.
    """
    if not hosts or borrow:
        return ''
    return (
        f'{DEFERRED} ({", ".join(sorted(hosts))}): a research seat never claims a verify part unless the user '
        f'opts in (allocate --borrow {VERIFY_BORROWS_RESEARCH})'
    )


def deferral(
    cards: Sequence[HostCard], *, now: datetime, borrow: bool, mine: Sequence[str] = ()
) -> Callable[[Candidate], str]:
    """Why this seat defers a candidate (:func:`defers`), the live affined cards read once.

    *mine* is this seat's own affinity: a part it covers is never deferred.
    """
    live = [card for card in cards if card.verify and not card.stale(now)]

    def defer(wanted: Candidate) -> str:
        context = context_of(wanted)
        if covers(mine, context):
            return ''
        return defers(hosts=[card.host for card in live if covers(card.verify, context)], borrow=borrow)

    return defer


def research_affinity_of(cards: Sequence[HostCard]) -> Affinity | None:
    """The verify accounts in *cards*, each by its Slurm user; ``None`` when none.

    A card names its seat ``<cluster>/<user>``; a public repository's opaque card
    (:func:`~dev_lab.dev.forgehosts.host_id`) names no account and is not read. A stale card still names its
    account: a dark verify account is still not research's.
    """
    users = frozenset(card.host.rpartition('/')[2] for card in cards if card.verify and '/' in card.host)
    return Affinity(verify=users) if users else None


def research_affinity(root: Path | None = None) -> Affinity | None:
    """:func:`research_affinity_of` the host cards on *root*'s forge (default: the working directory's).

    THE READER lab-commons loads (entry point :data:`lab_commons.hpc.affinity.READER`), so a workstation
    session's research submission keeps off the accounts that produce the forge's verify parts.
    """
    return research_affinity_of(read_cards(client_for(Path.cwd() if root is None else root)))
