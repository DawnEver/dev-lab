"""REVIEW ROUNDS: findings carried head to head by stable id, closed by a fix or a disposition, blocking while open.

Real git repositories and the stateful fake forge; the review command is a fake printing a findings document.
Every rule has its planted control: the same input one step away from the refused shape passes.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from _branch_repos import advance
from test_dev_forgereview import FakeCommand, _forge, _tick, _work

from dev_lab.dev.forgepulls import Marker, comment_upsert, marker
from dev_lab.dev.forgereview import RANGE_FIELD, REVIEW_CONTEXT, Review
from dev_lab.dev.forgereview_findings import Finding, Findings
from dev_lab.dev.forgereview_rounds import (
    FAMILY_MAX_ROUNDS,
    Ledger,
    context_summary,
    disposed,
    disposition_text,
    ledger_of,
    verdict,
)
from dev_lab.dev.forgereview_rounds import (
    advance as advance_round,
)
from dev_lab.dev.forgestatus import status_list

_REVIEW = Review(command=('reviewer', '--range', RANGE_FIELD))


def _finding(fid: str = 'F-000000000001', *, severity: str = 'MEDIUM', security: bool = False,
             file: str = 'x.txt', anchor: str = 'x') -> Finding:  # fmt: skip
    return Finding(fid, severity, security, 'occams-razor', file, anchor, f'{fid} summary', 'Bug')


def _doc(*findings: Finding) -> str:
    """A findings-output v3 document of *findings*, one ok reviewer."""
    rows = [
        {'id': one.id, 'severity': one.severity, 'security': one.security, 'rule': one.rule, 'file': one.file,
         'anchor': one.anchor, 'summary': one.summary, 'category': one.category, 'status': 'OPEN',
         'suggestion': '', 'detail': '', 'confidence': 'single', 'reviewers': [{'name': 'c', 'provider': 'p'}]}
        for one in findings
    ]  # fmt: skip
    return json.dumps({
        'schema_version': 3, 'range': 'a..b', 'profiles': ['c'],
        'reviewers': [{'name': 'c', 'provider': 'p', 'status': 'ok', 'dropped_findings': 0}], 'findings': rows,
    })  # fmt: skip


def _found(*findings: Finding) -> Findings:
    return Findings(3, 'a..b', ('c',), (), findings)


def _state(forge: object, sha: str) -> tuple[str, str]:
    latest = next(one for one in status_list(forge, sha) if one.context == REVIEW_CONTEXT)
    return latest.state, latest.description


# --- the ledger ----------------------------------------------------------------------------------------


def test_the_ledger_round_trips_through_its_comment_line_and_cannot_close_the_comment() -> None:
    hostile = _finding(anchor='a --> b')
    ledger = Ledger('h' * 40, 2, (hostile,))
    line = ledger.line()
    assert '-->' not in line.removesuffix(' -->'), 'the JSON may not close the HTML comment'
    assert ledger_of(['older', f'text\n{line}']) == ledger
    assert ledger_of(['no ledger here']) is None


def test_the_newest_ledger_wins_and_another_version_is_refused() -> None:
    old, new = Ledger('a' * 40, 1).line(), Ledger('b' * 40, 2).line()
    assert ledger_of([old, new]).round == 2
    with pytest.raises(ValueError, match='version 9'):
        ledger_of([new.replace('"version": 1', '"version": 9')])


# --- blocking -------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ('finding', 'state'),
    [
        (_finding(severity='HIGH'), 'failure'),
        (_finding(severity='LOW', security=True), 'failure'),
        (_finding(severity='MEDIUM'), 'success'),  # PLANTED control: below HIGH, not security
        (_finding(severity='LOW'), 'success'),
    ],
)
def test_an_open_high_or_security_finding_is_a_failure(finding: Finding, state: str) -> None:
    assert verdict(Ledger('h' * 40, 1, (finding,)), {}, 7)[0] == state


def test_a_disposed_blocking_finding_no_longer_blocks() -> None:
    high = _finding(severity='HIGH')
    ledger = Ledger('h' * 40, 1, (high,))
    state, said = verdict(ledger, {}, 7)
    assert state == 'failure'
    assert 'forge review dispose 7' in said
    assert verdict(ledger, {high.id: 'a false positive'}, 7)[0] == 'success'


def test_a_disposition_counts_only_under_its_own_keyed_marker() -> None:
    """PLANTED control: the same words quoted without the marker, or under another id's marker, dispose nothing."""
    text = disposition_text('F-1', 'box', 'the guard  is upstream')
    assert disposed([f'{marker(Marker.DISPOSITION, "F-1")}\n{text}']) == {'F-1': 'the guard is upstream'}
    assert disposed([text]) == {}
    assert disposed([f'{marker(Marker.DISPOSITION, "F-2")}\n{text}']) == {}


# --- rounds ---------------------------------------------------------------------------------------------


def _repo(tmp_path: Path) -> tuple[Path, str, str]:
    """A PR branch adding ``x.txt`` (``x``, ``y``) then rewriting it: (work, first head, second head)."""
    work, _ = _work(tmp_path)
    first = advance(work, 'pr/x', 'x.txt', 'x\ny\n')
    second = advance(work, 'pr/x', 'x.txt', 'y\nz\n')
    return work, first, second


