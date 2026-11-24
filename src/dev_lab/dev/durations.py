"""THE LEDGER THE WALL WRITES -- every test's measured cost, the ONE source test cost is derived from.

WHY THIS IS FAMILY. ``pytest.mark.slow`` was a hand-maintained set and on 2026-09-19 it cost consumer-b a
full day: an UNMARKED test ran twenty-nine minutes inside a narrowed tier and was killed by hand. The
marker set and the two readings that ratcheted it (``unmarked_but_slow``, ``marked_but_fast``) are RETIRED
(user ruling 2026-11-24, T3/H1): cost is no longer declared at all. The runner records every test's
wall-clock cost ONCE, from the report it already has, and :mod:`dev_lab.dev.testcost` derives what is
heavy -- and each test's deadline -- from these rows against the host's declared budget.

THE UNIT IS THE NODEID: a row is one test's summed setup, call and teardown seconds; :func:`module_of`
folds a nodeid to its file for a reader that reports per module.

THE DEFECT THE MECHANISM'S FIRST RUN FOUND, AND IT REFUTES THE MECHANISM IN ITS OWN DATA. When the
wall fires under ``-n``, the worker is GONE, so the controller files the crash against the nodeid
with a duration of ~0.0 -- and the tests the wall had just convicted enter the ledger as the FASTEST
things in the suite. A naive durations guard ACQUITS EXACTLY WHAT THE WALL CATCHES.
:func:`phase_seconds` is the arm that refuses it: a report whose text carries
:data:`CRASH_MARKER` is filed at AT LEAST the live wall, because a killed test held the box for at
least that long. It is a LOWER BOUND WRITTEN DOWN AS THE NUMBER, which is the difference between a
floor and a fabricated measurement -- the true duration is unknowable, because the process that knew
it died. MEASURED in this family's own installed toolchain rather than remembered: ``xdist`` 3.8.0
writes that sentence at ``xdist/dsession.py:436``, and
:func:`assert_the_crash_marker_is_what_the_scheduler_writes` re-reads it -- from source THE CONSUMER
hands over, because this layer is stdlib plus tier 1 and never imports a scheduler -- so a rename
reds instead of going silent.

THE WALL IS NOT PER-TEST ON EVERY PLATFORM, AND THIS MODULE WILL BE CONSUMED ON THREE.
``pytest-timeout`` raises inside the test only where ``SIGALRM`` exists; ``hasattr(signal,
'SIGALRM')`` is **False** on Windows (measured 2026-09-19, CPython 3.12 on win32), so
``timeout_method = "thread"`` is the only method available there and its timer ends in
``os._exit(1)`` (``pytest_timeout`` 2.4.0, line 542, and its own module docstring says so). THE
WHOLE SESSION DIES -- a stack dump naming the test, no summary, no verdict line, no exit through
pytest at all. So on Windows a wall alone converts a wedge into an abrupt process death, and what
makes it RECOVERABLE is SHARDING: under ``-n`` the process the wall kills is a WORKER, xdist reports
the crash against the test and restarts it, and the session survives to a verdict. Every verdict
consumer-b got on 2026-09-19 required ``-n 4``. "Run it sharded" is therefore not a performance
preference for a consumer of this module; it is the condition under which the ledger gets written at
all, and a reader who assumes otherwise is surprised exactly once, at the worst moment.

WHAT A LEDGER CANNOT SEE, stated rather than left to be discovered. It holds the tests that RAN, so
a narrowed selection records nothing about the tests it deselected -- which is why :func:`write` records
the SELECTOR beside the rows. A duration measured on a loaded box is also not a property of the test,
which is why :mod:`dev_lab.dev.testcost` keeps the newest reading per test rather than a band.
"""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Final, NamedTuple, Protocol, runtime_checkable

from lab_commons.compute.durable import durable_text

from dev_lab.dev import floors
from dev_lab.dev.datedlog import declared_output, output_dir

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

