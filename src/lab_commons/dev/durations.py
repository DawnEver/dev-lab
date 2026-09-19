"""THE LEDGER THE WALL WRITES, and the two readings a ``slow`` marker set is judged by.

WHY THIS IS FAMILY. ``pytest.mark.slow`` is a hand-maintained set and, until this module, nothing in
any of the four repos checked it was COMPLETE. On 2026-09-19 that cost wdg-lab a full day: three
runs wedged and produced no verdict at all, two of the three carried the marker and were selected
anyway, and THE THIRD CARRIED NO MARKER, ran for twenty-nine minutes inside a narrowed
``-m 'not slow'`` tier, and was killed by hand. A declaration asserting a property the code does not
enforce is this family's named dominant defect, and a marker set nobody verifies is exactly one.

THE MECHANISM, AND THE THREE IT WAS CHOSEN OVER. The runner records every test's wall-clock cost
ONCE, from the report it already has, as a machine-readable LEDGER; the consuming repo then convicts
any module the ledger clocks at or above ITS bar that carries no marker. The marker set therefore
grows from a MEASUREMENT OF THE BOX rather than from somebody's memory of which test felt slow.

* ``pytest-timeout``'s own red NAMES the test and is the hard stop, but it is a ONE-OFF rather than
  a ratchet: a killed test is fixed by making it faster, by raising the wall, or by marking it,
  nothing records which, and nothing ever reds when a MARKED test stops being slow.
* ``--durations=N`` is a REPORT, not data -- a truncated top-N printed to a terminal that a verdict
  log then has to be parsed back out of as TEXT. That reading has already been retired once here.
* A duration recorded by a per-test fixture hands the bookkeeping back to every test author, which
  is the hand-maintenance the guard exists to delete.

WHAT THE KIT KEEPS AND WHAT THE REPO RULES ON. This module records a FACT and CLASSIFIES it; it
never decides. ``SLOW_BAR``, ``FAST_CEILING``, ``WALL_SECONDS``, the ledger floor and the marked-set
NAMES stay in the consuming repo, which is the same seam ``configrender`` and ``datedmemory`` run on
-- a change to the bar cannot then be smuggled in as a change to the measurement. Every number here
arrives as a KEYWORD ARGUMENT WITH NO DEFAULT, for the reason :mod:`lab_commons.dev.floors` gives:
one repo's answer handed silently to another is a bar nothing measured.

THE UNIT IS THE MODULE, NOT THE TEST, and that is forced rather than chosen. ``pytest.mark.slow`` is
applied at module or function level and no reading of the source can attribute a module-level
``pytestmark`` to one nodeid, so a per-nodeid claim would convict every test in a marked module of
being unmarked. :func:`module_of` folds a nodeid to its file and both sides compare modules. The
cost is real and is stated rather than hidden: one slow test marks its whole module slow.

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
wdg-lab got on 2026-09-19 required ``-n 4``. "Run it sharded" is therefore not a performance
preference for a consumer of this module; it is the condition under which the ledger gets written at
all, and a reader who assumes otherwise is surprised exactly once, at the worst moment.

WHAT A LEDGER CANNOT SEE, stated rather than left to be discovered. It holds the tests that RAN, so
a run selecting ``-m 'not slow'`` records nothing about a marked module and the waiver-side arm has
no evidence for it -- which is why :func:`write` records the SELECTOR beside the rows and why
:func:`marked_but_fast` convicts over the INTERSECTION only. A duration measured on a loaded box is
also not a property of the test, which is why a consumer's two bars should be an order of magnitude
apart rather than a tight band that reds on the box's mood.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Final, NamedTuple, Protocol

from lab_commons.dev import floors

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

__all__ = [
    'CRASH_MARKER',
    'FAST',
    'LEDGER_DIRECTORY',
    'SLOW',
    'Finding',
    'Ledger',
    'LedgerInconclusive',
    'PhaseReport',
    'Recorder',
    'Row',
    'RunConfig',
    'RunSession',
    'assert_the_crash_marker_is_what_the_scheduler_writes',
    'assert_the_ledger_is_evidence',
    'assert_the_readings_still_convict',
    'ledger_path',
    'marked_but_fast',
    'module_of',
    'over',
    'phase_seconds',
    'read',
    'unmarked_but_slow',
    'write',
]

#: Beside the verdict logs, because a duration is evidence about the same run they are evidence for.
LEDGER_DIRECTORY: Final = '.verify'

#: One file per pytest process; :func:`read` merges them. See the docstring on sharding.
_STEM: Final = 'durations'

#: THE SENTENCE THE SCHEDULER WRITES WHEN A WORKER DIES MID-TEST, and the whole reason this module
#: does not trust a reported duration. Spelled here as the SUBSTRING that survives the ``!r``
#: quoting of a worker id and a nodeid around it, and re-read off the installed scheduler by
#: :func:`assert_the_crash_marker_is_what_the_scheduler_writes` so a rename reds rather than
#: silently restoring the acquit-what-the-wall-caught defect.
CRASH_MARKER: Final = 'crashed while running'

#: The two things a :class:`Finding` can be, and they carry OPPOSITE remedies -- mark the module, or
#: drop the marker. A caller asserts on the classification rather than on a bare count.
SLOW: Final = 'unmarked-but-slow'
FAST: Final = 'marked-but-fast'


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


class RunConfig(Protocol):
    """The two questions :class:`Recorder` asks a runner's config: the wall, and what was selected."""

    def getini(self, name: str) -> object:
        """The declared ini value for *name*, raising ``ValueError`` for an unregistered key."""

    def getoption(self, name: str) -> object:
        """The command-line option *name*, or a falsy value if it was not given."""


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


