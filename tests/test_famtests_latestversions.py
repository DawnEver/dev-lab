"""The controls for :mod:`lab_commons.dev.famtests.latestversions` -- both arms and all three answers.

THE ARM THIS FILE EXISTS FOR IS THE ONE ABOUT THE FETCH, and it is asserted as a TYPE rather than
only as a message. ``FetchUnavailable`` must NOT be an ``AssertionError``: this family reads an
assertion failure as a named FAIL, and a failed fetch is the third answer, the one that says the run
cannot speak. If the two were ever collapsed, a network outage would read as "your dependencies
drifted" -- a report about the wrong thing, produced confidently -- and the arm below is what refuses
that collapse.

EVERY OTHER ARM IS DRIVEN WITH A FETCH THAT NEVER LEAVES THE PROCESS. The verdict calls the fetcher
it is handed, so a planted one is a complete substitute; and the arm that says an offline red never
spends a fetch asserts the planted one was NOT called, which is a claim about cost that only a spy
can make.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from lab_commons.dev import floors
from lab_commons.dev.depversions import Exemption, Observation, Observed
from lab_commons.dev.famtests.latestversions import (
    DependencyDrift,
    Fetch,
    FetchUnavailable,
    LatestScan,
    assert_dependencies_are_latest,
    assert_the_reader_still_convicts,
    take_scan,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

_DAY = date(2026, 9, 21)
_REVISION = 'a' * 40
_OBSERVATION = 'observed-versions.toml'

#: The floors every arm but the floor arms hands the verdict: a planted tree of two, generously
#: banded, so an arm is about the ARM rather than about the arithmetic of a floor.
_FLOORS: Mapping[str, int] = {
    'floor': 2,
    'headroom': 100,
    'resolved_floor': 2,
    'resolved_headroom': 100,
    'exemption_ceiling': 1,
}

_LOCK = f"""\
version = 1
[[package]]
name = "an-index-dep"
version = "1.0.0"
source = {{ registry = "https://pypi.org/simple" }}

[[package]]
name = "a-remote-dep"
version = "0.1.1"
source = {{ git = "https://example.invalid/a-remote-dep.git#{_REVISION}" }}

[[package]]
name = "this-checkout"
version = "0.0.0"
source = {{ editable = "." }}
"""


def _baseline(day: date = _DAY) -> str:
    """The committed baseline, with the observation date movable -- the ceiling's own control."""
    return f"""\
[observed.an-index-dep]
latest = "1.0.0"
observed_on = "{day.isoformat()}"
kind = "index"
source = "an-index-dep"

[observed.a-remote-dep]
latest = "{_REVISION}"
observed_on = "{day.isoformat()}"
kind = "remote"
source = "https://example.invalid/a-remote-dep.git"
"""


def _answer(day: date = _DAY, **latest: str) -> Observation:
    """A planted fetch, answering exactly the names given and filing each as an ``'index'`` row."""
    return Observation(
        answered={
            name: Observed(name=name, latest=value, observed_on=day, kind='index', source=name)
            for name, value in sorted(latest.items())
        },
        failed={},
    )


class Counter:
    """A planted fetch that records whether it was called at all, and answers a scripted mapping."""

    def __init__(self, observation: Observation) -> None:
        """Answer *observation* and record every call."""
        self.observation = observation
        self.calls = 0

    def __call__(self, _baseline: Mapping[str, Observed]) -> Observation:
        """Answer, counting the call."""
        self.calls += 1
        return self.observation


def _planted(root: Path, *, day: date = _DAY, baseline: str | None = None) -> Path:
    """A lock, a baseline and the path a verdict is taken on. The environment is never read."""
    (root / 'uv.lock').write_text(_LOCK, encoding='utf-8')
    observation = root / _OBSERVATION
    observation.write_text(_baseline(day) if baseline is None else baseline, encoding='utf-8')
    return observation


def _scan(root: Path, observation: Path) -> LatestScan:
    """The tree's readings, with the environment supplied so arm two never touches this interpreter."""
    installed = {'an-index-dep': '1.0.0', 'a-remote-dep': '0.1.1'}
    return take_scan(root, observation=observation, installed=installed)


def _check(
    scan: LatestScan,
    fetch: Fetch,
    *,
    exemptions: Mapping[str, Exemption] | None = None,
    today: date = _DAY,
) -> None:
    """The verdict, called the way a consumer's architecture test calls it."""
    assert_dependencies_are_latest(
        scan,
        fetch=fetch,
        exemptions=exemptions or {},
        today=today,
        what='planted-corpus',
        **_FLOORS,
    )


def test_a_matching_resolution_passes_and_a_moved_one_names_both_sides(tmp_path: Path) -> None:
    """THE CHECK. Both sides of the comparison, and the refusal names both values.

    A package at exactly what the source answers is left alone; one that moved is reported with the
    value the lock holds and the value the source states.
    """
    scan = _scan(tmp_path, _planted(tmp_path))
    _check(scan, Counter(_answer(_DAY, **{'an-index-dep': '1.0.0', 'a-remote-dep': _REVISION})))
    moved = Counter(_answer(_DAY, **{'an-index-dep': '2.0.0', 'a-remote-dep': _REVISION}))
    with pytest.raises(DependencyDrift, match='an-index-dep'):
        _check(scan, moved)
    assert moved.calls == 1