#: RETIRED-NAMES-REGISTERED (user ruling 2026-11-24, T3/H1): the hand-kept ``slow`` marker ratchet, refused
#: by name with what replaced it -- no alias survives.
_RETIRED_NAMES: Final = (
    'SLOW', 'FAST', 'NO_DATA', 'Finding', 'over', 'unmarked_but_slow', 'marked_but_fast', 'unmeasured',
    'assert_the_readings_still_convict',
)  # fmt: skip
RETIRED: Final = dict.fromkeys(
    _RETIRED_NAMES, 'retired 2026-11-24 (T3/H1): cost is derived from the ledger -- dev_lab.dev.testcost'
)


def __getattr__(name: str) -> object:
    """A retired name is refused BY NAME with its replacement (:data:`RETIRED`)."""
    if name in RETIRED:
        msg = f'dev_lab.dev.durations.{name} is {RETIRED[name]}'
        raise AttributeError(msg)
    msg = f'module {__name__!r} has no attribute {name!r}'
    raise AttributeError(msg)


__all__ = [
    'CRASH_MARKER',
    'LEDGER_ENV_VAR',
    'LEDGER_KIND',
    'LEDGER_TREE_VAR',
    'MEASURE_DOOR',
    'RETIRED',
    'Ledger',
    'LedgerInconclusive',
    'PhaseReport',
    'PluginConfig',
    'PluginManager',
    'Recorder',
    'Row',
    'RunConfig',
    'RunSession',
    'assert_the_crash_marker_is_what_the_scheduler_writes',
    'assert_the_ledger_is_evidence',
    'ledger_path',
    'module_of',
    'phase_seconds',
    'pytest_configure',
    'read',
    'write',
]

#: The output-tree kind the ledger lives under: ``<output>/<yy>/<mm>/<dd>/durations/``
#: (:func:`dev_lab.dev.datedlog.output_dir`), dated like the verify logs it is evidence beside.
LEDGER_KIND: Final = 'durations'

#: One file per pytest process; :func:`read` merges them. See the docstring on sharding.
_STEM: Final = 'durations'
#: The last stamp this process wrote: Windows' ``time_ns`` can repeat across two writes, and a tie let the older
#: reading win (:func:`read` keeps the strictly newer one).
_LAST_NS = [0]

#: THE SENTENCE THE SCHEDULER WRITES WHEN A WORKER DIES MID-TEST, and the whole reason this module
#: does not trust a reported duration. Spelled here as the SUBSTRING that survives the ``!r``
#: quoting of a worker id and a nodeid around it, and re-read off the installed scheduler by
#: :func:`assert_the_crash_marker_is_what_the_scheduler_writes` so a rename reds rather than
#: silently restoring the acquit-what-the-wall-caught defect.
CRASH_MARKER: Final = 'crashed while running'


#: The door that takes a reading -- every verify run records the tests it executes.
MEASURE_DOOR: Final = 'python -m dev_lab.dev.verify --'

#: How :mod:`dev_lab.dev.verify` hands the tree and env it measures to the pytest it launches,
#: so every reading carries what it was taken on.
LEDGER_TREE_VAR: Final = 'LAB_COMMONS_LEDGER_TREE'
LEDGER_ENV_VAR: Final = 'LAB_COMMONS_LEDGER_ENV'


class LedgerInconclusive(AssertionError):
    """A reading could not be taken at all, which is not the same fact as a reading that was clean."""


class PhaseReport(Protocol):
    """EXACTLY the four attributes :class:`Recorder` reads off a runner's report, and no more.

    STRUCTURAL AND NOT ``Any``, deliberately. ``Any`` here would be a waiver saying "a pytest thing
    goes in", which is a declaration that says nothing and cannot be checked; this says WHICH four
    fields the module depends on, so a runner that renames one is a type error rather than an
    ``AttributeError`` at session finish. It is also what keeps the kit stdlib-plus-tier-1: nothing
    here imports pytest, and a control drives these methods with a plain object.
    """

    nodeid: str
    duration: float
    failed: bool
    longrepr: object