@dataclass(frozen=True, slots=True)
class Finding:
    """ONE convicted module, WITH THE READING THAT CONVICTED IT and which of the two it is.

    A bare name set says a module is wrong and not WHY, so a consumer's test can only assert on a
    count -- and a count is blind to a swap. *verdict* is :data:`SLOW` or :data:`FAST`, whose
    remedies are opposite, and *seconds* is the number the ledger actually held for it.
    """

    module: str
    seconds: float
    verdict: str

    def __str__(self) -> str:
        """The finding as one repair-shaped line, module first so a reader can sort by file."""
        return f'{self.module}: {self.seconds:.3f}s -- {self.verdict}'


def ledger_path(root: Path, *, worker: str | None = None) -> Path:
    """Where one process's rows live: ``<root>/.verify/durations[-<worker>].json``."""
    suffix = f'-{worker}' if worker else ''
    return Path(root) / LEDGER_DIRECTORY / f'{_STEM}{suffix}.json'


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


def write(root: Path, rows: Iterable[Row], *, selector: str, worker: str | None = None) -> Path:
    """Record *rows* for ONE process, MERGED into what THAT process's file already held, keeping max.

    MERGED RATHER THAN OVERWRITTEN, and the reason is a defect measured on this mechanism's first
    run. A ledger describing exactly one run sounds right and is not: a TARGETED run -- one file,
    thirteen tests -- would replace a full run's ledger with thirteen rows, and the consumer's floor
    would then red on the next full run for a reason with nothing to do with the suite. EVERY
    NARROW RUN A DEVELOPER MAKES WOULD BREAK THE GUARD.

    So a row means "the longest this test has been observed to hold the box ON THIS BOX", which is
    the claim a marker guard actually needs: a test that is slow on one run and quick on the next is
    slow. THE COST IS STALENESS -- a test that has genuinely become fast keeps its old row until the
    ledger is deleted -- and the remedy is exactly that deliberate act, which is what a ratchet
    wants.

    THE MERGE IS WITH THIS PROCESS'S OWN FILE AND NOT WITH EVERY FILE IN THE DIRECTORY. A worker
    folding its siblings' rows into its own file would leave four files each claiming to have
    measured everything; ``max`` makes that harmless to :func:`read` and ruinous to anyone reading
    one file to find out what one worker did.

    Args:
        root: the checkout whose ``.verify/`` holds the ledger.
        rows: this process's measurements.
        selector: what the run SELECTED, recorded because rows mean nothing without it.
        worker: the shard id, or ``None`` for an unsharded run.

    Returns:
        The path written.

    """
    path = ledger_path(root, worker=worker)
    path.parent.mkdir(parents=True, exist_ok=True)
    merged = dict(_rows_in(path))
    for row in rows:
        merged[row.nodeid] = max(round(float(row.seconds), 3), merged.get(row.nodeid, 0.0))
    payload = {'selector': selector, 'seconds': merged}
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    return path


def _rows_in(path: Path) -> dict[str, float]:
    """One ledger file's rows, or none at all if it is not there yet."""
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding='utf-8'))
    return {nodeid: float(value) for nodeid, value in dict(payload.get('seconds', {})).items()}


