"""REVIEW CLAIMS: a dispose is a CLAIM; an independent reviewer adjudicates it; an author never clears its own block.

User ruling 2026-10-31. The stateful fake forge, real git, and a fake judge; every refusal has its planted control.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from _branch_repos import advance
from _forge_state import StateForge
from test_dev_forgereview import FakeCommand, _forge, _tick, _work
from test_dev_forgereview_rounds import _REVIEW, _doc, _finding, _state

from dev_lab.dev._deny_status_row import STATUS_VIA_DOORS
from dev_lab.dev.forgecontexts import MERGE_READY_CONTEXT
from dev_lab.dev.forgepulls import Marker, comment_upsert, marker
from dev_lab.dev.forgereview_dispose import adjudicate_thread, alarms, blocked, dispose
from dev_lab.dev.forgereview_judge import AdjudicationRefused, Identity, identity, self_review
from dev_lab.dev.forgereview_rounds import trusted_bodies
from dev_lab.dev.forgestatus import status_list, status_post
from dev_lab.dev.forgetakeover import main, pull_for, takeover
from dev_lab.dev.forgework import ACTIONS_BOT, GITEA_ACTIONS_LOGIN
from dev_lab.dev.labsession import ENV as SESSION_ENV
from dev_lab.dev.platformparts import REVIEW_CONTEXT
from dev_lab.dev.reviewgate import forge_posted, review_missing

_AUTHOR = Identity('a', 'box', 'S-author')
_FORGE = Identity('forge', 'ci', ci=True)  # the forge's own reviewer: no session
_WHY = 'a false positive: the guard is upstream in a.py'


_BASE = 'integrate/main'


def _blocked(tmp_path: Path, *, login: str = 'a') -> tuple[Path, object, int, str]:
    """A PR whose head (authored by session ``S-author``) carries one open HIGH finding, reviewed as *login*."""
    work, _ = _work(tmp_path)
    head = advance(work, 'pr/x', 'x.py', 'x\nz\n', message='feat: x\n\nLab-Session: S-author')
    forge, number = _forge(head)
    forge.login = login
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


@pytest.mark.parametrize(
    'who', [_AUTHOR, Identity('b', 'ws2', 'S-third'), Identity('a', 'box', 'S-claimant'), Identity('a', 'box')]
)
def test_no_session_rules_only_the_forge_does(tmp_path: Path, who: Identity) -> None:
    """#11 round 2 (F-e97824b7b801): the author, a third session, the claimant, an unset LAB_SESSION -- all refused.

    PLANTED CONTROL: the forge's CI identity rules on the same claim.
    """
    work, forge, number, head = _blocked(tmp_path)
    dispose(forge, number, 'F-x', _WHY, by=Identity('a', 'box', 'S-claimant'))
    with pytest.raises(AdjudicationRefused, match='a ruling comes only from the forge'):
        _rule(work, forge, number, 'false-positive', by=who)
    assert not any(marker(Marker.ADJUDICATION, 'F-x') in c['body'] for c in forge.comments[number])
    assert _state(forge, head)[0] == 'failure'
    _rule(work, forge, number, 'false-positive')
    assert _state(forge, head)[0] == 'success'


def test_the_ci_identity_is_the_tokens_login_never_a_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    """The Actions bot login is CI whatever the env says. PLANTED CONTROL: a developer login with a CI-looking env."""
    forge = StateForge()
    monkeypatch.setenv('GITHUB_ACTIONS', 'true')
    monkeypatch.delenv(SESSION_ENV, raising=False)
    assert not identity(forge, 'box').ci, 'a variable never makes a developer the forge'
    forge.login = ACTIONS_BOT
    assert identity(forge, 'runner').ci
    forge.login = 'a'
    assert identity(forge, 'box', serving=True).ci, 'the serve process passes it from its own code path'


def test_an_unset_session_may_not_self_review_and_the_ci_identity_may() -> None:
    """Fail closed: '' is no identity, never one 'different' from the author's. PLANTED CONTROL: the CI identity."""
    authors = frozenset({'S-author'})
    with pytest.raises(AdjudicationRefused, match='names no session'):
        self_review(Identity('a', 'box'), authors, 'reviewing #1')
    with pytest.raises(AdjudicationRefused, match='names no session'):
        self_review(Identity('a', 'box', '   '.strip()), authors, 'reviewing #1')
    self_review(Identity(ACTIONS_BOT, 'runner', ci=True), authors, 'reviewing #1')
    self_review(Identity('b', 'ws2', 'S-other'), authors, 'reviewing #1')


@pytest.mark.parametrize('by', [Identity('a', 'box'), Identity('', 'box', 'S-x')])
def test_a_claim_without_a_session_or_login_is_refused(tmp_path: Path, by: Identity) -> None:
    """PLANTED CONTROL: the same claim with a session and login is recorded (the first test)."""
    _, forge, number, _ = _blocked(tmp_path)
    with pytest.raises(AdjudicationRefused, match='names its claimant'):
        dispose(forge, number, 'F-x', _WHY, by=by)
    assert not any(marker(Marker.CLAIM, 'F-x') in c['body'] for c in forge.comments[number])