def test_round_two_closes_a_finding_whose_anchor_is_gone_and_keeps_one_whose_anchor_stays(tmp_path: Path) -> None:
    work, first, second = _repo(tmp_path)
    gone, stays = _finding('F-1', anchor='x'), _finding('F-2', anchor='  y ')
    prior = Ledger(first, 1, (gone, stays))
    ledger = advance_round(work, second, f'{first}..{second}', prior, _found())
    assert ledger.round == 2
    assert [one.id for one in ledger.open] == ['F-2']
    assert [fid for fid, _ in ledger.closed] == ['F-1']


def test_a_later_round_raises_no_new_non_high_finding_on_a_line_it_did_not_add(tmp_path: Path) -> None:
    """No moving goalposts. PLANTED controls: the same MEDIUM on an added line, and a HIGH anywhere, are raised."""
    work, first, second = _repo(tmp_path)
    reviewed = f'{first}..{second}'
    old_line = _finding('F-old', anchor='y')  # y was there before this round
    new_line = _finding('F-new', anchor='z')  # z is what this round added
    high = _finding('F-high', severity='HIGH', anchor='y')
    ledger = advance_round(work, second, reviewed, Ledger(first, 1), _found(old_line, new_line, high))
    assert [one.id for one in ledger.open] == ['F-new', 'F-high']
    first_round = advance_round(work, second, reviewed, None, _found(old_line))
    assert [one.id for one in first_round.open] == ['F-old'], 'round 1 reads the whole change'


def test_past_the_cap_blocking_findings_stay_and_the_rest_are_deferred(tmp_path: Path) -> None:
    work, first, second = _repo(tmp_path)
    high, medium = _finding('F-h', severity='HIGH', anchor='y'), _finding('F-m', anchor='y')
    ledger = advance_round(work, second, f'{first}..{second}', Ledger(first, 3, (high, medium)), None)
    assert [one.id for one in ledger.open] == ['F-h']
    assert [one.id for one in ledger.deferred] == ['F-m']


def test_the_context_summary_names_what_changed_why_and_where(tmp_path: Path) -> None:
    work, _ = _work(tmp_path)
    (work / 'src' / 'pkg' / 'layer').mkdir(parents=True)
    (work / 'docs').mkdir()
    base = advance(work, 'pr/x', 'src/pkg/layer/a.py', 'a = 1\n')
    head = advance(work, 'pr/x', 'docs/b.md', '# b\n')
    text = context_summary(work, f'{base}~1..{head}')
    assert '2 file(s), +2/-0' in text
    assert '`src/pkg/layer` (1)' in text
    assert '`docs` (1)' in text
    assert '**Why** (the commits):\n- docs/b.md\n- src/pkg/layer/a.py' in text  # the subjects, newest first


# --- through the forge ----------------------------------------------------------------------------------


def test_a_fix_pushed_after_a_blocking_round_closes_it_and_the_head_succeeds(tmp_path: Path) -> None:
    work, head = _work(tmp_path)
    forge, number = _forge(head)
    high = _finding('F-x', severity='HIGH', file='x.py', anchor='x')
    _tick(work, forge, FakeCommand(_doc(high)), _REVIEW)
    assert _state(forge, head)[0] == 'failure'
    fixed = advance(work, 'pr/x', 'x.py', 'fixed\n')
    forge.pulls[number]['head']['sha'] = fixed
    command = FakeCommand(_doc())
    _tick(work, forge, command, _REVIEW)
    state, said = _state(forge, fixed)
    assert (state, 'review round 2' in said) == ('success', True)
    ((argv, _),) = command.ran
    assert argv[-1] == f'{head}..{fixed}', 'round 2 reads only what the branch added since the reviewed head'
    body = forge.comments[number][-1]['body']
    assert '### Closed this round' in body
    assert 'What changed' not in body, 'only round 1 carries the context summary'


def test_a_disposition_on_the_pr_unblocks_the_next_round(tmp_path: Path) -> None:
    work, head = _work(tmp_path)
    forge, number = _forge(head)
    high = _finding('F-x', severity='HIGH', anchor='x')
    _tick(work, forge, FakeCommand(_doc(high)), _REVIEW)
    comment_upsert(forge, number, kind=Marker.DISPOSITION, key='F-x', text=disposition_text('F-x', 'box', 'upstream'))
    after = advance(work, 'pr/x', 'y.txt', 'y\n')
    forge.pulls[number]['head']['sha'] = after
    _tick(work, forge, FakeCommand(_doc(high)), _REVIEW)
    assert _state(forge, after)[0] == 'success'


def test_past_max_rounds_no_command_runs_and_one_follow_up_issue_takes_the_rest(tmp_path: Path) -> None:
    work, head = _work(tmp_path)
    forge, number = _forge(head)
    review = Review(command=_REVIEW.command, max_rounds=1)
    high, medium = _finding('F-h', severity='HIGH', file='x.py', anchor='x'), _finding('F-m', file='x.py', anchor='x')
    _tick(work, forge, FakeCommand(_doc(high, medium)), review)
    after = advance(work, 'pr/x', 'y.txt', 'y\n')
    forge.pulls[number]['head']['sha'] = after
    command = FakeCommand(_doc())
    _tick(work, forge, command, review)
    assert command.ran == [], 'past the cap, no reviewer runs'
    assert _state(forge, after)[0] == 'failure', 'the blocking finding is re-checked and still open'
    (issue,) = [one for one in forge.issues_by_number.values() if one['title'].startswith('review follow-up')]
    assert 'F-m' in issue['body']
    assert 'F-h' not in issue['body']
    assert FAMILY_MAX_ROUNDS == Review().max_rounds == 3