def read(root: Path) -> Ledger:
    """EVERY ledger file in *root*, merged by max. An absent ledger is an EMPTY one, never an error.

    Emptiness is not judged here on purpose: "no ledger" and "a ledger of nothing" are the same fact,
    and the floor that refuses both is :func:`assert_the_ledger_is_evidence`, whose number belongs to
    the repo. Returning a sentinel would hand a caller a third state to forget about.
    """
    directory = Path(root) / LEDGER_DIRECTORY
    merged: dict[str, float] = {}
    selectors: list[str] = []
    paths = sorted(directory.glob(f'{_STEM}*.json')) if directory.is_dir() else []
    for path in paths:
        payload = json.loads(path.read_text(encoding='utf-8'))
        selectors.append(str(payload.get('selector', '')))
        for nodeid, seconds in _rows_in(path).items():
            merged[nodeid] = max(float(seconds), merged.get(nodeid, 0.0))
    return Ledger(selector=' | '.join(sorted(set(selectors))), seconds=merged)


def over(seconds: Mapping[str, float], *, bar: float) -> frozenset[str]:
    """The modules holding at least one test at or above *bar* seconds."""
    return frozenset(module_of(nodeid) for nodeid, value in seconds.items() if float(value) >= bar)


def _worst(seconds: Mapping[str, float]) -> dict[str, float]:
    """The longest row the ledger holds per module -- the reading both arms below classify on."""
    observed: dict[str, float] = {}
    for nodeid, value in seconds.items():
        module = module_of(nodeid)
        observed[module] = max(float(value), observed.get(module, 0.0))
    return observed


def unmarked_but_slow(
    seconds: Mapping[str, float],
    marked: frozenset[str],
    *,
    bar: float,
) -> tuple[Finding, ...]:
    """THE CONVICTION: modules the ledger clocks at or above *bar* that carry no marker.

    Args:
        seconds: the ledger's rows, nodeid to seconds.
        marked: the modules that DO declare the marker, read from the parsed tree by the consumer.
        bar: the seconds at which a module must be marked. NO DEFAULT -- it is the repo's number,
            and it should sit BELOW that repo's wall with stated headroom, or the only way to
            discover a missing marker is to be killed by the wall.

    Returns:
        One :class:`Finding` per convicted module, sorted, each carrying the reading and
        :data:`SLOW`.

    """
    worst = _worst(seconds)
    return tuple(
        Finding(module=name, seconds=worst[name], verdict=SLOW) for name in sorted(over(seconds, bar=bar) - marked)
    )


def marked_but_fast(
    seconds: Mapping[str, float],
    marked: frozenset[str],
    *,
    ceiling: float,
) -> tuple[Finding, ...]:
    """THE MIRROR, over the INTERSECTION ONLY -- a module with no row was never measured.

    A ratchet has two sides. A module over the bar and unmarked is the defect that cost a day; a
    module MARKED slow that the ledger clocks under *ceiling* is a waiver nobody uses, and it
    deselects real coverage from the narrowed tier for nothing.

    A module is convicted here only when EVERY row the ledger holds for it is under *ceiling*, so a
    single expensive test keeps the marker earned, and ABSENCE OF EVIDENCE CONVICTS NOBODY -- a run
    selecting ``-m 'not slow'`` records no row for a marked module, and reading that as fast would
    make the narrowed tier delete its own waivers.

    Args:
        seconds: the ledger's rows.
        marked: the modules declaring the marker.
        ceiling: the seconds under which a marker buys nothing. NO DEFAULT, and it should sit an
            order of magnitude below the bar rather than just under it: a duration measured on a
            loaded box is not a property of the test, and a tight two-sided band reds on the box's
            mood rather than on the suite.

    Returns:
        One :class:`Finding` per convicted module, sorted, each carrying :data:`FAST`.

    """
    worst = _worst(seconds)
    return tuple(
        Finding(module=name, seconds=worst[name], verdict=FAST)
        for name in sorted(marked & frozenset(worst))
        if worst[name] < ceiling
    )


