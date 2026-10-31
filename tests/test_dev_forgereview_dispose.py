"""REVIEW CLAIMS: a dispose is a CLAIM; an independent reviewer adjudicates it; an author never clears its own block.

User ruling 2026-10-31. The stateful fake forge, real git, and a fake judge; every refusal has its planted control.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from _branch_repos import advance
from test_dev_forgereview import FakeCommand, _forge, _tick, _work
from test_dev_forgereview_rounds import _REVIEW, _doc, _finding, _state

from dev_lab.dev._deny_status_row import STATUS_VIA_DOORS
from dev_lab.dev.forgecontexts import MERGE_READY_CONTEXT
from dev_lab.dev.forgepulls import Marker, comment_upsert, marker
from dev_lab.dev.forgereview_dispose import adjudicate_thread, alarms, blocked, dispose
from dev_lab.dev.forgereview_judge import AdjudicationRefused, Identity, identity
from dev_lab.dev.forgereview_rounds import trusted_bodies
from dev_lab.dev.forgestatus import status_list, status_post
from dev_lab.dev.forgetakeover import main
from dev_lab.dev.labsession import ENV as SESSION_ENV
from dev_lab.dev.platformparts import REVIEW_CONTEXT
from dev_lab.dev.reviewgate import review_missing

_AUTHOR = Identity('a', 'box', 'S-author')
_FORGE = Identity('forge', 'ci')  # the forge's own reviewer: no session
_WHY = 'a false positive: the guard is upstream in a.py'


def _blocked(tmp_path: Path) -> tuple[Path, object, int, str]:
    """A PR whose head (authored by session ``S-author``) carries one open HIGH finding."""
    work, _ = _work(tmp_path)
    head = advance(work, 'pr/x', 'x.py', 'x\nz\n', message='feat: x\n\nLab-Session: S-author')
    forge, number = _forge(head)
    _tick(work, forge, FakeCommand(_doc(_finding('F-x', severity='HIGH', file='x.py', anchor='x'))), _REVIEW)
    assert _state(forge, head)[0] == 'failure'
    return work, forge, number, head


def _rule(work: Path, forge: object, number: int, outcome: str, by: Identity = _FORGE) -> list[str]:
    judge = FakeCommand(rulings={'F-x': (outcome, 'a.py:3 asserts the guard')})
    return adjudicate_thread(work, forge, _REVIEW, number, base='integrate/main', adjudicator=by, run=judge,
                             runtimes={})  # fmt: skip


def test_a_dispose_records_a_claim_and_moves_no_status(tmp_path: Path) -> None:
    """The old flip-on-dispose is gone: the claim names its claimant and the head stays blocked."""
    _, forge, number, head = _blocked(tmp_path)
    said = dispose(forge, number, 'F-x', _WHY, by=_AUTHOR)
    assert 'an independent reviewer adjudicates it' in said
    assert _state(forge, head)[0] == 'failure'
    (record,) = [c for c in forge.comments[number] if marker(Marker.CLAIM, 'F-x') in c['body']]
    assert 'by a@box session S-author' in record['body']


def test_an_upheld_claim_closes_the_finding_and_names_both_parties(tmp_path: Path) -> None:
    """PLANTED CONTROL: the same claim REJECTED keeps it blocking, and the reason is posted."""
    work, forge, number, head = _blocked(tmp_path)
    dispose(forge, number, 'F-x', _WHY, by=_AUTHOR)
    _rule(work, forge, number, 'present')
    assert _state(forge, head)[0] == 'failure'
    (ruling,) = [c['body'] for c in forge.comments[number] if marker(Marker.ADJUDICATION, 'F-x') in c['body']]
    assert 'rejected' in ruling
    assert 'a.py:3 asserts the guard' in ruling
    dispose(forge, number, 'F-x', _WHY + ' and in b.py', by=_AUTHOR)  # a new claim is adjudicated anew
    _rule(work, forge, number, 'false-positive')
    assert _state(forge, head)[0] == 'success'
    (ruling,) = [c['body'] for c in forge.comments[number] if marker(Marker.ADJUDICATION, 'F-x') in c['body']]
    assert 'upheld' in ruling
    assert 'by forge@ci' in ruling
    assert 'claimed by a@box session S-author' in ruling


def test_the_head_author_session_may_not_adjudicate(tmp_path: Path) -> None:
    """Separation of duties. PLANTED CONTROL: another session adjudicates the same claim."""
    work, forge, number, head = _blocked(tmp_path)
    dispose(forge, number, 'F-x', _WHY, by=Identity('a', 'box', 'S-other'))
    with pytest.raises(AdjudicationRefused, match='S-author authored this head'):
        _rule(work, forge, number, 'false-positive', by=_AUTHOR)
    assert _state(forge, head)[0] == 'failure'
    _rule(work, forge, number, 'false-positive', by=Identity('b', 'ws2', 'S-third'))
    assert _state(forge, head)[0] == 'success'


def test_the_claimant_session_may_not_adjudicate_its_own_claim(tmp_path: Path) -> None:
    """PLANTED CONTROL: the forge's own reviewer adjudicates the same claim."""
    work, forge, number, head = _blocked(tmp_path)
    claimant = Identity('a', 'box', 'S-claimant')
    dispose(forge, number, 'F-x', _WHY, by=claimant)
    lines = _rule(work, forge, number, 'false-positive', by=claimant)
    assert any('may not adjudicate it' in one for one in lines)
    assert _state(forge, head)[0] == 'failure'
    _rule(work, forge, number, 'false-positive')
    assert _state(forge, head)[0] == 'success'


