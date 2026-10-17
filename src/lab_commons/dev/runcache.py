"""THE RUN CACHE -- this box's memory of judged runs, so a key already judged is CITED, not re-run.

WHAT IT IS, AND IS NOT. A cache of :mod:`lab_commons.dev.verify` runs keyed by ``(tree, env,
selector)``; it decides no push and is read by nobody else. A platform result is a ``tests/<part>``
part on the forge (:mod:`lab_commons.dev.platformparts`), which every workstation can read; the
per-test outcomes travel in that part's run record, not here.

WHAT IS STORED. Only a PASS or FAIL on a tree that did not move during the run (:func:`remember`
refuses anything else), with the commit it was about and the log it rests on. A key seen as both PASS
and FAIL is FLAKY and is never served, whatever came last.

WHERE IT LIVES. ``output/runcache/runs.jsonl`` in the MAIN checkout -- resolved through git's common
directory, so every lane worktree shares one cache.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

import lab_commons.launch as _door
from lab_commons.dev.forge import _GIT
from lab_commons.dev.verdict import Outcome, Verdict

__all__ = ['CACHED', 'CACHE_REL', 'CachedRun', 'cache_path', 'cached', 'remember', 'runs']

#: The cache, relative to the MAIN checkout's root.
CACHE_REL: Final = 'output/runcache/runs.jsonl'

#: The only results cached. INCONCLUSIVE says nothing about the tree.
CACHED: Final = frozenset(outcome.value.upper() for outcome in Outcome if outcome.settled)

_GIT_TIMEOUT_S: Final = 60


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


def remember(path: Path, verdict: Verdict, *, tree: str, env: str, selector: str, commit: str) -> CachedRun | None:
    """Append the run when its verdict is settled; an unsettled one is not a fact and is not cached."""
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
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a', encoding='utf-8') as handle:
        handle.write(json.dumps(asdict(run), sort_keys=True) + '\n')
    return run


def runs(path: Path) -> tuple[CachedRun, ...]:
    """Every cached run, oldest first; an absent cache is empty, a torn or foreign line is skipped."""
    try:
        lines = path.read_text(encoding='utf-8').splitlines()
    except FileNotFoundError:
        return ()
    out: list[CachedRun] = []
    for line in lines:
        try:
            out.append(CachedRun(**json.loads(line)))
        except (ValueError, TypeError):
            continue
    return tuple(out)


def cached(path: Path, *, tree: str, env: str, selector: str) -> CachedRun | None:
    """The newest run for the key, or ``None`` when there is none or the key is FLAKY."""
    matching = [run for run in runs(path) if (run.tree, run.env, run.selector) == (tree, env, selector)]
    if not matching or {run.result for run in matching} == CACHED:
        return None
    return matching[-1]
