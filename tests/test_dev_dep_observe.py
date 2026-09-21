"""The controls for :mod:`lab_commons.dev.dep_observe` -- the refresher, driven with no network.

WHY NOTHING HERE TOUCHES A SOURCE. The whole point of the module is that its two transports answer
different questions about the world, and a test that asked the world would be a test that fails on a
train. So both are driven through the seam the module publishes -- an injected ``transport`` -- and
the SHIPPED transports are driven with the retry wrapper replaced, which is the arm that says
NETWORK-RETRY-THEN-REPORT is enforced in this repo rather than declared absent. That arm asserts the
argv each transport hands ``run_network_verb``, so a transport reaching for a source itself would be
caught by the wrapper never being called.

THE STRICTNESS THAT MATTERS IS ONE-DIRECTIONAL AND BOTH ENDS ARE HERE. ``observe`` must SPLIT an
answer from a silence rather than merging them, and ``write_observed`` must refuse to commit an empty
file -- a baseline declaring nothing reads exactly like one whose every package is up to date, and
the difference only surfaces months later, in a comparison that never happened.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from lab_commons.dev import dep_observe
from lab_commons.dev.dep_observe import (
    ObservationRefused,
    main,
    observe,
    refresh,
    write_observed,
)
from lab_commons.dev.depversions import Observation, Observed, read_observed
from lab_commons.dev.netverb import Attempt, Diagnosis, Report

if TYPE_CHECKING:
    from collections.abc import Callable

_DAY = date(2026, 9, 21)
_REVISION = 'abcdefabcdefabcdefabcdefabcdefabcdefabcd'


class Spy:
    """A ``run_network_verb`` stand-in that records every argv and answers one scripted report."""

    def __init__(self, report: Report) -> None:
        """Answer *report* to every call, recording what each one was handed."""
        self.report = report
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, argv: tuple[str, ...], **_: object) -> Report:
        """Record the argv and answer exactly as ``run_network_verb`` would."""
        self.calls.append(tuple(argv))
        return self.report


def _report(
    *,
    argv: tuple[str, ...] = ('a-verb',),
    output: str = '',
    returncode: int = 0,
    diagnosis: Diagnosis = Diagnosis.SUCCEEDED,
) -> Report:
    """One attempt's worth of report, with the argv a refusal sentence is built from."""
    return Report(
        argv=argv,
        attempts=(Attempt(index=1, returncode=returncode, output=output, diagnosis=diagnosis),),
        allowed_attempts=1,
    )


def test_observe_splits_what_answered_from_what_did_not() -> None:
    """THE CHECK, both halves at once.

    A transport that answers for one locator and not another must produce one row and one failure,
    never one row and a silence -- the silence is the thing a verdict has to be able to see.
    """
    got = observe(
        {'pint': 'pint', 'gone': 'gone'},
        kind='index',
        transport=lambda loc: '0.25.2' if loc == 'pint' else None,
        today=_DAY,
    )
    assert sorted(got.answered) == ['pint']
    assert got.answered['pint'].latest == '0.25.2'
    assert got.answered['pint'].observed_on == _DAY
    assert got.answered['pint'].source == 'pint', 'the row stores the LOCATOR, so the refresh repeats'
    assert sorted(got.failed) == ['gone']
    assert 'answered nothing' in got.failed['gone']


def test_a_transport_that_refuses_carries_its_own_remedy_into_the_failed_half() -> None:
    """A refusal with no reason sends its reader to a network log.

    ``run_network_verb`` already wrote the sentence, so the failure half carries it rather than
    replacing it with a status word.
    """

    def refusing(_locator: str) -> str:
        msg = 'git ls-remote: gave up after 3 of 3 attempts, last diagnosis transient'
        raise ObservationRefused(msg)

    got = observe({'a-dep': 'https://example.invalid/a.git'}, kind='remote', transport=refusing, today=_DAY)
    assert got.answered == {}
    assert 'gave up after 3 of 3 attempts' in got.failed['a-dep']


def test_an_undeclared_kind_and_an_empty_name_set_are_both_refused() -> None:
    """Both are the vacuous shape.

    A kind nobody declared cannot be read at all, and a refresh asking about nothing returns an empty
    answer that is one keystroke from "everything is current".
    """
    with pytest.raises(ValueError, match='is not one of'):
        observe({'a': 'a'}, kind='somewhere-else', transport=lambda _loc: '1', today=_DAY)
    with pytest.raises(ValueError, match='observes nothing'):
        observe({}, kind='index', transport=lambda _loc: '1', today=_DAY)


def test_a_baseline_round_trips_through_the_writer_and_refuses_to_be_emptied(tmp_path: Path) -> None:
    """The writer's two contracts.

    What it writes is what the reader reads, and it will not write a file that declares nothing.
    """
    rows = [
        Observed(name='zed', latest='2.0.0', observed_on=_DAY, kind='index', source='zed'),
        Observed(name='alpha', latest=_REVISION, observed_on=_DAY, kind='remote', source='https://x/a.git'),
    ]
    path = tmp_path / 'observed.toml'
    assert write_observed(path, rows) == 2
    text = path.read_text(encoding='utf-8')
    assert text.index('alpha') < text.index('zed'), 'the file is written sorted, so a refresh diffs cleanly'
    assert read_observed(path) == {'alpha': rows[1], 'zed': rows[0]}
    with pytest.raises(ObservationRefused, match='declaring no package'):
        write_observed(path, [])