def test_a_dry_run_adjudication_prints_the_verdict_and_posts_nothing(tmp_path: Path) -> None:
    """Any session may dry-run. PLANTED CONTROL: the forge's run of the same claim posts and rules."""
    work, forge, number, head = _blocked(tmp_path)
    dispose(forge, number, 'F-x', _WHY, by=Identity('a', 'box', 'S-claimant'))
    judge = FakeCommand(rulings={'F-x': ('false-positive', 'a.py:3 asserts the guard')})
    lines = adjudicate_thread(work, forge, _REVIEW, number, base='integrate/main', adjudicator=_AUTHOR, run=judge,
                              runtimes={}, dry_run=True)  # fmt: skip
    assert any('dry run, not posted' in one and 'upheld' in one for one in lines)
    assert not any(marker(Marker.ADJUDICATION, 'F-x') in c['body'] for c in forge.comments[number])
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
    assert main(['dispose', str(number), 'F-x', '--why', _WHY], cwd=work, client=forge) == 2, 'no session: refused'
    monkeypatch.setenv(SESSION_ENV, 'S-claimant')
    assert main(['dispose', str(number), 'F-x', '--why', 'short'], cwd=work, client=forge) == 2
    assert main(['dispose', str(number), 'F-x', '--why', _WHY], cwd=work, client=forge) == 0
    assert _state(forge, head)[0] == 'failure'
    judge = FakeCommand(rulings={'F-x': ('false-positive', 'a.py:3 asserts the guard')})
    assert main(['adjudicate', str(number)], cwd=work, client=forge, run=judge) == 2, 'a session never rules'
    assert main(['adjudicate', str(number), '--dry-run'], cwd=work, client=forge, run=judge) == 0
    assert _state(forge, head)[0] == 'failure'
    monkeypatch.setattr('dev_lab.dev.forgereview_judge.CI_LOGINS', frozenset({forge.login}))  # the forge's token
    monkeypatch.delenv(SESSION_ENV)  # the forge's job runs in no session
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


def test_an_adjudication_recomputes_merge_ready_in_the_same_step(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#7 (2026-10-31): a ruling moved tests/review and merge-ready stayed stale for 30 minutes.

    The door re-posts merge-ready through forgemerge.ready, so it always agrees with review_missing. PLANTED CONTROL:
    a rejected ruling leaves the review unreviewed and merge-ready names it.
    """
    work, forge, number, head = _blocked(tmp_path, login=GITEA_ACTIONS_LOGIN)  # the forge's round is its job's
    run_id, _ = forge.add_run(head)
    monkeypatch.setenv('GITEA_ACTIONS', 'true')  # the rulings run as that job: tests/review names its run
    monkeypatch.setenv('GITHUB_RUN_ID', str(run_id))
    for context in ('tests/base', 'tests/security'):
        status_post(forge, head, context=context, state='success', description='scope=full')
    forge.login = 'a'  # the claimant
    dispose(forge, number, 'F-x', _WHY, by=_AUTHOR)
    forge.login = GITEA_ACTIONS_LOGIN  # the forge's job rules: Gitea records its tests/review as the Actions ghost
    _rule(work, forge, number, 'present')
    ready = next(one for one in status_list(forge, head) if one.context == MERGE_READY_CONTEXT)
    assert ready.state == 'failure'
    assert review_missing(status_list(forge, head), forge_posted(forge, head, base=_BASE)) is not None
    assert REVIEW_CONTEXT in ready.description
    forge.login = 'a'
    dispose(forge, number, 'F-x', _WHY + ' and b.py', by=_AUTHOR)
    forge.login = GITEA_ACTIONS_LOGIN
    _rule(work, forge, number, 'false-positive')
    ready = next(one for one in status_list(forge, head) if one.context == MERGE_READY_CONTEXT)
    assert review_missing(status_list(forge, head), forge_posted(forge, head, base=_BASE)) is None
    assert REVIEW_CONTEXT not in ready.description, 'the review no longer waits the merge'


def test_an_author_claiming_as_fake1_and_taking_over_as_fake2_never_reaches_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D11, F-4eee841cf16c: LAB_SESSION is the author's to set, so the takeover moves no status at all.

    PLANTED CONTROL: the forge's own round on the same head, judging the same claim, does reach success.
    """
    work, forge, number, _ = _blocked(tmp_path)
    monkeypatch.setenv(SESSION_ENV, 'fake1')
    assert main(['dispose', str(number), 'F-x', '--why', _WHY], cwd=work, client=forge) == 0
    after = advance(work, 'pr/x', 'y.py', 'y = 1\n', message='feat: y\n\nLab-Session: S-author')
    forge.pulls[number]['head']['sha'] = after
    monkeypatch.setenv(SESSION_ENV, 'fake2')
    judge = FakeCommand(_doc(), rulings={'F-x': ('false-positive', 'a.py:3 asserts the guard')})
    takeover(work, forge, _REVIEW, after, pull=pull_for(forge, after), base='integrate/main', host='box', run=judge)
    assert all(one.context != REVIEW_CONTEXT for one in status_list(forge, after)), 'advisory: no status'
    assert review_missing(status_list(forge, after), lambda status: status.creator == forge.login) is not None
    (review,) = [c['body'] for c in forge.comments[number] if marker(Marker.REVIEW, after) in c['body']]
    assert 'Emergency takeover' in review
    monkeypatch.delenv(SESSION_ENV)
    _tick(work, forge, judge, _REVIEW)  # the forge serve round
    assert _state(forge, after)[0] == 'success'
    assert review_missing(status_list(forge, after), lambda status: status.creator == forge.login) is None
