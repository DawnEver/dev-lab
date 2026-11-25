"""COST IS DERIVED, NEVER DECLARED -- the measured ledger against THIS host's budget decides where a test runs.

User rulings 2026-11-24 (T3, superseded in part by H1). No repo keeps a heavy, not-heavy or big-memory list,
and no ``slow`` / ``heavy`` marker: a hand-kept cost is refused at collection (:data:`RETIRED_MARKERS`). The
cost of a test is what :func:`measured_seconds` reads -- ONE READER over the family's two measurements: this
host's own duration ledger (:mod:`dev_lab.dev.durations`, newest row per id) over the forge's learned table
(:func:`forge_seconds`, every host's cache of the forge's runs), so a test the forge measured is measured on a
workstation that never ran it. The budget is the
HOST's, declared once in the family instance -- the machine file's ``[test_budget]`` table, which the family
layer (:func:`lab_commons.config.section`) merges under it -- and dev-lab and the repos declare none::

    [test_budget]
    test_s = 600       # the longest one test may run on this host, seconds
    cores = 8          # what a test run may take of this host
    memory_gb = 24

:func:`plan` splits a selection: a test measured AT OR OVER ``test_s`` is HANDED (it does not fit this host;
the forge places it by its need markers and a host whose budget holds it), the rest run here. Each local test
carries a DEADLINE: a measured one :data:`DEADLINE_FACTOR` times its reading, never under
:data:`DEADLINE_FLOOR_S` nor over the budget; a NEVER-MEASURED one runs once with the budget as its deadline,
and that run is its measurement. A kill at the deadline is filed in the ledger at the deadline
(:func:`killed_at`, :func:`dev_lab.dev.durations.phase_seconds`) -- "cost >= deadline", a lower bound -- so the
next plan hands it as over budget.

LIMITS, STATED: the ledger holds seconds only, so a test's memory and cores are not per-test facts here; the
box admits the run as a whole against ``cores``/``memory_gb`` (:mod:`dev_lab.dev.verifybox`). A host with no
``[test_budget]`` plans nothing (every test runs here, under the repo's ``timeout``) and says so in one line.
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

import pytest

__all__ = [
    'BUDGET_KEYS',
    'BUDGET_TABLE',
    'DEADLINE_FACTOR',
    'DEADLINE_FLOOR_S',
    'KILL_GRACE_S',
    'RETIRED_MARKERS',
    'Budget',
    'Plan',
    'beyond_budget',
    'budget_defects',
    'budget_of',
    'forge_seconds',
    'killed_at',
    'measured_seconds',
    'origin_of',
    'part_costs',
    'plan',
    'read_budget',
    'refuse_cost_markers',
    'schedule',
]

#: The machine-file table (family layer merged under it) declaring this host's test budget.
BUDGET_TABLE: Final = 'test_budget'
#: Every key ``[test_budget]`` declares: its kind and its unit -- each a positive number, none optional.
BUDGET_KEYS: Final = {'test_s': (float, 'seconds'), 'cores': (int, 'cores'), 'memory_gb': (float, 'GB')}
#: A measured test's deadline is this many times its newest reading (dimensionless): a box under load runs
#: slower than the box that measured it, and three times is the margin before a hang is called a hang.
DEADLINE_FACTOR: Final = 3.0
#: The shortest deadline a measured test gets, in seconds: a 10 ms test's 30 ms would fire on scheduling noise.
DEADLINE_FLOOR_S: Final = 10.0
#: Seconds the per-test timeout fires AFTER the deadline: the ledger's deadline watchdog
#: (:meth:`dev_lab.dev.durations.Recorder.pytest_runtest_logstart`) writes "cost >= deadline" first, since on
#: Windows without workers the timeout ends the whole process and nothing after it runs.
KILL_GRACE_S: Final = 5.0
#: RETIRED-NAMES-REGISTERED: the hand-kept cost markers (T3, 2026-11-24), refused at collection by name.
RETIRED_MARKERS: Final = ('slow', 'heavy', 'big_memory')


@dataclass(frozen=True)
class Budget:
    """What one host gives one test (*test_s*, seconds) and a test run (*cores*, *memory_gb*)."""

    test_s: float
    cores: int
    memory_gb: float


def _defect(table: Mapping[str, Any], key: str) -> str:
    """Why *key* of *table* is no positive number of its kind (:data:`BUDGET_KEYS`); ``''`` when it is one."""
    kind, unit = BUDGET_KEYS[key]
    value = table.get(key)
    if isinstance(value, bool) or not isinstance(value, kind | int) or value <= 0:
        return f'[{BUDGET_TABLE}] {key} = {value!r}: a positive {kind.__name__}, in {unit} (dev_lab.dev.testcost)'
    return ''


def budget_defects(table: object) -> list[str]:
    """Every refusal of a ``[test_budget]`` table, each naming its key; ``[]`` for a sound or an empty one.

    The one schema of the table: :func:`budget_of` refuses with it on the host, ``configcheck`` in the config source.
    """
    if not isinstance(table, Mapping):
        return [f'[{BUDGET_TABLE}] must be a table of {", ".join(BUDGET_KEYS)} (dev_lab.dev.testcost)']
    if not table:
        return []
    declared = ', '.join(BUDGET_KEYS)
    found = [
        f'[{BUDGET_TABLE}] {key} is not a declared key: the table declares {declared} (dev_lab.dev.testcost)'
        for key in table
        if key not in BUDGET_KEYS
    ]
    return found + [why for key in BUDGET_KEYS if (why := _defect(table, key))]


def budget_of(table: Mapping[str, Any]) -> Budget | None:
    """The :class:`Budget` *table* declares; ``None`` when it declares none; a malformed table is refused by name."""
    if found := budget_defects(table):
        raise ValueError('; '.join(found))
    if not table:
        return None
    return Budget(test_s=float(table['test_s']), cores=int(table['cores']), memory_gb=float(table['memory_gb']))


def read_budget(section: Callable[[str], Mapping[str, Any]] | None = None) -> Budget | None:
    """The running host's budget, through the family layer (:func:`lab_commons.config.section`)."""
    if section is None:
        from lab_commons.config import section  # noqa: PLC0415 -- the machine file is read only when planning

    return budget_of(section(BUDGET_TABLE))


