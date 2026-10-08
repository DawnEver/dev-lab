"""THE VERDICT LEDGER -- the one record of promoted verdicts, keyed by ``(tree, env, test)``.

WHY IT EXISTS. Until 2026-10-08 a verdict lived only as a stamped line at the end of a log, so
"has this tree already been judged?" was answered by parsing scattered logs, and nothing answered it
BEFORE a run. Agents therefore re-ran what had been judged, and push admission re-parsed log text.
This file is the single source of truth both now read:

* the RUNNER reads it before running -- a key already recorded is CITED, not re-run;
* PUSH ADMISSION reads it instead of log text (:mod:`lab_commons.dev.admission`).

THE WRITER IS THE RUNNER, AND ONLY AFTER PROMOTION. A run starts INCONCLUSIVE and is promoted only on
proof (:mod:`lab_commons.dev.verdict`); only a PASS or FAIL on a tree that did not move during the
run is recorded. :func:`record` refuses anything else, so "nobody knows" can never be served as a
fact. Logs stay as the evidence each entry points at.

WHAT IS NEVER SERVED. A key seen as both PASS and FAIL is FLAKY and is never served, whatever came
last. A test that drives a live vendor engine has an input outside the tree -- the engine -- so the
writer never records it (:data:`LIVE_MARKERS`).

THE KEY'S FIRST VERSION IS THE WHOLE TREE, AND THE SEAM IS NAMED. :func:`reach` maps a test to the
content address its result depends on. Today that is the whole-tree address for every test
(:data:`REACH_IS_WHOLE_TREE`): safe, because any change re-keys everything. The follow-up -- the
test file, its conftests, its static import closure and its declared data inputs -- replaces the body
of :func:`reach` and nothing else. Under-declared reach would serve a stale PASS, which is why it is
not guessed at here.

WHERE IT LIVES. ``output/verdicts/ledger.jsonl`` in the MAIN checkout of the repository -- resolved
through git's common directory, so every lane worktree reads and writes the same file. It is a store
read across days, so it is not under the dated ``output/logs/<yy>/<mm>/<dd>/`` tree that holds one
day's artefacts; the logs its entries cite stay there.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Final, Protocol, runtime_checkable

from lab_commons.dev.durations import PluginConfig
from lab_commons.dev.forge import _GIT
from lab_commons.dev.verdict import Outcome, Verdict

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

__all__ = [
    'LEDGER_REL',
    'LIVE_MARKERS',
    'OUTCOMES_DIR_VAR',
    'REACH_IS_WHOLE_TREE',
    'RECORDED',
    'Entry',
    'LedgerRefusal',
    'OutcomeRecorder',
    'OutcomeReport',
    'OutcomeSession',
    'entries',
    'ledger_path',
    'outcomes_dir',
    'reach',
    'read_outcomes',
    'record',
    'record_promoted',
    'run_test_id',
    'served',
]

#: The ledger, relative to the MAIN checkout's root.
LEDGER_REL: Final = 'output/verdicts/ledger.jsonl'

#: The only results the ledger holds. INCONCLUSIVE says nothing about the tree.
RECORDED: Final = frozenset(outcome.value.upper() for outcome in Outcome if outcome.settled)

#: Markers naming a test whose input includes a live external engine; the writer never records one.
LIVE_MARKERS: Final = frozenset({'live', 'heavy'})

#: The state of the :func:`reach` seam: ``True`` while every test reaches the whole tree.
REACH_IS_WHOLE_TREE: Final = True

_RUN_PREFIX: Final = 'run:'
_GIT_TIMEOUT_S: Final = 60


class LedgerRefusal(ValueError):
    """An entry the ledger must not hold -- recording it would serve a non-fact as a verdict."""


@dataclass(frozen=True, slots=True)
class Entry:
    """One recorded result: the key ``(tree, env, test)``, the result, and where it came from.

    ``tier`` names the runner tier that produced it; ``commit`` is HEAD when the tree was clean and
    unmoved across the run, else ``''`` (admission reads only entries that name a commit); ``log``
    is the evidence.
    """

    tree: str
    env: str
    test: str
    result: str
    tier: str
    commit: str
    log: str
    at: str = ''


def run_test_id(selector: str) -> str:
    """The ``test`` field of a whole-run entry: the selection, prefixed so no node id can collide."""
    return f'{_RUN_PREFIX}{selector}'


def reach(test: str, *, tree: str) -> str:
    """THE SEAM: the content address *test*'s result depends on. Today, the whole tree.

    The follow-up hashes the test file, its conftests, its import closure and its declared data
    instead; *test* is unused until then, and is in the signature so the callers do not move.
    """
    del test
    return tree


def ledger_path(root: Path) -> Path:
    """The ledger for the repository *root* belongs to, in its MAIN checkout (shared by every lane)."""
    common = subprocess.run(
        [_GIT, '-C', str(root), 'rev-parse', '--path-format=absolute', '--git-common-dir'],
        capture_output=True,
        text=True,
        encoding='utf-8',
        check=True,
        timeout=_GIT_TIMEOUT_S,
    ).stdout.strip()
    return Path(common).parent / LEDGER_REL


def record(path: Path, rows: Iterable[Entry]) -> None:
    """Append *rows* in one write. Refuses -- writing nothing -- any row whose result is not recordable."""
    stamped = [row if row.at else _stamped(row) for row in rows]
    bad = sorted({row.result for row in stamped} - RECORDED)
    if bad:
        msg = f'the ledger records only {sorted(RECORDED)}, not {bad}: INCONCLUSIVE is not a fact about a tree.'
        raise LedgerRefusal(msg)
    if not stamped:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    text = ''.join(json.dumps(asdict(row), sort_keys=True) + '\n' for row in stamped)
    with path.open('a', encoding='utf-8') as handle:
        handle.write(text)


def _stamped(row: Entry) -> Entry:
    values = asdict(row)
    values['at'] = datetime.now(UTC).isoformat(timespec='seconds')
    return Entry(**values)


def entries(path: Path) -> tuple[Entry, ...]:
    """Every entry in *path*, oldest first; an absent ledger is an empty one, a torn line is skipped."""
    try:
        lines = path.read_text(encoding='utf-8').splitlines()
    except FileNotFoundError:
        return ()
    out: list[Entry] = []
    for line in lines:
        try:
            out.append(Entry(**json.loads(line)))
        except (ValueError, TypeError):
            continue
    return tuple(out)


def served(path: Path, *, tree: str, env: str, test: str) -> Entry | None:
    """The newest entry for the key, or ``None`` when there is none or the key is FLAKY."""
    key = reach(test, tree=tree)
    matching = [row for row in entries(path) if (row.tree, row.env, row.test) == (key, env, test)]
    if not matching or {row.result for row in matching} == RECORDED:
        return None
    return matching[-1]


def record_promoted(path: Path, verdict: Verdict, tree: str, env: str, selector: str, *, commit: str) -> None:
    """THE ONE WRITER's entry point: a PROMOTED verdict's run entry plus every outcome it recorded.

    The caller has already checked the tree did not move during the run. An unsettled verdict
    records nothing; the per-test outcomes are read from :func:`outcomes_dir` beside its log.
    """
    if not verdict.result.outcome.settled:
        return
    evidence = f'{verdict.log.path}@{verdict.log.digest}'
    tier = selector.split(' ', 1)[0]

    def entry(test: str, result: str) -> Entry:
        return Entry(tree, env, test, result, tier=tier, commit=commit, log=evidence)

    outcomes = sorted(read_outcomes(outcomes_dir(verdict.log.path)).items())
    run = entry(run_test_id(selector), verdict.result.outcome.value.upper())
    record(path, [run, *(entry(test, result) for test, result in outcomes)])


def outcomes_dir(log: Path) -> Path:
    """Where one run's per-test outcomes are written: beside its log, named after it."""
    return log.with_suffix('.outcomes')