def assert_the_ledger_is_evidence(*, ledger: Ledger, floor: int, headroom: int, what: str) -> None:
    """THE FLOOR, BOTH SIDES. An absent, empty or partial ledger is a KILLED RUN, not a clean suite.

    THE LEDGER IS ALWAYS THE PREVIOUS RUN'S, and that is inherent rather than a bug: rows are written
    at session finish and a guard reading them is collected long before it. A box that has never
    completed a full run therefore reds HERE, naming the remedy -- run the suite once. That cost is
    paid once per box, because :func:`write` merges rather than overwrites.

    Args:
        ledger: what :func:`read` returned.
        floor: the smallest row count that can mean anything in this repo. NO DEFAULT. A run records
            a ROW PER TEST, so a floor set from a repo's MODULE count is conservative on purpose.
        headroom: the largest slack the floor may carry before it must be re-measured -- the side
            that stops a floor measured against a small suite from passing a run that lost most of
            its corpus.
        what: names the scan, so the refusal says which guard went quiet. NO DEFAULT; a borrowed
            label does not raise, it MISDIRECTS.

    Raises:
        lab_commons.dev.floors.FloorUnmet: fewer rows than *floor*.
        lab_commons.dev.floors.SlackFloor: the floor has been outgrown past *headroom*.
        lab_commons.dev.floors.FloorMisdeclared: the floor or headroom refuses nothing.

    """
    floors.assert_floor(len(ledger.seconds), floor=floor, what=what)
    floors.assert_floor_still_binds(len(ledger.seconds), floor=floor, headroom=headroom, what=what)


