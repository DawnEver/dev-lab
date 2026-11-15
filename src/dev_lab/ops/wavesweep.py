"""An open break-glass wave lands what is green: the host's own tick merges each green, non-draft PR it serves.

User ruling 2026-11-11: while a wave is open, nobody should have to run the merge by hand. The break-glass host's
tick (:meth:`dev_lab.ops.breakglass.Server.tick`) is the one place that holds the wave AND the merge credential, so
the sweep runs there and nowhere else -- never on an agent. It needs no credential and no consent beyond the wave.

Each candidate goes through the SAME admission as ``forge pr breakglass`` (:meth:`Server._merge`): the repo is one the
host serves, the PR targets its integration branch at the head it was judged at, and its security check and test
parts stand green (merge-ready's own reading, ``_waits_for_the_wave``) -- checked HERE, since the admission no
longer refuses on tests (user ruling 2026-11-11: an explicit break-glass merge waives them; the sweep never does).
The sweep only decides WHICH PRs to ask for:

- a draft is left alone (a draft runs nothing, so it is never judged);
- a PR whose ``tests/merge-ready`` already stands ``success`` lands by the normal path, which wins;
- a PR whose head is not current (``pr-current`` does not stand ``success``: it lacks the integration branch or its
  lock is stale) is left alone -- a wave lands only what is current, never a stale green head;
- a PR whose security check or test parts do not stand green (red, pending, unrun) is left alone;
- a PR whose admission or merge is refused (off the integration branch, the forge's own refusal) is
  skipped with its reason logged, never forced, and the sweep goes on: one PR never stops the tick;
- a PR the admission holds back for its own consent (``needs-consent``, :meth:`Server._admit`) is skipped and
  logged once per wave by the server; *land* answers ``None`` for it. A skip spends none of the cap.

Every merge counts against the wave's cap; the merge that reaches it closes the wave, whose ONE summary is the alert.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import Protocol

from lab_commons.log import emit

from dev_lab.dev.forge import forge_of_url
from dev_lab.dev.forgecontexts import MERGE_READY_CONTEXT
from dev_lab.dev.forgefailure import ForgeCallFailed
from dev_lab.dev.forgeheadgate import PR_CURRENT_CONTEXT
from dev_lab.dev.forgemergewaits import parts_wait
from dev_lab.dev.forgesecurity import security_wait
from dev_lab.dev.forgestatus import CommitStatus
from dev_lab.dev.lanepolicy import policy_from
from dev_lab.ops import request as requests

__all__ = ['Listing', 'Pull', 'integration_at', 'reason_of', 'sweep']


@dataclass(frozen=True)
class Pull:
    """One open PR as the sweep reads it: its number, base branch, head commit and whether it is a draft."""

    number: int
    base: str
    head: str
    draft: bool


class Listing(Protocol):
    """What the sweep reads of one served repository's forge."""

    def declaration(self, ref: str) -> str:
        """The repository's ``pyproject.toml`` at *ref*; raises ``ValueError`` when it cannot be read."""
        ...

    def open_pulls(self) -> Sequence[Pull]:
        """Every open PR."""
        ...

    def statuses(self, head: str) -> Sequence[CommitStatus]:
        """The statuses *head* carries."""
        ...


def integration_at(forge: Listing, base: str, repo: str) -> str:
    """The integration branch *repo*'s declaration AT *base* names -- the branch a PR into *base* lands on.

    The ONE reading break-glass makes (admission and sweep): never the default branch, which may hold no declaration
    (2026-11-12: a member's ``main`` an old data commit, ``integrate/main`` the declared one).
    """
    return policy_from(forge.declaration(base), f'{repo}@{base}:pyproject.toml').integration


def reason_of(wave: str) -> str:
    """The reason a swept merge records: which wave landed it, and what it waived."""
    return f'wave {wave} lands what is green: the review is waived, its security and test parts stand green'


def _waits_for_the_wave(posted: Sequence[CommitStatus], head: str) -> bool:
    """Whether *head* is current and green -- security check and test parts PASS -- yet not already merge-ready."""
    if _stands(posted, MERGE_READY_CONTEXT) or not _stands(posted, PR_CURRENT_CONTEXT):
        return False
    return security_wait(posted) is None and parts_wait(head, posted) is None


def _stands(posted: Sequence[CommitStatus], context: str) -> bool:
    return any(one.context == context and one.state == 'success' for one in posted)


def _integrates(forge: Listing, base: str, url: str) -> bool:
    """Whether *base* is the integration branch its own declaration names; unreadable there is ``False``."""
    try:
        return integration_at(forge, base, url) == base
    except ValueError:
        return False


def sweep(
    repos: Iterable[str], forge_for: Callable[[str], Listing], *, wave: Callable[[], str | None],
    land: Callable[[requests.Merge], str | None], refused: type[Exception],
) -> list[str]:  # fmt: skip
    """Ask *land* for every green, non-draft PR of each of *repos* while *wave* names an open wave; what each said.

    *land* is the server's one admission and merge (``None``: held back, logged by it); a PR it refuses
    with *refused*, or the forge refuses (:class:`ForgeCallFailed`), is skipped and logged, never forced. The
    caller holds the role lock. No open wave: nothing is read and nothing merges.
    """
    said: list[str] = []
    for url in repos:
        if (held := wave()) is None:
            return said
        forge = forge_for(url)
        for pull in forge.open_pulls():
            if pull.draft or not _integrates(forge, pull.base, url):
                continue
            if not _waits_for_the_wave(forge.statuses(pull.head), pull.head):
                continue
            try:
                landed = land(requests.Merge(forge_of_url(url).identity, pull.number, pull.head, reason_of(held)))
            except (refused, ForgeCallFailed) as why:
                emit(f'[breakglass] wave {held}: {url} #{pull.number} skipped: {str(why).splitlines()[0]}', err=True)
                continue
            if landed is None:
                continue
            said.append(landed)
            if wave() is None:  # the cap closed the wave
                return said
    return said