class RunConfig(Protocol):
    """The two questions :class:`Recorder` asks a runner's config: the wall, and what was selected."""

    def getini(self, name: str) -> object:
        """The declared ini value for *name*, raising ``ValueError`` for an unregistered key."""

    def getoption(self, name: str) -> object:
        """The command-line option *name*, or a falsy value if it was not given."""


@runtime_checkable
class _WorkerConfig(Protocol):
    """The worker-only input pytest-xdist attaches to its config, absent on the controller."""

    workerinput: Mapping[str, str]


class PluginManager(Protocol):
    """The one call :func:`pytest_configure` makes on a runner's plugin manager."""

    def register(self, plugin: object, name: str) -> object:
        """Register *plugin* under *name*."""


class PluginConfig(Protocol):
    """A runner's config, read by the plugin door for its root and its plugin manager."""

    rootpath: Path
    pluginmanager: PluginManager


class RunSession(Protocol):
    """A session, read for its config alone -- the shard id lives there and not on the session."""

    config: RunConfig


class Row(NamedTuple):
    """One test's wall-clock cost, in seconds, as the runner measured it."""

    nodeid: str
    seconds: float


class Ledger(NamedTuple):
    """Every row a run recorded, plus WHAT THE RUN SELECTED -- the half a bare mapping loses."""

    selector: str
    seconds: dict[str, float]


def ledger_path(root: Path, *, worker: str | None = None) -> Path:
    """Where one process's rows live TODAY: ``<output>/<yy>/<mm>/<dd>/durations/durations[-<worker>].json``."""
    suffix = f'-{worker}' if worker else ''
    return output_dir(Path(root), LEDGER_KIND) / f'{_STEM}{suffix}.json'


def module_of(nodeid: str) -> str:
    """The test file a nodeid names, spelled the way a corpus spells a path (forward slashes)."""
    return nodeid.split('::', 1)[0].replace(os.sep, '/').replace('\\', '/')


def phase_seconds(*, duration: float, failed: bool, longrepr: str, wall: float) -> float:
    """What one report is worth in seconds, with A KILLED TEST FILED AT THE WALL rather than at zero.

    THE ARM THIS FUNCTION EXISTS FOR. A worker the wall killed is gone, so the controller files its
    crash at ~0.0s, and the tests the wall just convicted would enter the ledger as the fastest in
    the suite -- the mechanism acquitting exactly what it was built to learn from. A killed test held
    the box for AT LEAST *wall*, so *wall* is what it is recorded at.

    ``max`` and not an assignment, so a crash that somehow reports a LONGER duration keeps it: the
    wall is a lower bound on a killed test, never a statement that the number is the wall.

    Args:
        duration: the phase duration the runner reported.
        failed: whether the report is a failure -- a crash is only ever read out of a failed one.
        longrepr: the report's representation, as TEXT. The only place the scheduler says a worker
            died; a crash carries no structured field to key on.
        wall: the live per-test wall, in seconds, as the RUNNER is enforcing it. NO DEFAULT: a
            second spelling of the wall is a second thing to keep in step, and this module has no
            business holding an opinion about the number.

    Returns:
        The seconds to record for this report.

    """
    if failed and CRASH_MARKER in longrepr:
        return max(float(duration), float(wall))
    return float(duration)