def test_refresh_asks_each_row_through_the_transport_its_own_kind_names() -> None:
    """ONE BASELINE, TWO SOURCES.

    A refresh that used one transport for both kinds would answer a git revision from an index, or
    the other way round, and either of those reads as a successful fetch.
    """
    baseline = {
        'an-index-dep': Observed('an-index-dep', '1.0.0', _DAY, 'index', 'an-index-dep'),
        'a-remote-dep': Observed('a-remote-dep', _REVISION, _DAY, 'remote', 'https://x/a.git'),
    }
    asked: list[tuple[str, str]] = []

    def transport_for(kind: str) -> Callable[[str], str]:
        def read(locator: str) -> str:
            asked.append((kind, locator))
            return '9.9.9'

        return read

    transports = {'index': transport_for('index'), 'remote': transport_for('remote')}
    got = refresh(baseline, transports=transports, today=_DAY)
    assert sorted(asked) == [('index', 'an-index-dep'), ('remote', 'https://x/a.git')]
    assert sorted(got.answered) == ['a-remote-dep', 'an-index-dep']


def test_the_index_transport_reaches_its_answer_through_the_retry_wrapper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """NETWORK-RETRY-THEN-REPORT, ENFORCED RATHER THAN DECLARED ABSENT.

    The rule stood in this repo's adoption with the reason "nothing here calls a network verb, so a
    retry wrapper would guard nothing". Both transports are the reason that sentence stopped being
    true, and this arm is what refuses a transport that reaches for its source directly.
    """
    spy = Spy(_report(output='0.25.2\n'))
    monkeypatch.setattr(dep_observe, 'run_network_verb', spy)
    assert dep_observe._index_verb('pint') == '0.25.2'
    argv = spy.calls[0]
    assert argv[1:] == ('-m', 'lab_commons.dev.dep_observe', '--pypi', 'pint'), argv
    assert 'python' in argv[0].lower(), argv


def test_the_remote_transport_reads_head_and_a_missing_ref_is_a_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``--exit-code`` is the difference between "this remote has no HEAD" and an empty answer.

    Without it a remote that answered with no matching ref would read exactly like a remote that
    answered, which is the one shape an observation must never be written from.
    """
    spy = Spy(_report(output=f'{_REVISION}\tHEAD\n'))
    monkeypatch.setattr(dep_observe, 'run_network_verb', spy)
    assert dep_observe._remote_verb('https://x/a.git') == _REVISION
    assert spy.calls[0] == ('git', 'ls-remote', '--exit-code', 'https://x/a.git', 'HEAD')
    git_argv = ('git', 'ls-remote', '--exit-code', 'https://x/a.git', 'HEAD')
    absent = Spy(_report(argv=git_argv, returncode=2, diagnosis=Diagnosis.REMOTE_ABSENT))
    monkeypatch.setattr(dep_observe, 'run_network_verb', absent)
    with pytest.raises(ObservationRefused, match='ls-remote'):
        dep_observe._remote_verb('https://x/a.git')


def test_the_pypi_mode_answers_one_project_and_reports_what_it_could_not(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``--pypi`` is the transport's inner verb, so its two answers are the two the retry loop reads."""
    monkeypatch.setattr(dep_observe, '_pypi_latest', lambda project: '0.25.2' if project == 'pint' else None)
    assert main(['--pypi', 'pint']) == 0
    assert capsys.readouterr().out.strip() == '0.25.2', 'the version is the LAST line a caller reads'
    assert main(['--pypi', 'no-such-project']) == 1
    assert 'answers nothing for' in capsys.readouterr().err


def test_the_refresh_command_writes_only_a_complete_baseline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """THE REFUSAL THAT MATTERS.

    A partial answer must not reach the file: a baseline missing a row is compared against as though
    the package were covered, for as long as the file lives.
    """
    path = tmp_path / 'observed-versions.toml'
    a_row = Observed('a-dep', '1.0.0', _DAY, 'index', 'a-dep')
    b_row = Observed('b-dep', '2.0.0', _DAY, 'index', 'b-dep')
    short = Observation(answered={'a-dep': a_row}, failed={'b-dep': 'the index was down'})
    monkeypatch.setattr(dep_observe, '_ask', lambda *_, **__: short)
    assert main(['--refresh', str(path), '--index', 'a-dep=a-dep', '--index', 'b-dep=b-dep']) == 1
    assert not path.exists(), 'a short answer wrote a file that reads as a complete baseline'
    assert 'the index was down' in capsys.readouterr().err
    whole = Observation(answered={'a-dep': a_row, 'b-dep': b_row}, failed={})
    monkeypatch.setattr(dep_observe, '_ask', lambda *_, **__: whole)
    assert main(['--refresh', str(path), '--index', 'a-dep=a-dep', '--index', 'b-dep=b-dep']) == 0
    assert sorted(read_observed(path)) == ['a-dep', 'b-dep']


def test_the_command_line_refuses_to_guess_what_it_was_asked_to_do(tmp_path: Path) -> None:
    """No mode, a malformed ``NAME=LOCATOR``, and a file with nothing to observe.

    Three different repairs, so three refusals rather than one silent no-op.
    """
    with pytest.raises(SystemExit):
        main([])
    empty = tmp_path / 'nothing.toml'
    assert main(['--refresh', str(empty)]) == 1
    assert main(['--refresh', str(empty), '--index', 'no-equals-sign']) == 1
    assert not empty.exists()