@dataclass(frozen=True)
class Plan:
    """A selection split: what runs *local*, what is *handed*, each local test's deadline, and the never-measured."""

    local: tuple[str, ...]
    handed: tuple[str, ...]
    deadlines: dict[str, float] = field(default_factory=dict)
    unmeasured: tuple[str, ...] = ()


def killed_at(deadline_s: float) -> float:
    """The seconds the ledger files for a test killed at *deadline_s*: the deadline itself, a lower bound."""
    return deadline_s


def plan(nodeids: Iterable[str], seconds: Mapping[str, float], budget: Budget) -> Plan:
    """Split *nodeids* by their measured *seconds* against *budget* (module docstring)."""
    local, handed, unmeasured, deadlines = [], [], [], {}
    for nodeid in nodeids:
        cost = seconds.get(nodeid)
        if cost is None:
            local.append(nodeid)
            unmeasured.append(nodeid)
            deadlines[nodeid] = budget.test_s
        elif cost >= budget.test_s:
            handed.append(nodeid)
        else:
            local.append(nodeid)
            deadlines[nodeid] = min(budget.test_s, max(DEADLINE_FLOOR_S, DEADLINE_FACTOR * cost))
    return Plan(tuple(local), tuple(handed), deadlines, tuple(unmeasured))


def refuse_cost_markers(items: list[pytest.Item]) -> None:
    """Refuse the session when a test carries a hand-kept cost marker (:data:`RETIRED_MARKERS`), naming each."""
    refused = [
        f'{item.nodeid}: @pytest.mark.{name} is retired 2026-11-24 (T3) -- cost is measured, not declared '
        f'(dev_lab.dev.testcost); delete the marker'
        for item in items
        for name in RETIRED_MARKERS
        if item.get_closest_marker(name) is not None
    ]
    if refused:
        raise pytest.UsageError('\n'.join(refused))


def forge_seconds(repo_url: str) -> dict[str, float]:
    """The forge's measured seconds per test id of *repo_url* (:func:`lab_commons.compute.learned.learned`).

    A finished id is its duration; an id that never finished is its FLOOR -- "cost >= floor", the time it ran
    before its item was killed (:mod:`lab_commons.compute.measured`) -- so a test the forge killed is never free.
    """
    from lab_commons.compute import learned  # noqa: PLC0415 -- read only when a budget plans or the forge places
    from lab_commons.compute.measured import Measured  # noqa: PLC0415

    measured = Measured.of(dict(learned.learned(repo_url)))
    seconds = {node: float(value) for node, value in measured.floors.items()}
    for node, value in measured.durations.items():
        seconds[node] = max(float(value), seconds.get(node, 0.0))
    return seconds