def write(
    root: Path,
    rows: Iterable[Row],
    *,
    selector: str,
    worker: str | None = None,
    tree: str = '',
    env: str = '',
) -> Path:
    """Record *rows* for ONE process, MERGED by nodeid into what THAT process's file held, NEWEST WINS.

    MERGED RATHER THAN OVERWRITTEN, and the reason is a defect measured on this mechanism's first
    run. A ledger describing exactly one run sounds right and is not: a TARGETED run -- one file,
    thirteen tests -- would replace a full run's ledger with thirteen rows, and the consumer's floor
    would then red on the next full run for a reason with nothing to do with the suite. EVERY
    NARROW RUN A DEVELOPER MAKES WOULD BREAK THE GUARD.

    NEWEST WINS PER NODEID (user directive 2026-10-05), replacing an earlier keep-the-max merge: a
    max never forgets, so a test made fast stayed slow in the ledger until someone deleted it. Each
    row is stamped with WHEN it was taken and the ``tree``/``env`` it was taken on, so a reader can
    tell which run a reading came from and :func:`read` picks the newest across worker files.

    THE MERGE IS WITH THIS PROCESS'S OWN FILE AND NOT WITH EVERY FILE IN THE DIRECTORY. A worker
    folding its siblings' rows into its own file would leave four files each claiming to have
    measured everything, which misleads anyone reading one file to find out what one worker did.

    Args:
        root: the checkout whose declared output tree holds the ledger.
        rows: this process's measurements.
        selector: what the run SELECTED, recorded because rows mean nothing without it.
        worker: the shard id, or ``None`` for an unsharded run.
        tree: the content address verify is measuring, or ``''`` outside verify.
        env: the env key verify is measuring under, or ``''`` outside verify.

    Returns:
        The path written.

    """
    path = ledger_path(root, worker=worker)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.loads(path.read_text(encoding='utf-8')) if path.is_file() else {}
    merged = {nodeid: float(value) for nodeid, value in dict(payload.get('seconds', {})).items()}
    provenance = dict(payload.get('provenance', {}))
    now = _LAST_NS[0] = max(time.time_ns(), _LAST_NS[0] + 1)
    for row in rows:
        merged[row.nodeid] = round(float(row.seconds), 3)
        provenance[row.nodeid] = {'at_ns': now, 'tree': tree, 'env': env}
    payload = {'selector': selector, 'seconds': merged, 'provenance': provenance}
    return durable_text(path, json.dumps(payload, indent=2, sort_keys=True) + '\n')


def read(root: Path) -> Ledger:
    """EVERY ledger file under *root*'s output tree, EVERY DAY, merged by nodeid, NEWEST WINS. Absent is EMPTY.

    Emptiness is not judged here on purpose: "no ledger" and "a ledger of nothing" are the same fact,
    and :func:`assert_the_ledger_is_evidence` reports it as no data against the repo's floor.
    A row with no recorded time (a ledger written before readings were stamped) counts as oldest.
    """
    base = Path(root) / declared_output(Path(root))
    newest: dict[str, tuple[int, float]] = {}
    selectors: list[str] = []
    paths = sorted(base.glob(f'*/*/*/{LEDGER_KIND}/{_STEM}*.json'))
    for path in paths:
        payload = json.loads(path.read_text(encoding='utf-8'))
        selectors.append(str(payload.get('selector', '')))
        provenance = dict(payload.get('provenance', {}))
        for nodeid, seconds in dict(payload.get('seconds', {})).items():
            at = int(dict(provenance.get(nodeid, {})).get('at_ns', 0))
            if nodeid not in newest or at > newest[nodeid][0]:
                newest[nodeid] = (at, float(seconds))
    merged = {nodeid: seconds for nodeid, (_, seconds) in newest.items()}
    return Ledger(selector=' | '.join(sorted(set(selectors))), seconds=merged)


