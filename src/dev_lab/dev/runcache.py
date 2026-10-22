"""THE RUN CACHE -- this box's memory of judged runs, so a key already judged is CITED, not re-run.

WHAT IT IS, AND IS NOT. A cache of :mod:`dev_lab.dev.verify` runs keyed by ``(tree, env,
selector)``; it decides no push and is read by nobody else. A platform result is a ``tests/<part>``
part on the forge (:mod:`dev_lab.dev.platformparts`), which every workstation can read; the
per-test outcomes travel in that part's run record, not here.

WHAT IS STORED. An :class:`lab_commons.outcomes.Record` (plan A1.5): per key -- the identity of
``(tree, env, selector)`` -- one outcome event, ``OK`` for PASS and ``REJECTED`` for FAIL, its data the key,
the commit it was about and the log it rests on. Only a settled verdict on a tree that did not move is
stored (:func:`remember` refuses anything else). The first decision is final: a run deciding a key the
other way is a ``flaky`` event, never an overwrite, and a flaky key is never served. A repeat of the same
decision writes nothing, so the first log is the one cited.

A cache of the retired line shape (one JSON object per run, no schema) is refused by name with
:class:`RetiredCache`: it is regenerable -- delete it and the next runs re-fill it.

WHERE IT LIVES. ``output/runcache/record.jsonl`` in the MAIN checkout -- resolved through git's common
directory, so every lane worktree shares one cache. It is a NEW file, not the retired line-shape file
renamed in place: a checkout still at the retired code keeps appending its own file, so the two shapes never
meet in one file while the family converges (the retired file is regenerable; delete it at will).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

import lab_commons.launch as _door
from dev_lab.dev.forge import _GIT
from dev_lab.dev.verdict import Verdict
from lab_commons.outcomes import OUTCOME, Cell, Conclusion, Event, FinalityError, Identity, Reason, Record, Status

__all__ = [
    'CACHED',
    'CACHE_REL',
    'FLAKY',
    'CachedRun',
    'RetiredCache',
    'cache_path',
    'cached',
    'record',
    'remember',
    'runs',
]

#: The cache, relative to the MAIN checkout's root.
CACHE_REL: Final = 'output/runcache/record.jsonl'

#: The only results cached. INCONCLUSIVE says nothing about the tree.
CACHED: Final = frozenset(outcome.value.upper() for outcome in Conclusion if outcome.settled)

_GIT_TIMEOUT_S: Final = 60

#: The caller event kind recorded when a key is decided the other way.
FLAKY: Final = 'flaky'

#: A settled result word -> the cell it is.
_CELL: Final = {
    Conclusion.PASS.value.upper(): Cell(Status.OK),
    Conclusion.FAIL.value.upper(): Cell(Status.REJECTED, reason=Reason('fail', 'the verdict was FAIL')),
}


class RetiredCache(ValueError):
    """A cache of the retired line shape: regenerable, so refused -- delete it and re-run."""


@dataclass(frozen=True, slots=True)
class CachedRun:
    """One judged run: the key, the result, the commit it was about (``''`` for a dirty tree), the log."""

    tree: str
    env: str
    selector: str
    result: str
    commit: str
    log: str
    at: str = ''


def cache_path(root: Path) -> Path:
    """The cache for the repository *root* belongs to, in its MAIN checkout (shared by every lane)."""
    common = _door.run(
        [_GIT, '-C', str(root), 'rev-parse', '--path-format=absolute', '--git-common-dir'],
        capture_output=True,
        text=True,
        encoding='utf-8',
        check=True,
        timeout=_GIT_TIMEOUT_S,
    ).stdout.strip()
    return Path(common).parent / CACHE_REL


def _key(run: CachedRun) -> str:
    return Identity.of({'tree': run.tree, 'env': run.env, 'selector': run.selector}).key


def record(path: Path, run: CachedRun) -> None:
    """Append *run* as its key's outcome; an opposite decision is a ``flaky`` event, never an overwrite."""
    cache = _open(path)
    data = {name: value for name, value in asdict(run).items() if name != 'result'}
    try:
        cache.outcome(_key(run), _CELL[run.result], data=data)
    except FinalityError:
        cache.append(Event(FLAKY, _key(run), data={**data, 'result': run.result}))


def remember(path: Path, verdict: Verdict, *, tree: str, env: str, selector: str, commit: str) -> CachedRun | None:
    """Record the run when its verdict is settled; an unsettled one is not a fact and is not cached."""
    if not verdict.result.outcome.settled:
        return None
    run = CachedRun(
        tree,
        env,
        selector,
        verdict.result.outcome.value.upper(),
        commit,
        f'{verdict.log.path.resolve()}@{verdict.log.digest}',
        datetime.now(UTC).isoformat(timespec='seconds'),
    )
    record(path, run)
    return run


def _open(path: Path) -> Record:
    """The cache's Record; a file of the retired line shape raises :class:`RetiredCache`."""
    try:
        first = path.read_text(encoding='utf-8').splitlines()[0]
    except FileNotFoundError:
        return Record(path)
    try:
        retired = 'schema' not in json.loads(first)
    except ValueError:
        retired = False  # a torn tail is the Record's to judge
    if retired:
        msg = (
            f'{path} is a run cache of the retired line shape; it is regenerable, so it is refused, never '
            'upgraded -- delete it and the next runs re-fill it'
        )
        raise RetiredCache(msg)
    return Record(path)


def _replayed(path: Path) -> tuple[list[CachedRun], set[str]]:
    found: list[CachedRun] = []
    flaky: set[str] = set()
    for event in _open(path).replay():
        if event.kind == FLAKY:
            flaky.add(event.key)
        elif event.kind == OUTCOME and event.cell is not None:
            result = next(word for word, cell in _CELL.items() if cell.status is event.cell.status)
            found.append(CachedRun(**{**event.data, 'result': result}))
    return found, flaky


def runs(path: Path) -> tuple[CachedRun, ...]:
    """Every cached decision, oldest first; an absent cache is empty."""
    return tuple(_replayed(path)[0])


def cached(path: Path, *, tree: str, env: str, selector: str) -> CachedRun | None:
    """The key's decision, or ``None`` when there is none or the key is FLAKY."""
    found, flaky = _replayed(path)
    probe = CachedRun(tree, env, selector, '', '', '')
    if _key(probe) in flaky:
        return None
    return next((run for run in found if _key(run) == _key(probe)), None)