def origin_of(root: Path) -> str | None:
    """The forge origin the learned table of *root* is keyed by; ``None`` for a tree with no forge remote."""
    from dev_lab.dev.forge import UnreadableRemote  # noqa: PLC0415 -- deferred like every plugin import
    from dev_lab.dev.platformparts import origin_url  # noqa: PLC0415

    try:
        return origin_url(root)
    except UnreadableRemote:
        return None


def measured_seconds(root: Path, repo_url: str | None) -> dict[str, float]:
    """THE ONE READER of a test's cost here: the forge's reading of *repo_url*, overlaid by *root*'s own ledger.

    This host's newest reading of an id wins it -- it is this box, and newest wins (user directive 2026-10-05);
    an id only the forge measured is priced by the forge; ``None`` for *repo_url* reads the ledger alone.
    """
    from dev_lab.dev import durations  # noqa: PLC0415 -- deferred like every plugin import (pytest_family)
    from dev_lab.dev.datedlog import UndeclaredOutput  # noqa: PLC0415

    seconds = forge_seconds(repo_url) if repo_url else {}
    with contextlib.suppress(UndeclaredOutput):  # a tree with no output root has no ledger of its own
        seconds.update(durations.read(root).seconds)
    return seconds


def schedule(config: pytest.Config, items: list[pytest.Item], *, budget: Budget | None) -> Plan | None:
    """Apply :func:`plan` to the collected *items*: deselect the handed, give each local test its deadline."""
    if budget is None:
        return None
    root = config.rootpath
    planned = plan([item.nodeid for item in items], measured_seconds(root, origin_of(root)), budget)
    handed = set(planned.handed)
    if handed:
        config.hook.pytest_deselected(items=[item for item in items if item.nodeid in handed])
        items[:] = [item for item in items if item.nodeid not in handed]
        reporter = config.pluginmanager.get_plugin('terminalreporter')
        if reporter is not None:
            reporter.write_line(
                f'testcost: {len(handed)} test(s) measured over this host budget '
                f'({budget.test_s:g} s) are handed to the forge: {", ".join(sorted(handed))}'
            )
    recorder = config.pluginmanager.get_plugin('lab-commons-durations')
    for item in items:
        if item.get_closest_marker('timeout') is None:
            item.add_marker(pytest.mark.timeout(planned.deadlines[item.nodeid] + KILL_GRACE_S))
    if recorder is not None:
        recorder.deadlines.update(planned.deadlines)
    return planned


def beyond_budget(part_ids_seconds: Mapping[str, float], budget: Budget | None, *, part: str) -> str:
    """FORGE PLACEMENT (H1): why THIS host must not claim *part*, ``''`` when its budget holds every measured test.

    *part_ids_seconds* is the part's measured cost per test id (the learned table,
    :func:`lab_commons.compute.learned.learned`). A part holding a test measured at or over this host's ``test_s``
    would run here incomplete (:func:`schedule` hands that test), so it is left for a host whose budget fits it.
    No declared budget places nothing here by cost.
    """
    if budget is None or not part_ids_seconds:
        return ''
    dear, seconds = max(part_ids_seconds.items(), key=lambda row: row[1])
    if seconds < budget.test_s:
        return ''
    return (
        f'over this host test budget: {part} holds {dear}, measured {seconds:g} s >= [{BUDGET_TABLE}] test_s '
        f'{budget.test_s:g} s -- a host whose budget fits it claims it'
    )


def part_costs(repo_url: str, part: str) -> dict[str, float]:
    """The measured seconds of *part*'s test ids (:func:`forge_seconds`): the ids in the files the part last ran."""
    from lab_commons.compute import learned  # noqa: PLC0415 -- read by the forge pass only

    from dev_lab.dev.partrows import needs_of_row  # noqa: PLC0415

    files = set(learned.part_files(repo_url, needs_of_row(part)))
    return {node: value for node, value in forge_seconds(repo_url).items() if node.split('::', 1)[0] in files}
