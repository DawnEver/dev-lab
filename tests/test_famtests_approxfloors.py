"""The controls for :mod:`lab_commons.dev.famtests.approxfloors` -- every distinction, both ways.

A LINT THAT HAS NEVER BEEN SHOWN TO FIRE PROVES NOTHING WHEN IT IS GREEN, and one convicting every
comparison it sees is deleted rather than obeyed. Every distinction below is planted against in both
directions, over real files, through the published surface.

THE ARM THAT MATTERS MOST IS THE BAR. Two repos ask one question and a third asks the other, and the
two convict different sets. So the disagreeing call -- ``approx(x)`` with no tolerance at all -- is
asserted SEPARATELY under each bar rather than parametrized into a single expectation that would be
satisfied by a body with no bar in it.

EVERY NO-DEFAULT ARGUMENT GETS A COUNTER-CONTROL, for the reason the density controls next door give:
the argument for a signature is never the signature, it is that a WRONG value REPORTS A NUMBER rather
than raising. A bar nobody declared is the exception and is refused outright, because both bars return
a plausible answer and neither misreading would look wrong.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from lab_commons.dev import floors
from lab_commons.dev.famtests.approxfloors import (
    BARS,
    ApproxScan,
    FloorlessTolerance,
    approx_calls,
    assert_every_tolerance_states_its_floor,
    assert_the_scanner_still_convicts,
    is_approx,
    take_scan,
    unfloored,
)

_WHAT = 'RELATIVE-TOLERANCE'


def _plant(root: Path, name: str, body: str) -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding='utf-8')
    return path


def _bound(scan: ApproxScan, **over: int) -> None:
    """Bind both floors with values that pass, so an arm testing something else is not floored out."""
    kwargs = {'file_floor': 1, 'file_headroom': 50, 'call_floor': 1, 'call_headroom': 500} | over
    assert_every_tolerance_states_its_floor(scan, bar='ratio', what=_WHAT, **kwargs)


# -- THE BAR: the one call the two questions disagree about. ---------------------------------------


def test_a_defaulted_call_is_an_offender_under_one_bar_and_clean_under_the_other(tmp_path: Path) -> None:
    """``approx(x)`` is the whole disagreement, so it is asserted under each bar by name."""
    planted = _plant(tmp_path, 'test_d.py', 'a = v == approx(1.0)\n')
    assert take_scan([planted], root=tmp_path, bar='unconditional').offenders == ('test_d.py:1',)
    assert take_scan([planted], root=tmp_path, bar='ratio').offenders == ()


@pytest.mark.parametrize('bar', sorted(BARS))
def test_a_ratio_with_no_floor_is_refused_under_every_bar(bar: str, tmp_path: Path) -> None:
    """The one shape BOTH bars convict, parametrized over the NAMED SET so a dropped bar is a hole."""
    planted = _plant(tmp_path, 'test_r.py', 'a = v == approx(1.0, rel=1e-9)\n')
    assert take_scan([planted], root=tmp_path, bar=bar).offenders == ('test_r.py:1',), bar


def test_a_bar_nobody_declared_is_refused_rather_than_selected() -> None:
    """THE COUNTER-CONTROL for the one no-default argument that must not fall back.

    Both bars return a plausible number, so a misspelling silently picking one would be a verdict
    nobody chose. It raises instead, and the message names the set it could have been.
    """
    with pytest.raises(ValueError, match='ratio'):
        unfloored(ast.parse('a = approx(1.0)\n'), bar='strict')


# -- THE READER: import spellings, and the positional pair no consumer sees. ------------------------


def test_both_import_spellings_are_one_call_and_a_lookalike_is_not(tmp_path: Path) -> None:
    """Over-matching and under-matching are both fatal, so each is asserted by count."""
    planted = _plant(
        tmp_path,
        'test_s.py',
        'a = v == pytest.approx(1.0, rel=1e-9)\nb = v == approx(1.0, rel=1e-9)\nc = other.call(1.0, rel=1e-9)\n',
    )
    scan = take_scan([planted], root=tmp_path, bar='ratio')
    assert scan.calls_seen == 2, 'the dotted and the bare form are one call; the lookalike is not one'
    assert scan.offenders == ('test_s.py:1', 'test_s.py:2')


def test_an_aliased_import_is_invisible_and_the_module_says_so() -> None:
    """The blindness the docstring DECLARES, asserted -- a declaration nothing checks is the defect."""
    assert unfloored(ast.parse('a = close(1.0, rel=1e-9)\n'), bar='ratio') == ()
    assert 'approx as close' in (is_approx.__doc__ or ''), 'the alias hole must stay named where it is real'


@pytest.mark.parametrize(
    ('source', 'named'),
    [
        ('a = approx(1.0, 1e-9)\n', True),
        ('a = approx(1.0, 1e-9, 0.0)\n', False),
        ('a = approx(1.0, rel=1e-9, abs=0.0)\n', False),
        ('a = approx(1.0, 1e-9, abs=0.0)\n', False),
    ],
)
def test_a_positional_tolerance_is_read_as_the_keyword_it_is(source: str, *, named: bool, tmp_path: Path) -> None:
    """The reading every consumer file is blind to today, both directions, mixed spellings included."""
    planted = _plant(tmp_path, 'test_p.py', source)
    assert bool(take_scan([planted], root=tmp_path, bar='ratio').offenders) is named, source


# -- THE POPULATIONS: the two floors refuse two different silences. ---------------------------------


def test_an_unparseable_file_is_skipped_rather_than_counted_as_read(tmp_path: Path) -> None:
    """An unparseable file and a parsed clean one are different facts; only the second is evidence."""
    _plant(tmp_path, 'test_broken.py', 'def (\n')
    good = _plant(tmp_path, 'test_ok.py', 'a = v == approx(1.0, rel=1e-9, abs=0.0)\n')
    scan = take_scan(sorted(tmp_path.glob('*.py')), root=tmp_path, bar='ratio')
    assert scan.files_read == 1, 'the broken file must not inflate the corpus the floor judges'
    assert scan.calls_seen == 1
    assert good.exists()


def test_a_read_corpus_with_no_call_sites_left_is_refused_by_the_second_floor(tmp_path: Path) -> None:
    """THE SILENCE THE CORPUS FLOOR CANNOT SEE: every file read, and no tolerance site in any of them."""
    for index in range(30):
        _plant(tmp_path, f'test_{index}.py', 'a = 1\n')
    scan = take_scan(sorted(tmp_path.glob('*.py')), root=tmp_path, bar='ratio')
    assert scan.files_read == 30, 'the corpus floor has nothing to complain about'
    with pytest.raises(floors.FloorUnmet, match='approx call sites'):
        _bound(scan, call_floor=2)


def test_an_empty_walk_is_refused_by_the_corpus_floor(tmp_path: Path) -> None:
    """The other silence: nothing read at all, which reports exactly what a clean tree reports."""
    with pytest.raises(floors.FloorUnmet, match='corpus'):
        _bound(take_scan([], root=tmp_path, bar='ratio'), file_floor=5)


def test_a_floor_the_population_outgrew_is_refused_on_the_other_side() -> None:
    """A ratchet has two sides: a floor measured against a smaller tree stops separating anything."""
    with pytest.raises(floors.SlackFloor, match='corpus'):
        _bound(ApproxScan(files_read=900, calls_seen=9, offenders=()), file_floor=40, file_headroom=25)


def test_the_floors_are_bound_before_a_single_offender_is_looked_at(tmp_path: Path) -> None:
    """ORDER IS THE PROPERTY: an unread tree must not be able to report an offender list instead."""
    planted = _plant(tmp_path, 'test_o.py', 'a = v == approx(1.0, rel=1e-9)\n')
    scan = take_scan([planted], root=tmp_path, bar='ratio')
    assert scan.offenders, 'the scan really does hold an offender, so the floor is what fires'
    with pytest.raises(floors.FloorUnmet):
        _bound(scan, file_floor=40)


def test_the_verdict_names_every_offender_and_the_bar_it_judged_under(tmp_path: Path) -> None:
    """A refusal that does not say which question it asked sends a reader to the wrong repair."""
    planted = _plant(tmp_path, 'test_v.py', 'a = v == approx(1.0, rel=1e-9)\nb = v == approx(2.0, rel=1e-9)\n')
    scan = take_scan([planted], root=tmp_path, bar='ratio')
    with pytest.raises(FloorlessTolerance) as caught:
        _bound(scan)
    assert 'test_v.py:1' in str(caught.value)
    assert 'test_v.py:2' in str(caught.value)
    assert "'ratio'" in str(caught.value)


def test_a_clean_corpus_passes_every_arm(tmp_path: Path) -> None:
    """The green direction, because a guard that cannot pass is deleted rather than obeyed."""
    _plant(tmp_path, 'test_c.py', 'a = v == approx(1.0, rel=1e-9, abs=0.0)\nb = v == approx(2.0, abs=1e-12)\n')
    _bound(take_scan(sorted(tmp_path.glob('*.py')), root=tmp_path, bar='ratio'))


# -- THE SHIPPED CONTROL: it must itself convict, and must itself be able to fail. ------------------


@pytest.mark.parametrize('bar', sorted(BARS))
def test_the_shipped_control_passes_over_the_shipped_scanner(bar: str, tmp_path: Path) -> None:
    """The control a consumer calls really does clear against the reader it is pointed at."""
    assert_the_scanner_still_convicts(tmp_path, bar=bar)


def test_the_shipped_control_reds_when_the_reader_is_doctored(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """DRIVE THE REAL GUARD ON A DOCTORED INPUT AND ASSERT IT REDS, before trusting that it works.

    A control asserted only against a correct reader is a control that has never been shown to fail,
    which is the same vacuity it exists to refuse one level down. Here the READER is broken on purpose
    -- every call reads as having stated its floor -- and the shipped control must notice.
    """
    monkeypatch.setattr('lab_commons.dev.famtests.approxfloors._stated', lambda _call: (True, True))
    with pytest.raises(AssertionError, match='planted offenders'):
        assert_the_scanner_still_convicts(tmp_path, bar='ratio')


def test_the_shipped_control_reds_when_the_matcher_over_matches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The other direction: a matcher reaching a call that is not ``approx`` must be caught too."""
    monkeypatch.setattr('lab_commons.dev.famtests.approxfloors.is_approx', lambda _func: True)
    with pytest.raises(AssertionError, match='approx calls among'):
        assert_the_scanner_still_convicts(tmp_path, bar='ratio')


def test_the_reader_is_pure_over_its_argument() -> None:
    """``approx_calls`` is what a control drives, so it must answer from the tree and nothing else."""
    tree = ast.parse('a = approx(1.0)\nb = pytest.approx(2.0)\nc = other(3.0)\n')
    assert len(approx_calls(tree)) == 2
    assert approx_calls(ast.parse('a = 1\n')) == ()