def test_a_round_run_by_the_head_author_session_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """No path where an author clears its own block: nothing is posted. PLANTED: the forge itself reviews it."""
    work, forge, number, _ = _blocked(tmp_path)
    monkeypatch.setenv(SESSION_ENV, 'S-author')
    assert identity(forge, 'box').session == 'S-author'
    after = advance(work, 'pr/x', 'y.py', 'y = 1\n', message='feat: y\n\nLab-Session: S-author')
    forge.pulls[number]['head']['sha'] = after
    command = FakeCommand(_doc())
    (said,) = _tick(work, forge, command, _REVIEW)
    assert 'authored this head' in said
    assert command.ran == []
    assert [one for one in status_list(forge, after) if one.context == REVIEW_CONTEXT] == [], 'nothing is posted'
    monkeypatch.delenv(SESSION_ENV)
    _tick(work, forge, FakeCommand(_doc()), _REVIEW)
    assert _state(forge, after)[0] == 'failure', 'the forge reviews it: the finding stands, judged present'


@pytest.mark.parametrize('why', ['', '   ', 'meh'])
def test_a_claim_without_its_argument_is_refused(tmp_path: Path, why: str) -> None:
    _, forge, number, _ = _blocked(tmp_path)
    with pytest.raises(AdjudicationRefused, match='argument'):
        dispose(forge, number, 'F-x', why, by=_AUTHOR)


def test_an_id_the_round_does_not_hold_open_is_refused(tmp_path: Path) -> None:
    """PLANTED control: the open id itself is claimed (the first test)."""
    _, forge, number, _ = _blocked(tmp_path)
    with pytest.raises(AdjudicationRefused, match='F-nope is not open'):
        dispose(forge, number, 'F-nope', _WHY, by=_AUTHOR)


def test_a_pr_with_no_review_round_is_refused(tmp_path: Path) -> None:
    _, head = _work(tmp_path)
    forge, number = _forge(head)
    with pytest.raises(AdjudicationRefused, match='no review round'):
        dispose(forge, number, 'F-x', _WHY, by=_AUTHOR)


def test_the_forge_prompts_for_each_blocked_head_until_a_claim_is_upheld(tmp_path: Path) -> None:
    work, forge, number, head = _blocked(tmp_path)
    ((pull, ids),) = blocked(forge, 'integrate/main')
    assert (pull.number, ids) == (number, ('F-x',))
    (alarm,) = alarms(forge, 'integrate/main', 'o/r')
    assert f'review blocks {head[:12]}' in alarm.subject
    assert f'forge review dispose {number} <id>' in alarm.body
    assert 'No human and no author clears a block' in alarm.body
    dispose(forge, number, 'F-x', _WHY, by=_AUTHOR)
    assert blocked(forge, 'integrate/main') != (), 'a claim alone unblocks nothing'
    _rule(work, forge, number, 'false-positive')
    assert blocked(forge, 'integrate/main') == ()