def assert_the_ledger_is_evidence(*, ledger: Ledger, floor: int, headroom: int, what: str) -> str:
    """THE FLOOR, BOTH SIDES -- and a ledger UNDER the floor is NO DATA, reported rather than failed.

    THE LEDGER IS ALWAYS THE PREVIOUS RUN'S: rows are written at session finish and a guard reading
    them is collected long before it, so a fresh worktree reads nothing. That is a missing reading,
    not a conviction (user directive 2026-10-05), so it is returned as one line naming the door; the
    two judgements convict only on a reading. The SLACK side still raises, because it judges a
    ledger that does exist.

    Args:
        ledger: what :func:`read` returned.
        floor: the smallest row count that can mean anything in this repo. NO DEFAULT. A run records
            a ROW PER TEST, so a floor set from a repo's MODULE count is conservative on purpose.
        headroom: the largest slack the floor may carry before it must be re-measured -- the side
            that stops a floor measured against a small suite from passing a run that lost most of
            its corpus.
        what: names the scan, so the notice says which guard has no data. NO DEFAULT; a borrowed
            label MISDIRECTS.

    Returns:
        ``''`` when the ledger is evidence, else ``<what>: no data (...) -- run `<door>` to measure``.

    Raises:
        dev_lab.dev.floors.SlackFloor: the floor has been outgrown past *headroom*.
        dev_lab.dev.floors.FloorMisdeclared: the floor or headroom refuses nothing.

    """
    count = len(ledger.seconds)
    if count < floor:
        return f'{what}: no data ({count} of {floor} readings) -- run `{MEASURE_DOOR}` to measure'
    floors.assert_floor_still_binds(count, floor=floor, headroom=headroom, what=what)
    return ''


def assert_the_crash_marker_is_what_the_scheduler_writes(*, scheduler_source: str, where: str) -> None:
    """:data:`CRASH_MARKER` is still the sentence the scheduler writes, read off SOURCE THE CALLER READ.

    A DETECTOR AND ITS SUBJECT MUST NOT AGREE ONLY WITH EACH OTHER. The crash arm keys on text
    because a dead worker leaves no structured field, so the day the scheduler rewords that sentence
    the arm goes silent -- and silent means the ledger files the wall's own kills at ~0.0s again,
    which is the mechanism refuting itself in its own data with no red anywhere.

    THE SOURCE IS AN ARGUMENT AND THIS MODULE NEVER IMPORTS THE SCHEDULER, which is a tier decision
    and not a style one. ``lab_commons``'s pyproject promises that a consumer wanting only logging
    installs nothing heavier, so ``dev_lab.dev`` is stdlib plus tier 1 and
    ``test_dev_gate.py::test_no_dev_module_imports_anything_outside_stdlib_and_tier_one`` reads the
    IMPORT STATEMENTS to enforce it. A guarded ``try: import xdist`` adds no dependency at install
    time and the gate cannot see that -- but evading the gate by spelling the import dynamically
    would be the declaration-that-lies shape arriving inside the guard against it. So the CONSUMER,
    which is the party that actually installs a scheduler, reads its source and hands it over::

        dsession = pytest.importorskip('xdist.dsession')
        assert_the_crash_marker_is_what_the_scheduler_writes(
            scheduler_source=Path(dsession.__file__).read_text(encoding='utf-8'),
            where=dsession.__file__,
        )

    This is the shape :func:`dev_lab.dev.famtests.venvspelling.spellings_in` already uses for the
    same reason: a body handed TEXT can be driven by a control, where a body that opens its own
    subject can only be driven by having that subject installed.

    EMPTY SOURCE IS INCONCLUSIVE, NEVER CLEAN, and the two are separate exception types for the
    reason :mod:`dev_lab.dev.floors` separates its own. It is the FLOOR on this reading: a
    caller whose ``importorskip`` was skipped, or whose read returned nothing, has not PASSED this
    check -- it has failed to take it, and an empty string trivially contains no marker, so without
    this arm the strongest-looking green here is the one that read nothing.

    Args:
        scheduler_source: the scheduler module's source, as the caller read it.
        where: where it came from, so a refusal names a file a reader can open. NO DEFAULT -- a
            borrowed label misdirects, which is worse than naming nothing.

    Raises:
        LedgerInconclusive: *scheduler_source* is empty or blank, so nothing was read.
        AssertionError: the scheduler no longer writes :data:`CRASH_MARKER`.

    """
    if not scheduler_source.strip():
        msg = (
            f'no scheduler source was read from {where!r}, so the crash marker was checked against '
            f'nothing. That is INCONCLUSIVE rather than clean: an empty string contains no marker, '
            f'so this arm would otherwise report its strongest green for the reading it failed to '
            f'take. A repo with no scheduler is also the repo where a wall on Windows kills the '
            f'SESSION instead of a worker, because sharding is what makes the wall recoverable.'
        )
        raise LedgerInconclusive(msg)
    if CRASH_MARKER not in scheduler_source:
        msg = (
            f'the scheduler at {where} no longer writes {CRASH_MARKER!r}. The crash arm keys on that '
            f'text because a dead worker leaves no structured field, so it is now inert: every test '
            f'the wall kills will be filed at the ~0.0s the controller reports for it, and the ledger '
            f'will read the suite the wall just convicted as its FASTEST. Re-read the scheduler and '
            f'move CRASH_MARKER onto the sentence it writes today.'
        )
        raise AssertionError(msg)