# -- the runner's half: which node ids passed or failed in THIS run -------------------------------

#: How a runner hands this run's outcome directory to the pytest it launches.
OUTCOMES_DIR_VAR: Final = 'LAB_COMMONS_OUTCOMES_DIR'

_OUTCOMES_STEM: Final = 'outcomes'


@runtime_checkable
class _WorkerConfig(Protocol):
    """The worker-only input pytest-xdist attaches to its config, absent on the controller."""

    workerinput: Mapping[str, str]


class OutcomeReport(Protocol):
    """EXACTLY the attributes :class:`OutcomeRecorder` reads off a runner's phase report."""

    nodeid: str
    when: str
    passed: bool
    failed: bool
    keywords: Mapping[str, object]


class OutcomeSession(Protocol):
    """A session, read for its config alone -- the shard id lives there."""

    config: object


@dataclass(eq=False)  # registered as a pytest plugin, which pytest hashes: identity, not value
class OutcomeRecorder:
    """Collect PASS/FAIL per node id over every phase, and write them once at session finish.

    FAIL if ANY phase failed (a broken teardown is a failed test); PASS if the call passed and nothing
    failed. A skip records nothing, and so does a test carrying a :data:`LIVE_MARKERS` keyword. One
    file per process (``outcomes[-<worker>].json``), merged by :func:`read_outcomes`. Nothing here
    imports pytest; a control drives it with plain objects.
    """

    directory: Path
    outcomes: dict[str, str] = field(default_factory=dict)
    live: set[str] = field(default_factory=set)

    def pytest_runtest_logreport(self, report: OutcomeReport) -> None:
        """Fold one phase report into its node id's outcome."""
        if LIVE_MARKERS & set(report.keywords):
            self.live.add(report.nodeid)
        if report.failed:
            self.outcomes[report.nodeid] = 'FAIL'
        elif report.when == 'call' and report.passed:
            self.outcomes.setdefault(report.nodeid, 'PASS')

    def pytest_sessionfinish(self, session: OutcomeSession) -> Path:
        """Write this process's outcomes, live tests removed."""
        config = session.config
        worker = config.workerinput.get('workerid') if isinstance(config, _WorkerConfig) else None
        kept = {node: result for node, result in self.outcomes.items() if node not in self.live}
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.directory / f'{_OUTCOMES_STEM}{f"-{worker}" if worker else ""}.json'
        path.write_text(json.dumps(kept, indent=1, sort_keys=True) + '\n', encoding='utf-8')
        return path


def read_outcomes(directory: Path) -> dict[str, str]:
    """Every outcome file in *directory*, merged; FAIL wins a node id two files disagree on."""
    merged: dict[str, str] = {}
    paths = sorted(directory.glob(f'{_OUTCOMES_STEM}*.json')) if directory.is_dir() else []
    for path in paths:
        for nodeid, result in dict(json.loads(path.read_text(encoding='utf-8'))).items():
            merged[nodeid] = 'FAIL' if 'FAIL' in (result, merged.get(nodeid)) else str(result)
    return merged


def pytest_configure(config: PluginConfig) -> None:
    """THE PLUGIN DOOR: ``pytest -p lab_commons.dev.verdictledger`` records outcomes when a runner asks.

    Inert unless :data:`OUTCOMES_DIR_VAR` names a directory, so loading the plugin outside a runner
    writes nothing.
    """
    directory = os.environ.get(OUTCOMES_DIR_VAR, '')
    if directory:
        config.pluginmanager.register(OutcomeRecorder(directory=Path(directory)), name='lab-commons-outcomes')
