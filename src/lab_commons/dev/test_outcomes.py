"""PER-TEST CELLS of one local run -- a pytest plugin a runner loads (``-p lab_commons.dev.test_outcomes``).

With :data:`OUTCOMES_DIR_VAR` naming a directory, every pytest process (an xdist worker, the controller)
appends to its OWN :class:`~lab_commons.outcomes.Record`, ``cells[-<worker>].jsonl``: per node id one
``outcome`` event carrying the test's :class:`~lab_commons.outcomes.Cell` and declared
:class:`~lab_commons.outcomes.Expectation`, by THE pytest mapping (:func:`lab_commons.hpc.pytest_item.judged`,
the one a cluster item uses too), written when the test's last phase reports. So a local run and a cluster
run are one shape and post as one kind of part (:mod:`lab_commons.dev.platformparts`). Inert without the
variable.

A SINGLE RUN'S CONCLUSION IS DECIDED. A node decided both ways in one run (a rerun plugin, two processes)
is never overwritten: the Record's finality refuses the second decision, a ``flaky`` event is recorded
instead (:data:`lab_commons.hpc.testcells.FLAKY`), and :func:`read_cells` reports the id flaky, which makes
the run INCONCLUSIVE (:func:`lab_commons.hpc.testcells.conclude`).

A directory the retired plugin wrote (``outcomes*.json`` words) is refused by name: it is regenerable --
re-run the verify.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, Protocol, runtime_checkable

from lab_commons.dev.durations import PluginConfig
from lab_commons.hpc.pytest_item import NOT_APPLICABLE_LINE, badness, declared_resources, judged
from lab_commons.hpc.testcells import FLAKY, TestCell, merged
from lab_commons.outcomes import OUTCOME, Event, FinalityError, Record

if TYPE_CHECKING:
    from collections.abc import Mapping


__all__ = ['OUTCOMES_DIR_VAR', 'CellRecorder', 'RetiredOutcomes', 'outcomes_dir', 'read_cells']

#: How a runner hands this run's directory to the pytest it launches.
OUTCOMES_DIR_VAR: Final = 'LAB_COMMONS_OUTCOMES_DIR'

_STEM: Final = 'cells'

#: The file stem the retired plugin wrote its words under.
_RETIRED_STEM: Final = 'outcomes'


class RetiredOutcomes(ValueError):
    """A run directory of the retired word files: regenerable, so refused -- re-run."""


def outcomes_dir(log: Path) -> Path:
    """Where one run's per-test cells are written: beside its log, named after it."""
    return log.with_suffix('.outcomes')


@runtime_checkable
class _WorkerConfig(Protocol):
    """The worker-only input pytest-xdist attaches to its config, absent on the controller."""

    workerinput: Mapping[str, str]


class CellReport(Protocol):
    """EXACTLY the attributes the mapping reads off a runner's phase report."""

    nodeid: str
    when: str
    outcome: str
    duration: float
    longrepr: object
    keywords: Mapping[str, object]


@dataclass(eq=False)  # registered as a pytest plugin, which pytest hashes: identity, not value
class CellRecorder:
    """Fold each node's phase reports into its worst one; append it to *path*'s Record at teardown.

    Nothing here imports pytest; a control drives it with plain objects.
    """

    path: Path
    resources: frozenset[str] = frozenset()
    _worst: dict[str, dict[str, Any]] = field(default_factory=dict)
    _record: Record | None = None

    def pytest_runtest_logreport(self, report: CellReport) -> None:
        """Fold one phase report; at its teardown, record the node's cell."""
        plain = judged(report, self.resources)
        held = self._worst.get(report.nodeid)
        if plain is not None and (held is None or badness(plain) < badness(held)):
            self._worst[report.nodeid] = plain
        if report.when == 'teardown' and report.nodeid in self._worst:
            self.record(report.nodeid, TestCell.from_plain(self._worst.pop(report.nodeid)))

    def record(self, node: str, one: TestCell) -> None:
        """Append *node*'s cell; a second, different decision is a ``flaky`` event, never an overwrite."""
        if self._record is None:
            self._record = Record(self.path)
        try:
            self._record.outcome(node, one.cell, expectation=one.expectation)
        except FinalityError as why:
            self._record.append(Event(FLAKY, node, data={'cell': one.cell.to_plain(), 'why': str(why)}))


def read_cells(directory: Path) -> tuple[dict[str, TestCell], frozenset[str]]:
    """``(cells, flaky ids)`` over every process's Record in *directory*; absent reads as none.

    Raises:
        RetiredOutcomes: *directory* holds the retired word files.

    """
    if not directory.is_dir():
        return {}, frozenset()
    retired = sorted(p.name for p in directory.glob(f'{_RETIRED_STEM}*.json'))
    if retired:
        msg = (
            f'{directory} holds the retired per-test word files ({", ".join(retired)}); they are regenerable, '
            'so they are refused, never upgraded -- re-run the verify'
        )
        raise RetiredOutcomes(msg)
    sources: list[dict[str, TestCell]] = []
    flaky: set[str] = set()
    for path in sorted(directory.glob(f'{_STEM}*.jsonl')):
        cells: dict[str, TestCell] = {}
        for event in Record(path).replay():
            if event.kind == OUTCOME and event.cell is not None:
                cells[event.key] = TestCell(event.cell, event.expectation)
            elif event.kind == FLAKY:
                flaky.add(event.key)
        sources.append(cells)
    cells, disagreed = merged(sources)
    return cells, frozenset(flaky | disagreed)


class _Config(PluginConfig, Protocol):
    """What the plugin door reads of pytest's ``Config``: its root, plugin manager and ini lines."""

    def addinivalue_line(self, name: str, line: str) -> None:
        """Append *line* to the ini value *name*."""


def pytest_configure(config: _Config) -> None:
    """THE PLUGIN DOOR: inert unless :data:`OUTCOMES_DIR_VAR` names a directory."""
    config.addinivalue_line('markers', NOT_APPLICABLE_LINE)
    directory = os.environ.get(OUTCOMES_DIR_VAR, '')
    if not directory:
        return
    worker = config.workerinput.get('workerid') if isinstance(config, _WorkerConfig) else None
    path = Path(directory) / f'{_STEM}{f"-{worker}" if worker else ""}.jsonl'
    resources = declared_resources(Path(config.rootpath) / 'pyproject.toml')
    config.pluginmanager.register(CellRecorder(path, resources), name='lab-commons-test-outcomes')