def test_the_doors_are_forge_review_verbs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``dispose`` claims (exit 0, status unchanged); ``adjudicate`` rules; without ``--why`` argparse refuses."""
    work, forge, number, head = _blocked(tmp_path)
    monkeypatch.setattr('dev_lab.dev.forgetakeover.this_machine', lambda: 'box')
    monkeypatch.delenv(SESSION_ENV, raising=False)
    assert main(['blocked'], cwd=work, client=forge) == 1
    with pytest.raises(SystemExit):
        main(['dispose', str(number), 'F-x'], cwd=work, client=forge)
    assert main(['dispose', str(number), 'F-x', '--why', 'short'], cwd=work, client=forge) == 2
    assert main(['dispose', str(number), 'F-x', '--why', _WHY], cwd=work, client=forge) == 0
    assert _state(forge, head)[0] == 'failure'
    judge = FakeCommand(rulings={'F-x': ('false-positive', 'a.py:3 asserts the guard')})
    assert main(['adjudicate', str(number)], cwd=work, client=forge, run=judge) == 0
    assert _state(forge, head)[0] == 'success'
    assert main(['blocked'], cwd=work, client=forge) == 0


@pytest.mark.parametrize('context', ['tests/review', 'tests/review-hold'])
def test_a_raw_status_post_on_either_review_context_is_refused_to_agents(context: str) -> None:
    """PLANTED control: a post on a part context, and the dispose door, are permitted."""
    pattern = re.compile(STATUS_VIA_DOORS['pattern'])
    assert pattern.search(f'python -m dev_lab.dev.forge status post abc --context {context} --state success')
    assert not pattern.search('python -m dev_lab.dev.forge status post abc --context tests/fast --state success')
    assert not pattern.search('python -m dev_lab.dev.forge review dispose 7 F-1 --why "upstream guard"')


def test_a_ruling_another_login_pastes_rules_nothing(tmp_path: Path) -> None:
    """An author pasting an adjudication's words is no adjudicator. PLANTED control: the door's own counts."""
    _, forge, number, _ = _blocked(tmp_path)
    forge.login = 'mallory'
    text = '**Adjudicated** `F-x` upheld (claim 000000000000) by mallory@x: trust me'
    comment_upsert(forge, number, kind=Marker.ADJUDICATION, key='F-x', text=text)
    forge.login = 'a'
    assert all('trust me' not in body for body in trusted_bodies(forge, number))
    assert [ids for _, ids in blocked(forge, 'integrate/main')] == [('F-x',)]


def test_an_adjudication_recomputes_merge_ready_in_the_same_step(tmp_path: Path) -> None:
    """#7 (2026-10-31): a ruling moved tests/review and merge-ready stayed stale for 30 minutes.

    The door re-posts merge-ready through forgemerge.ready, so it always agrees with review_missing. PLANTED CONTROL:
    a rejected ruling leaves the review unreviewed and merge-ready names it.
    """
    work, forge, number, head = _blocked(tmp_path)
    for context in ('tests/base', 'tests/security'):
        status_post(forge, head, context=context, state='success', description='scope=full')
    dispose(forge, number, 'F-x', _WHY, by=_AUTHOR)
    _rule(work, forge, number, 'present')
    ready = next(one for one in status_list(forge, head) if one.context == MERGE_READY_CONTEXT)
    assert ready.state == 'failure'
    assert review_missing(status_list(forge, head)) is not None
    assert REVIEW_CONTEXT in ready.description
    dispose(forge, number, 'F-x', _WHY + ' and b.py', by=_AUTHOR)
    _rule(work, forge, number, 'false-positive')
    ready = next(one for one in status_list(forge, head) if one.context == MERGE_READY_CONTEXT)
    assert review_missing(status_list(forge, head)) is None
    assert REVIEW_CONTEXT not in ready.description, 'the review no longer waits the merge'