def test_a_fetch_that_does_not_answer_is_inconclusive_and_never_a_pass(tmp_path: Path) -> None:
    """THE THIRD ANSWER, and the reason this module may call the network at all.

    ``upperbounds`` refuses a network call inside a verdict because an unanswered call must not become
    one of the verdict's two answers. Here it becomes the third, and it must NOT be readable as a
    pass: "the index was down, so we passed" hands the answer to somebody else's uptime. The refusal
    names the packages that went unanswered AND the committed baseline a reader falls back to, with
    its age, because a stale baseline is a reason to refresh rather than one to lean on.
    """
    assert not issubclass(FetchUnavailable, AssertionError), (
        'a failed fetch must not read as a FAIL: this family reads an assertion failure as a named '
        'red, and "the network was down" is not a report about a dependency.'
    )
    scan = _scan(tmp_path, _planted(tmp_path))
    half = Counter(_answer(_DAY, **{'an-index-dep': '1.0.0'}))
    with pytest.raises(FetchUnavailable) as caught:
        _check(scan, half)
    text = str(caught.value)
    assert 'a-remote-dep' in text, text
    assert _OBSERVATION in text, 'the remedy must name the committed baseline to read'
    assert 'days ago' in text, text
    assert 'INCONCLUSIVE' in text, text


def test_an_offline_red_never_spends_a_fetch(tmp_path: Path) -> None:
    """A stale baseline reds BEFORE the network is asked anything.

    The ceilings are the offline half, so a repo whose declaration has rotted is told so without a
    round trip -- and an arm that spent one anyway would make the cheap finding cost the expensive
    thing.
    """
    stale_day = _DAY.fromordinal(_DAY.toordinal() - 30)
    scan = _scan(tmp_path, _planted(tmp_path, day=stale_day))
    fetch = Counter(_answer(_DAY, **{'an-index-dep': '1.0.0', 'a-remote-dep': _REVISION}))
    with pytest.raises(DependencyDrift, match='shared baseline'):
        _check(scan, fetch)
    assert fetch.calls == 0, 'an offline arm red before the fetch, so nothing should have been asked'


def test_the_floors_refuse_a_checkout_with_no_lock_and_a_baseline_with_no_rows(tmp_path: Path) -> None:
    """FINDING NOTHING IS VACUOUS RATHER THAN GREEN.

    A fresh clone has no resolved state at all, and a baseline file whose table is empty declares no
    package -- both report exactly what a clean run reports unless the population is floored, which is
    the one case the design brief names by hand.
    """
    observation = _planted(tmp_path)
    (tmp_path / 'uv.lock').unlink()
    with pytest.raises(floors.FloorUnmet, match='below its measured floor'):
        _check(_scan(tmp_path, observation), Counter(_answer(_DAY, **{'an-index-dep': '1.0.0'})))
    (tmp_path / 'uv.lock').write_text(_LOCK, encoding='utf-8')
    observation.write_text('[observed]\n', encoding='utf-8')
    with pytest.raises(floors.FloorUnmet, match='below its measured floor'):
        _check(_scan(tmp_path, observation), Counter(_answer(_DAY, **{'an-index-dep': '1.0.0'})))


def test_a_baseline_row_nothing_resolves_is_a_waiver_nothing_uses(tmp_path: Path) -> None:
    """The census, one way round and deliberately so.

    A lock resolves the whole transitive closure and declaring all of it is not the point; but a row
    outliving the dependency it names covers nothing while still reading as a decision.
    """
    orphaned = _baseline() + (
        '[observed.gone]\nlatest = "1.0.0"\nobserved_on = "2026-09-21"\nkind = "index"\nsource = "gone"\n'
    )
    scan = _scan(tmp_path, _planted(tmp_path, baseline=orphaned))
    with pytest.raises(DependencyDrift, match='tracks'):
        _check(scan, Counter(_answer(_DAY, **{'an-index-dep': '1.0.0', 'a-remote-dep': _REVISION})))


def test_an_exemption_skips_the_latest_arm_and_is_still_judged_as_a_waiver(tmp_path: Path) -> None:
    """The two halves of an escape hatch, in one arm.

    An exempt package may sit behind the latest; the exemption itself must still carry a reason, a
    live review date and a name that exists.
    """
    scan = _scan(tmp_path, _planted(tmp_path))
    answered = _answer(_DAY, **{'an-index-dep': '2.0.0', 'a-remote-dep': _REVISION})
    with pytest.raises(DependencyDrift, match='an-index-dep'):
        _check(scan, Counter(answered))
    waived = {'an-index-dep': Exemption(reason='the vendor has not tagged since 2024', review_on=date(2026, 12, 1))}
    _check(scan, Counter(answered), exemptions=waived)
    expired = {'an-index-dep': Exemption(reason='a reason', review_on=date(2026, 1, 1))}
    with pytest.raises(DependencyDrift, match='which has passed'):
        _check(scan, Counter(answered), exemptions=expired)
    with pytest.raises(DependencyDrift, match='no reason recorded'):
        _check(scan, Counter(answered), exemptions={'an-index-dep': Exemption(reason='', review_on=_DAY)})


def test_the_control_convicts_a_planted_tree_and_refuses_a_dirty_one(tmp_path: Path) -> None:
    """THE PLANTED CONTROL, driven rather than described.

    One arm runs the shipped control over an empty tree and requires it to pass; the other hands it a
    directory with something already in it, so the control cannot report on a tree it is only partly
    reading -- which is the shape that would let a broken arm pass for a clean one.
    """
    assert_the_reader_still_convicts(tmp_path, observation_name=_OBSERVATION, what='planted-corpus')
    assert sorted(p.name for p in tmp_path.iterdir()) == [_OBSERVATION], 'the control cleaned up after itself'
    dirty = tmp_path / 'dirty'
    dirty.mkdir()
    (dirty / 'something-else.txt').write_text('', encoding='utf-8')
    with pytest.raises(AssertionError, match='not empty'):
        assert_the_reader_still_convicts(dirty, observation_name=_OBSERVATION, what='planted-corpus')