def assert_the_crash_marker_is_what_the_scheduler_writes(*, scheduler_source: str, where: str) -> None:
    """:data:`CRASH_MARKER` is still the sentence the scheduler writes, read off SOURCE THE CALLER READ.

    A DETECTOR AND ITS SUBJECT MUST NOT AGREE ONLY WITH EACH OTHER. The crash arm keys on text
    because a dead worker leaves no structured field, so the day the scheduler rewords that sentence
    the arm goes silent -- and silent means the ledger files the wall's own kills at ~0.0s again,
    which is the mechanism refuting itself in its own data with no red anywhere.

    THE SOURCE IS AN ARGUMENT AND THIS MODULE NEVER IMPORTS THE SCHEDULER, which is a tier decision
    and not a style one. ``lab_commons``'s pyproject promises that a consumer wanting only logging
    installs nothing heavier, so ``lab_commons.dev`` is stdlib plus tier 1 and
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

    This is the shape :func:`lab_commons.dev.famtests.venvspelling.spellings_in` already uses for the
    same reason: a body handed TEXT can be driven by a control, where a body that opens its own
    subject can only be driven by having that subject installed.

    EMPTY SOURCE IS INCONCLUSIVE, NEVER CLEAN, and the two are separate exception types for the
    reason :mod:`lab_commons.dev.floors` separates its own. It is the FLOOR on this reading: a
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


def assert_the_readings_still_convict(*, bar: float, ceiling: float) -> None:
    """THE PLANTED CONTROL. Plant a ledger built to be convicted and drive the REAL readings.

    The thing under test is NOT replaced -- :func:`unmarked_but_slow`, :func:`marked_but_fast` and
    :func:`phase_seconds` are the same functions a live arm calls, handed the same SHAPE of data. It
    is the EVIDENCE that is planted, and that is the point: the alternative is a control that waits
    for a real test to become slow.

    EQUALITY, NOT MEMBERSHIP, on every arm. A grader that names everything passes a membership
    control, and the declared-subset-of-live shape has already hidden wrong constants in this family.

    Five claims, because the readings make five and a control driving one leaves four asserted by
    prose:

    * a module over the bar with no marker is convicted, and a fast one beside it is not;
    * the MARKER is what makes the difference, not the duration;
    * the mirror convicts a marked module the ledger clocks as fast, and ACQUITS a marked module the
      ledger never measured -- absence convicts nobody;
    * a mixed module keeps its marker on the strength of its one expensive test;
    * A CRASH REPORT AT ~0.0s IS FILED AT THE WALL, which is the defect that refutes the whole
      mechanism in its own data, and an ordinary failure at ~0.0s is NOT.

    Args:
        bar: the seconds at or above which a module must be marked.
        ceiling: the seconds under which a marker buys nothing.

    Raises:
        AssertionError: any of the five, or the two bars do not admit a plantable case between them.

    """
    if not 0 < ceiling < bar:
        msg = (
            f'a ceiling of {ceiling} and a bar of {bar} leave no room to plant a case: the control '
            f'needs a duration BETWEEN them to prove the two arms convict different things. A '
            f'ceiling at or above the bar makes every module both slow and fast at once.'
        )
        raise AssertionError(msg)

    slow_nodeid = 'tests/integration/test_planted_wedge.py::test_a'
    fast_nodeid = 'tests/unit/test_planted_fast.py::test_b'
    seconds = {slow_nodeid: bar + 1.0, fast_nodeid: ceiling / 2}
    convicted = unmarked_but_slow(seconds, frozenset(), bar=bar)
    if tuple(item.module for item in convicted) != ('tests/integration/test_planted_wedge.py',):
        msg = (
            f'the conviction answered {[str(item) for item in convicted]} on a planted ledger holding '
            f'one module over the bar and one under it. A reading that names everything or nothing '
            f'reports a clean tree for the defect it was written against.'
        )
        raise AssertionError(msg)
    if convicted[0].verdict != SLOW:
        msg = f'the conviction classified its finding as {convicted[0].verdict!r}, not {SLOW!r}'
        raise AssertionError(msg)

    marked = frozenset({'tests/integration/test_planted_wedge.py'})
    if unmarked_but_slow(seconds, marked, bar=bar):
        msg = (
            'a module the ledger clocks far over the bar was convicted WITH its marker present, so '
            'the marker is not what makes the difference and every marked module in the tree is a '
            'standing red.'
        )
        raise AssertionError(msg)

    mirror_marked = frozenset({'tests/a/test_fast.py', 'tests/a/test_mixed.py', 'tests/a/test_unmeasured.py'})
    mirror_seconds = {
        'tests/a/test_fast.py::test_a': ceiling / 2,
        'tests/a/test_mixed.py::test_a': ceiling / 2,
        'tests/a/test_mixed.py::test_b': bar + 1.0,
    }
    mirror = marked_but_fast(mirror_seconds, mirror_marked, ceiling=ceiling)
    if tuple(item.module for item in mirror) != ('tests/a/test_fast.py',):
        msg = (
            f'the mirror answered {[str(item) for item in mirror]}. It must convict the module every '
            f'row of which is under the ceiling, keep the marker on the module with ONE expensive '
            f'test, and say NOTHING about the module the ledger never measured -- a run selecting '
            f'`-m "not slow"` measures no marked module at all, and reading that as fast would make '
            f'the narrowed tier delete its own waivers.'
        )
        raise AssertionError(msg)
    if mirror[0].verdict != FAST:
        msg = f'the mirror classified its finding as {mirror[0].verdict!r}, not {FAST!r}'
        raise AssertionError(msg)

    wall = bar * 2
    killed = phase_seconds(
        duration=0.0,
        failed=True,
        longrepr=f"worker 'gw1' {CRASH_MARKER} '{slow_nodeid}'",
        wall=wall,
    )
    if killed != wall:
        msg = (
            f'a crash report filed at 0.0s was recorded as {killed}s rather than at the {wall}s wall. '
            f'THIS IS THE DEFECT THAT REFUTES THE MECHANISM IN ITS OWN DATA: the tests the wall just '
            f'convicted enter the ledger as the fastest in the suite, and the guard then acquits '
            f'exactly what the wall caught.'
        )
        raise AssertionError(msg)
    ordinary = phase_seconds(duration=0.0, failed=True, longrepr='assert 1 == 2', wall=wall)
    if ordinary != 0.0:
        msg = (
            f'an ordinary assertion failure at 0.0s was recorded as {ordinary}s. The arm must key on '
            f'the scheduler sentence and nothing else; filing every fast failure at the wall would '
            f'mark the whole suite slow and is the same fabrication pointing the other way.'
        )
        raise AssertionError(msg)


@dataclass
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

    def pytest_runtest_logreport(self, report: PhaseReport) -> None:
        """Accumulate the wall-clock cost of every PHASE of every test, per nodeid.

        ALL THREE PHASES ARE SUMMED, not just ``call``: a fixture that takes four minutes to set up
        costs the box four minutes, and attributing that to zero lets the expensive half of a slow
        test hide in ``setup``, where no duration reading looks.
        """
        seconds = phase_seconds(
            duration=float(report.duration),
            failed=bool(report.failed),
            longrepr=str(getattr(report, 'longrepr', '')),
            wall=self.wall,
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
        worker = getattr(config, 'workerinput', {}).get('workerid')
        return write(
            self.root,
            (Row(nodeid=nodeid, seconds=value) for nodeid, value in self.seconds.items()),
            selector=selector,
            worker=worker,
        )
