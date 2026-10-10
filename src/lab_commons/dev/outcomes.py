"""PER-TEST OUTCOMES of one local run, in the RUN RECORD's vocabulary -- a pytest plugin a runner loads.

``pytest -p lab_commons.dev.outcomes`` with :data:`OUTCOMES_DIR_VAR` naming a directory writes, per
process, ``outcomes[-<worker>].json``: node id -> ``passed`` | ``failed`` | ``skipped`` | ``xfailed``,
the words a run record (:mod:`lab_commons.hpc.records`) uses, so a local run's record and a cluster
run's record are one shape and post as one kind of part (:mod:`lab_commons.dev.platformparts`). Skip
reasons are written beside them (``reasons[-<worker>].json``). Inert without the variable.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Final, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Mapping

    from lab_commons.dev.durations import PluginConfig

__all__ = [
    'OUTCOMES_DIR_VAR',
    'OutcomeRecorder',
    'OutcomeReport',
    'OutcomeSession',
    'outcomes_dir',
    'read_outcomes',
    'read_reasons',
]

#: How a runner hands this run's outcome directory to the pytest it launches.
OUTCOMES_DIR_VAR: Final = 'LAB_COMMONS_OUTCOMES_DIR'

_OUTCOMES_STEM: Final = 'outcomes'
_REASONS_STEM: Final = 'reasons'

#: When two processes disagree on one id, the worse word wins.
_RANK: Final = {'passed': 0, 'xfailed': 1, 'skipped': 2, 'failed': 3}


def outcomes_dir(log: Path) -> Path:
    """Where one run's per-test outcomes are written: beside its log, named after it."""
    return log.with_suffix('.outcomes')


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
    skipped: bool
    longrepr: object


class OutcomeSession(Protocol):
    """A session, read for its config alone -- the shard id lives there."""

    config: object


def _skip_reason(report: OutcomeReport) -> str:
    longrepr = report.longrepr
    if isinstance(longrepr, tuple):  # pytest's (path, line, reason)
        return str(longrepr[-1]).removeprefix('Skipped: ')
    return str(longrepr or '')


@dataclass(eq=False)  # registered as a pytest plugin, which pytest hashes: identity, not value
class OutcomeRecorder:
    """Fold every phase report into one word per node id, and write them once at session finish.

    ``failed`` if ANY phase failed (a broken teardown is a failed test); ``xfailed`` for an expected
    failure; ``skipped`` (with its reason) for a skip; ``passed`` when the call passed. Nothing here
    imports pytest; a control drives it with plain objects.
    """

    directory: Path
    outcomes: dict[str, str] = field(default_factory=dict)
    reasons: dict[str, str] = field(default_factory=dict)

    def pytest_runtest_logreport(self, report: OutcomeReport) -> None:
        """Fold one phase report into its node id's outcome."""
        node = report.nodeid
        if report.failed:
            self.outcomes[node] = 'failed'
        elif report.skipped:
            # a skip carries pytest's (path, line, reason) tuple; an xfail carries the failure it expected
            if not isinstance(report.longrepr, tuple):
                self.outcomes.setdefault(node, 'xfailed')
            else:
                self.outcomes.setdefault(node, 'skipped')
                self.reasons[node] = _skip_reason(report)
        elif report.when == 'call' and report.passed:
            self.outcomes.setdefault(node, 'passed')

    def pytest_sessionfinish(self, session: OutcomeSession) -> Path:
        """Write this process's outcomes and skip reasons."""
        config = session.config
        worker = config.workerinput.get('workerid') if isinstance(config, _WorkerConfig) else None
        suffix = f'-{worker}' if worker else ''
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.directory / f'{_OUTCOMES_STEM}{suffix}.json'
        path.write_text(json.dumps(self.outcomes, indent=1, sort_keys=True) + '\n', encoding='utf-8')
        reasons = self.directory / f'{_REASONS_STEM}{suffix}.json'
        reasons.write_text(json.dumps(self.reasons, indent=1, sort_keys=True) + '\n', encoding='utf-8')
        return path


def _merged(directory: Path, stem: str) -> list[dict[str, str]]:
    paths = sorted(directory.glob(f'{stem}*.json')) if directory.is_dir() else []
    return [dict(json.loads(path.read_text(encoding='utf-8'))) for path in paths]


def read_outcomes(directory: Path) -> dict[str, str]:
    """Every outcome file in *directory*, merged; the worse word wins an id two files disagree on."""
    merged: dict[str, str] = {}
    for found in _merged(directory, _OUTCOMES_STEM):
        for node, word in found.items():
            if node not in merged or _RANK.get(word, 0) > _RANK.get(merged[node], 0):
                merged[node] = str(word)
    return merged


def read_reasons(directory: Path) -> dict[str, str]:
    """Every skip reason in *directory*, merged."""
    merged: dict[str, str] = {}
    for found in _merged(directory, _REASONS_STEM):
        merged.update(found)
    return merged


def pytest_configure(config: PluginConfig) -> None:
    """THE PLUGIN DOOR: inert unless :data:`OUTCOMES_DIR_VAR` names a directory."""
    directory = os.environ.get(OUTCOMES_DIR_VAR, '')
    if directory:
        config.pluginmanager.register(OutcomeRecorder(directory=Path(directory)), name='lab-commons-outcomes')