@dataclass(eq=False)
class Recorder:
    """The runner's half: accumulate every PHASE of every test, then write the ledger ONCE.

    WHY A CLASS AND NOT THREE MODULE-LEVEL HOOKS. A consumer's ``conftest.py`` is the only thing
    pytest loads for EVERY selection -- a recorder that only ran when the guard itself was selected
    would measure exactly the tests it does not need to measure -- but module-level hook functions in
    the kit would share one mutable dict across every consumer in a process. Binding the three
    methods in a conftest keeps the state with the run::

        _recorder = Recorder(root=REPO_ROOT)
        pytest_configure = _recorder.pytest_configure
        pytest_runtest_logreport = _recorder.pytest_runtest_logreport
        pytest_sessionfinish = _recorder.pytest_sessionfinish

    NOTHING HERE IMPORTS PYTEST. The three arguments are used for four attributes between them, so
    the kit stays stdlib-plus-tier-1 and every method is drivable from a control with a plain object.
    """

    root: Path
    #: The live wall, bound from the runner's own setting by :meth:`pytest_configure`. ZERO until
    #: then, and zero is the honest reading: a repo with no wall has no lower bound to file a crash
    #: at, and inventing one here would be the fabricated measurement this module refuses.
    wall: float = 0.0
    seconds: dict[str, float] = field(default_factory=dict)
    #: Each test's own deadline (:func:`dev_lab.dev.testcost.schedule`): a kill there is filed AT it, not at the wall.
    deadlines: dict[str, float] = field(default_factory=dict)
    #: What verify is measuring, handed over through the environment; ``''`` outside verify.
    tree: str = field(default_factory=lambda: os.environ.get(LEDGER_TREE_VAR, ''))
    env: str = field(default_factory=lambda: os.environ.get(LEDGER_ENV_VAR, ''))
    #: The worker this process is (``None``: the controller or a run without workers), bound at configure.
    worker: str | None = None
    #: The watchdog of the test now running, if it has a deadline (:meth:`pytest_runtest_logstart`).
    _watch: threading.Timer | None = field(default=None, repr=False)

    def pytest_configure(self, config: RunConfig) -> None:
        """Bind the crash duration to THE WALL THE RUNNER IS ACTUALLY ENFORCING, never to a copy.

        A second spelling of the wall is a second thing to keep in step. A repo with no
        ``pytest-timeout`` has no ``timeout`` setting to read, which raises ``ValueError`` out of
        pytest's own ini lookup -- caught BY NAME, because a bare except here would swallow the
        misconfiguration it exists to tolerate.
        """
        try:
            declared = config.getini('timeout')
        except ValueError:
            declared = None
        self.wall = float(declared or 0.0)
        self.worker = config.workerinput.get('workerid') if isinstance(config, _WorkerConfig) else None

    def pytest_runtest_logstart(self, nodeid: str, location: object) -> None:
        """Arm the DEADLINE WATCHDOG of a test that has a deadline (:func:`dev_lab.dev.testcost.schedule`).

        WINDOWS WITHOUT WORKERS: pytest-timeout's thread method ends the WHOLE PROCESS (``os._exit``), so no
        report and no session finish ever record the kill. The watchdog fires at the deadline -- before the
        timeout, which :data:`dev_lab.dev.testcost.KILL_GRACE_S` later ends the process -- and writes this
        process's ledger with the test filed AT its deadline: "cost >= deadline", a measurement. A test that
        finishes first disarms it (:meth:`pytest_runtest_logfinish`), and the session's own write supersedes it.
        """
        del location
        if nodeid in self.deadlines:
            self._watch = threading.Timer(self.deadlines[nodeid], self.deadline_reached, args=(nodeid,))
            self._watch.daemon = True
            self._watch.start()

    def pytest_runtest_logfinish(self, nodeid: str, location: object) -> None:
        """Disarm the watchdog: the test ended inside its deadline."""
        del nodeid, location
        if self._watch is not None:
            self._watch.cancel()
            self._watch = None

    def deadline_reached(self, nodeid: str) -> Path:
        """Write the ledger NOW with *nodeid* filed at its deadline, before the timeout ends the process."""
        rows = {**self.seconds, nodeid: max(self.seconds.get(nodeid, 0.0), self.deadlines[nodeid])}
        return write(
            self.root,
            (Row(nodeid=node, seconds=value) for node, value in rows.items()),
            selector='deadline',
            worker=self.worker,
            tree=self.tree,
            env=self.env,
        )

    def pytest_runtest_logreport(self, report: PhaseReport) -> None:
        """Accumulate the wall-clock cost of every PHASE of every test, per nodeid.

        ALL THREE PHASES ARE SUMMED, not just ``call``: a fixture that takes four minutes to set up
        costs the box four minutes, and attributing that to zero lets the expensive half of a slow
        test hide in ``setup``, where no duration reading looks.
        """
        seconds = phase_seconds(
            duration=float(report.duration),
            failed=bool(report.failed),
            longrepr=str(report.longrepr),
            wall=self.deadlines.get(report.nodeid, self.wall),
        )
        self.seconds[report.nodeid] = self.seconds.get(report.nodeid, 0.0) + seconds

    def pytest_sessionfinish(self, session: RunSession) -> Path:
        """Write the ledger once, NAMING THE SELECTOR -- a run's rows mean nothing without it.

        ``exitstatus`` IS DELIBERATELY NOT DECLARED. pluggy passes a hook only the arguments it
        names, so omitting it is the supported spelling AND it keeps the ledger unconditional:
        a recorder that skipped writing on a red exit would lose the rows of exactly the run
        that went wrong, which is the run whose durations are worth having.
        """
        config = session.config
        selector = str(config.getoption('-m') or '').strip() or 'all'
        worker = config.workerinput.get('workerid') if isinstance(config, _WorkerConfig) else None
        return write(
            self.root,
            (Row(nodeid=nodeid, seconds=value) for nodeid, value in self.seconds.items()),
            selector=selector,
            worker=worker,
            tree=self.tree,
            env=self.env,
        )


def pytest_configure(config: PluginConfig) -> None:
    """THE PLUGIN DOOR: ``pytest -p dev_lab.dev.durations`` records every run, whatever conftest loads.

    :mod:`dev_lab.dev.verify` passes it, so a TARGETED run records too -- a conftest-bound recorder
    only loads for tests under that conftest. One :class:`Recorder` per run keeps the state off this
    module, and ``pytest_configure`` is historic, so the instance's own one is still called.
    """
    config.pluginmanager.register(Recorder(root=Path(config.rootpath)), name='lab-commons-durations')
