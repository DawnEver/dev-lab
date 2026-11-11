"""An open break-glass wave lands what is green: the host's own tick merges each green, non-draft PR it serves.

User ruling 2026-11-11: while a wave is open, nobody should have to run the merge by hand. The break-glass host's
tick (:meth:`dev_lab.ops.breakglass.Server.tick`) is the one place that holds the wave AND the merge credential, so
the sweep runs there and nowhere else -- never on an agent. It needs no credential and no consent beyond the wave.

Each candidate goes through the SAME admission as ``forge pr breakglass`` (:meth:`Server._merge`): the repo is one the
host serves, the PR targets its integration branch at the head it was judged at, and its security check and test
parts stand green (``_tests_stand``). The sweep only decides WHICH PRs to ask for:

- a draft is left alone (a draft runs nothing, so it is never judged);
- a PR whose ``tests/merge-ready`` already stands ``success`` lands by the normal path, which wins;
- a PR whose admission is refused (red, pending, off the integration branch) is skipped, never forced.

Every merge counts against the wave's cap; the merge that reaches it closes the wave, whose ONE summary is the alert.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import Protocol

from dev_lab.dev.forge import forge_of_url
from dev_lab.dev.forgecontexts import MERGE_READY_CONTEXT
from dev_lab.dev.forgestatus import CommitStatus
from dev_lab.dev.lanepolicy import policy_from
from dev_lab.ops import request as requests

__all__ = ['Listing', 'Pull', 'reason_of', 'sweep']


@dataclass(frozen=True)
class Pull:
    """One open PR as the sweep reads it: its number, base branch, head commit and whether it is a draft."""

    number: int
    base: str
    head: str
    draft: bool


class Listing(Protocol):
    """What the sweep reads of one served repository's forge."""

    def declaration(self) -> str:
        """The repository's ``pyproject.toml`` at its default branch."""
        ...

    def open_pulls(self) -> Sequence[Pull]:
        """Every open PR."""
        ...

    def statuses(self, head: str) -> Sequence[CommitStatus]:
        """The statuses *head* carries."""
        ...


def reason_of(wave: str) -> str:
    """The reason a swept merge records: which wave landed it, and what it waived."""
    return f'wave {wave} lands what is green: the review is waived, its security and test parts stand green'


def _merge_ready(forge: Listing, head: str) -> bool:
    return any(one.context == MERGE_READY_CONTEXT and one.state == 'success' for one in forge.statuses(head))


def sweep(
    repos: Iterable[str], forge_for: Callable[[str], Listing], *, wave: Callable[[], str | None],
    land: Callable[[requests.Merge], str], refused: type[Exception],
) -> list[str]:  # fmt: skip
    """Ask *land* for every green, non-draft PR of each of *repos* while *wave* names an open wave; what each said.

    *land* is the server's one admission and merge; a PR it refuses with *refused* is skipped, never forced. The
    caller holds the role lock. No open wave: nothing is read and nothing merges.
    """
    said: list[str] = []
    for url in repos:
        if (held := wave()) is None:
            return said
        forge = forge_for(url)
        try:
            integration = policy_from(forge.declaration(), f'{url}:pyproject.toml').integration
        except ValueError:
            continue
        for pull in forge.open_pulls():
            if pull.draft or pull.base != integration or _merge_ready(forge, pull.head):
                continue
            try:
                said.append(land(requests.Merge(forge_of_url(url).identity, pull.number, pull.head, reason_of(held))))
            except refused:
                continue
            if wave() is None:  # the cap closed the wave
                return said
    return said
