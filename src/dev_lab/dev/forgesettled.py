"""A commit whose every part is SETTLED never changes: its status history is read once and kept.

THE INCIDENT (2026-10-24): every tick of every host read ``GET .../statuses/<sha>`` for every served head
-- hundreds per repository in ten minutes -- though almost every head was long settled. A tick derives a
head's parts from its history (:func:`dev_lab.dev.platformparts.derived`) and claims what is missing; a head
whose every derived part has a settled latest status (``success``/``failure``, never a ``pending`` claim or a
retryable ``error``) has nothing left to claim, and a pushed commit cannot change. So such a history is
cached per repository (:attr:`~dev_lab.dev.forgework.Client.cache_dir`) and never asked again; every other
head is read each tick, once per tick. A claim still reads afresh (:func:`dev_lab.dev.forgeclaim.claim`), so
a stale cache can cost a refused claim, never a duplicate one.
"""

from __future__ import annotations

import dataclasses
import json
import os
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Any, Final

from dev_lab.dev.forgestatus import CommitStatus, status_history
from dev_lab.dev.platformparts import derived, parts_of

if TYPE_CHECKING:
    from dev_lab.dev.forgework import Client

__all__ = ['SettledHistories', 'settled']

#: The settled commits kept per repository, newest last; the oldest beyond it are dropped (and read again if served).
KEPT: Final = 4096


def settled(history: Sequence[CommitStatus]) -> bool:
    """Whether every part *history* derives has a settled LATEST status, and no ``tests/`` context is unsettled."""
    latest: dict[str, CommitStatus] = {}
    for status in sorted(history, key=lambda one: one.id):
        latest[status.context] = status
    parts, problems = parts_of(tuple(latest.values()))
    return not problems and set(derived(history)) <= set(parts)


class SettledHistories:
    """``history(sha)``: read once per reader, and never again once settled (module docstring)."""

    def __init__(
        self, client: Client, *, read: Callable[[Client, str], tuple[CommitStatus, ...]] = status_history
    ) -> None:
        """Load *client*'s repository cache; a client without a cache directory only memoizes."""
        self._client, self._read = client, read
        self._memo: dict[str, tuple[CommitStatus, ...]] = {}
        home = client.cache_dir
        self._path = None if home is None else home / f'settled-{client.forge.owner}-{client.forge.repo}.json'
        self._kept: dict[str, list[dict[str, Any]]] = self._load()

    def _load(self) -> dict[str, list[dict[str, Any]]]:
        if self._path is None:
            return {}
        try:
            saved = json.loads(self._path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return {}
        return saved if isinstance(saved, dict) else {}

    def __call__(self, sha: str) -> tuple[CommitStatus, ...]:
        """The history of *sha*: memoized, from the settled cache, else read (and kept when settled)."""
        if sha in self._memo:
            return self._memo[sha]
        if sha in self._kept:
            try:
                found = tuple(CommitStatus(**raw) for raw in self._kept[sha])
            except TypeError:
                found = None
            if found is not None:
                self._memo[sha] = found
                return found
        found = self._read(self._client, sha) if sha else ()
        self._memo[sha] = found
        if sha and settled(found):
            self._keep(sha, found)
        return found

    def _keep(self, sha: str, history: tuple[CommitStatus, ...]) -> None:
        if self._path is None:
            return
        self._kept[sha] = [dataclasses.asdict(one) for one in history]
        while len(self._kept) > KEPT:
            self._kept.pop(next(iter(self._kept)))
        self._path.parent.mkdir(parents=True, exist_ok=True)
        spare = self._path.with_name(f'{self._path.name}.{os.getpid()}.tmp')
        spare.write_text(json.dumps(self._kept), encoding='utf-8')
        spare.replace(self._path)
