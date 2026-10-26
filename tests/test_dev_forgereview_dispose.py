"""REVIEW DISPOSITION: only the door closes a blocking finding without a fix, and only with a reason.

The stateful fake forge and a fake review command; every refusal has its planted control.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from test_dev_forgereview import FakeCommand, _forge, _tick, _work
from test_dev_forgereview_rounds import _REVIEW, _doc, _finding, _state

from dev_lab.dev._deny_reviewstatus_row import REVIEW_STATUS_VIA_DOORS
from dev_lab.dev.forgepulls import Marker, comment_upsert, marker
from dev_lab.dev.forgereview_dispose import DisposeRefused, alarms, blocked, dispose
from dev_lab.dev.forgereview_rounds import disposition_text, trusted_bodies
from dev_lab.dev.forgetakeover import main


def _blocked(tmp_path: Path) -> tuple[object, int, str]:
    work, head = _work(tmp_path)
    forge, number = _forge(head)
    _tick(work, forge, FakeCommand(_doc(_finding('F-x', severity='HIGH', anchor='x'))), _REVIEW)
    assert _state(forge, head)[0] == 'failure'
    return forge, number, head


def test_a_disposition_with_its_reason_unblocks_the_reviewed_head(tmp_path: Path) -> None:
    forge, number, head = _blocked(tmp_path)
    said = dispose(forge, number, 'F-x', 'a false positive: the guard is upstream', host='box')
    assert said.endswith('tests/review success')
    assert _state(forge, head)[0] == 'success'
    (record,) = [c for c in forge.comments[number] if marker(Marker.DISPOSITION, 'F-x') in c['body']]
    assert 'by box: a false positive: the guard is upstream' in record['body']


@pytest.mark.parametrize('why', ['', '   ', 'meh'])
def test_a_disposition_without_a_reason_is_refused(tmp_path: Path, why: str) -> None:
    forge, number, head = _blocked(tmp_path)
    with pytest.raises(DisposeRefused, match='reason'):
        dispose(forge, number, 'F-x', why, host='box')
    assert _state(forge, head)[0] == 'failure'


def test_an_id_the_round_does_not_hold_open_is_refused(tmp_path: Path) -> None:
    """PLANTED control: the open id itself is disposed (the first test)."""
    forge, number, _ = _blocked(tmp_path)
    with pytest.raises(DisposeRefused, match='F-nope is not open'):
        dispose(forge, number, 'F-nope', 'a reason long enough', host='box')


def test_a_pr_with_no_review_round_is_refused(tmp_path: Path) -> None:
    _, head = _work(tmp_path)
    forge, number = _forge(head)
    with pytest.raises(DisposeRefused, match='no review round'):
        dispose(forge, number, 'F-x', 'a reason long enough', host='box')


def test_the_forge_prompts_the_integrator_for_each_blocked_head_until_it_is_disposed(tmp_path: Path) -> None:
    forge, number, head = _blocked(tmp_path)
    ((pull, ids),) = blocked(forge, 'integrate/main')
    assert (pull.number, ids) == (number, ('F-x',))
    (alarm,) = alarms(forge, 'integrate/main', 'o/r')
    assert f'review blocks {head[:12]}' in alarm.subject
    assert f'forge review dispose {number} <id>' in alarm.body
    assert 'a human is asked only when the integrator and the author disagree' in alarm.body
    dispose(forge, number, 'F-x', 'a false positive: the guard is upstream', host='box')
    assert blocked(forge, 'integrate/main') == ()


def test_the_door_is_the_forge_review_verb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``forge review dispose`` exits 0 and unblocks; without ``--why`` argparse refuses; ``blocked`` lists heads."""
    forge, number, head = _blocked(tmp_path)
    monkeypatch.setattr('dev_lab.dev.forgetakeover.this_machine', lambda: 'box')
    root = tmp_path / 'work'
    assert main(['blocked'], cwd=root, client=forge) == 1
    with pytest.raises(SystemExit):
        main(['dispose', str(number), 'F-x'], cwd=root, client=forge)
    assert main(['dispose', str(number), 'F-x', '--why', 'short'], cwd=root, client=forge) == 2
    assert main(['dispose', str(number), 'F-x', '--why', 'the guard is upstream'], cwd=root, client=forge) == 0
    assert _state(forge, head)[0] == 'success'
    assert main(['blocked'], cwd=root, client=forge) == 0


@pytest.mark.parametrize('context', ['tests/review', 'tests/review-hold'])
def test_a_raw_status_post_on_either_review_context_is_refused_to_agents(context: str) -> None:
    """PLANTED control: a post on a part context, and the dispose door, are permitted."""
    pattern = re.compile(REVIEW_STATUS_VIA_DOORS['pattern'])
    assert pattern.search(f'python -m dev_lab.dev.forge status post abc --context {context} --state success')
    assert not pattern.search('python -m dev_lab.dev.forge status post abc --context tests/fast --state success')
    assert not pattern.search('python -m dev_lab.dev.forge review dispose 7 F-1 --why "upstream guard"')


def test_a_disposition_another_login_writes_disposes_nothing(tmp_path: Path) -> None:
    """An author pasting a disposition's words is not the integrator. PLANTED control: the door's own counts."""
    forge, number, _ = _blocked(tmp_path)
    forge.login = 'mallory'
    comment_upsert(forge, number, kind=Marker.DISPOSITION, key='F-x', text=disposition_text('F-x', 'box', 'trust me'))
    forge.login = 'a'
    assert all('trust me' not in body for body in trusted_bodies(forge, number))
    assert [ids for _, ids in blocked(forge, 'integrate/main')] == [('F-x',)]
