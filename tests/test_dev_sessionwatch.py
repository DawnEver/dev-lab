"""TASK-HEARS-ITS-FORGE-EVENTS: a session hears every red, green, merge and close on its own PRs, in any repository.

User ruling 2026-11-11: lab-commons #158 went red and nothing told the session, because the push journal lived
in another checkout. Each test plants its control: the same red on a PR that is NOT the session's.
"""

from __future__ import annotations

import pytest
from _forge_state import FORGE, StateForge

from dev_lab.dev import forgewatch, sessionprs
from dev_lab.dev.forgestatus import status_post

SHA = 'a' * 40
NEWER = 'b' * 40


def _post(forge: StateForge, sha: str, context: str, state: str) -> None:
    status_post(forge, sha, context=context, state=state, description=f'{context} {state}')


def _opened(forge: StateForge, capsys: pytest.CaptureFixture[str], session: str = 's1', *, sha: str = SHA) -> int:
    """A PR the session opened: the door records it."""
    number = forge.add_pull('pr/x', 'main', sha=sha)
    assert sessionprs.record_opened(FORGE, number, branch='pr/x', sha=sha, env={'CLAUDE_CODE_SESSION_ID': session})
    capsys.readouterr()
    return number


def _watch(forge: StateForge, session: str = 's1', *, posts: list | None = None) -> tuple[int, list[str]]:
    said: list[str] = []
    script = list(posts or [])

    def sleep(_s: float) -> None:
        if script:
            script.pop(0)()

    code = forgewatch.watch_session(
        session, clients=lambda _f: forge, say=said.append, every_s=0, deadline_s=60, clock=lambda: 0.0, sleep=sleep
    )
    return code, said


def _reds(forge: StateForge, session: str = 's1') -> list[str]:
    """The session's red PR heads no ``--ack`` answers (:func:`forgewatch.unacknowledged_reds`)."""
    return forgewatch.unacknowledged_reds(session, clients=lambda _f: forge)


def _merge(forge: StateForge, number: int) -> None:
    forge.pulls[number].update(state='closed', merged=True)


def test_a_red_then_green_then_merge_is_reported_once_each_and_the_watch_ends(
    capsys: pytest.CaptureFixture[str],
) -> None:
    forge = StateForge()
    number = _opened(forge, capsys)
    key = f'{FORGE.identity}#{number}'
    _post(forge, SHA, 'tests/base', 'failure')
    code, said = _watch(forge, posts=[
        lambda: _post(forge, SHA, 'tests/base', 'failure'),  # unchanged: no line
        lambda: _post(forge, SHA, 'tests/base', 'success'),
        lambda: _merge(forge, number),
    ])  # fmt: skip
    assert code == 0
    assert said == [
        f'{key} {SHA[:12]} tests/base failure tests/base failure',
        f'{key} {SHA[:12]} green',
        f'{key} merged',
        'session s1: no open PR left',
    ]
    assert _watch(forge)[1] == ['session s1: no open PR left'], 'a merge is reported once, never again'


def test_a_row_its_failed_job_posted_error_streams_red_and_an_absent_row_streams_nothing(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """claude-code-config #6 (2026-11-13): an unreachable windows job read pending, so the stream never said it.

    The job now posts the row ``error`` (jobparts); PLANTED CONTROL: the row absent (``pending``) says nothing.
    """
    forge = StateForge()
    number = _opened(forge, capsys)
    key = f'{FORGE.identity}#{number}'
    status_post(forge, SHA, context='tests/base@windows', state='pending', description='absent: no job settled')
    code, said = _watch(forge, posts=[
        lambda: status_post(forge, SHA, context='tests/base@windows', state='error', description='unreachable: npm'),
        lambda: _merge(forge, number),
    ])  # fmt: skip
    assert code == 0
    assert said[0] == f'{key} {SHA[:12]} tests/base@windows error unreachable: npm', said
    assert not any('absent' in line for line in said), 'an absent row is not a red'


def test_a_closed_pr_is_reported_closed_and_another_session_hears_nothing(
    capsys: pytest.CaptureFixture[str],
) -> None:
    forge = StateForge()
    number = _opened(forge, capsys)
    _watch(forge, 'other')
    assert _watch(forge, 'other')[1] == ['session other: no open PR left'], 'PLANTED CONTROL: not its PR'
    forge.pulls[number]['state'] = 'closed'
    assert _watch(forge)[1][0] == f'{FORGE.identity}#{number} closed'


def test_a_red_session_pr_stands_until_acknowledged_or_a_newer_head(capsys: pytest.CaptureFixture[str]) -> None:
    forge = StateForge()
    number = _opened(forge, capsys)
    _post(forge, SHA, 'tests/base', 'error')
    [red] = _reds(forge)
    assert forge.pulls[number]['html_url'] in red
    assert 'tests/base error' in red
    with pytest.raises(SystemExit):
        forgewatch.session_main(
            ['--session', 's1', '--ack', str(number)], clients=lambda _f: forge
        )  # no reason: refused
    assert (
        forgewatch.session_main(
            ['--session', 's1', '--ack', str(number), '--reason', 'flaky host, rerun queued'], clients=lambda _f: forge
        )
        == 0
    )
    assert _reds(forge) == [], 'an acknowledged red head stands answered'
    forge.pulls[number]['head']['sha'] = NEWER
    _post(forge, NEWER, 'tests/base', 'failure')
    assert _reds(forge), 'a newer head is judged afresh: the old reason does not cover it'
    _post(forge, NEWER, 'tests/base', 'success')
    assert _reds(forge) == []
    capsys.readouterr()


def test_a_red_pr_another_session_opened_is_not_this_sessions_red(capsys: pytest.CaptureFixture[str]) -> None:
    forge = StateForge()
    foreign = _opened(forge, capsys, 'other')
    _post(forge, SHA, 'tests/base', 'failure')
    assert _reds(forge) == []
    assert _reds(forge, 'other'), f'PLANTED CONTROL: #{foreign} is red for its owner'


def test_a_pushed_branch_becomes_its_open_pr_and_is_watched() -> None:
    forge = StateForge()
    forge.branches['pr/y'] = False
    sessionprs.record_push('s1', FORGE, 'pr/y', SHA)
    assert _watch(forge)[1] == ['session s1: no open PR left'], 'a branch with no PR has nothing to watch'
    number = forge.add_pull('pr/y', 'main', sha=SHA)
    _post(forge, SHA, 'ci/lint', 'failure')
    _, said = _watch(forge, posts=[lambda: _merge(forge, number)])
    assert said[0] == f'{FORGE.identity}#{number} {SHA[:12]} ci/lint failure ci/lint failure'
    assert list(sessionprs.rows('s1')) == [f'{FORGE.identity}#{number}'], 'the branch row became the PR row'


def test_forge_watch_with_session_routes_to_the_session_watch(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[list[str]] = []
    monkeypatch.setattr(forgewatch, 'session_main', lambda argv: seen.append(argv) or 0)
    assert forgewatch.main(['--session', 's1', '--stream']) == 0
    assert seen == [['--session', 's1', '--stream']]


@pytest.mark.parametrize('named', ['url', 'key'])
def test_a_red_is_acknowledged_by_its_pr_url_or_its_key(capsys: pytest.CaptureFixture[str], named: str) -> None:
    """The URL a red line prints is normalized to the ``<host>/<owner>/<repo>#<number>`` key."""
    forge = StateForge()
    number = _opened(forge, capsys)
    _post(forge, SHA, 'tests/base', 'failure')
    assert _reds(forge), 'PLANTED CONTROL: unanswered, the red stands'
    given = forge.pulls[number]['html_url'] if named == 'url' else f'{FORGE.identity}#{number}'
    args = ['--session', 's1', '--ack', given, '--reason', 'stands on purpose']
    assert forgewatch.session_main(args, clients=lambda _f: forge) == 0
    assert _reds(forge) == []
    capsys.readouterr()


def test_a_url_of_another_repository_names_no_session_pr(capsys: pytest.CaptureFixture[str]) -> None:
    """PLANTED CONTROL: the same PR number under another repository is not this session's PR."""
    forge = StateForge()
    number = _opened(forge, capsys)
    args = ['--session', 's1', '--ack', f'https://{FORGE.host}/o/other/pulls/{number}', '--reason', 'x']
    assert forgewatch.session_main(args, clients=lambda _f: forge) == 2
    capsys.readouterr()


def _watch_until_deadline(forge: StateForge, session: str = 's1', *, posts: list | None = None) -> list[str]:
    """One watch whose clock passes its deadline once *posts* are spent: a re-armable run that ends."""
    said: list[str] = []
    script, now = list(posts or []), [0.0]

    def sleep(_s: float) -> None:
        if script:
            script.pop(0)()
        else:
            now[0] = 120.0

    forgewatch.watch_session(
        session, clients=lambda _f: forge, say=said.append, every_s=0, deadline_s=60, clock=lambda: now[0], sleep=sleep
    )
    return said


def test_a_re_armed_watch_never_re_reports_a_state_the_session_already_heard(
    capsys: pytest.CaptureFixture[str],
) -> None:
    forge = StateForge()
    number = _opened(forge, capsys)
    key = f'{FORGE.identity}#{number}'
    _post(forge, SHA, 'tests/base', 'failure')
    first = _watch_until_deadline(forge)
    assert f'{key} {SHA[:12]} tests/base failure tests/base failure' in first
    assert _watch_until_deadline(forge) == ['session s1: deadline, 1 PR(s) still open'], 'heard once per session'
    _post(forge, SHA, 'tests/base', 'success')
    assert f'{key} {SHA[:12]} green' in _watch_until_deadline(forge), 'PLANTED CONTROL: a new state is heard'


def test_green_waits_for_every_required_context_to_end_in_success(capsys: pytest.CaptureFixture[str]) -> None:
    """A head whose only posted test status is green is not green while the required tests/base is absent/pending."""
    forge = StateForge()
    number = _opened(forge, capsys)
    green = f'{FORGE.identity}#{number} {SHA[:12]} green'
    _post(forge, SHA, 'tests/security', 'success')
    assert green not in _watch_until_deadline(forge), 'tests/base not posted yet'
    _post(forge, SHA, 'tests/base', 'pending')
    assert green not in _watch_until_deadline(forge), 'tests/base still running'
    _post(forge, SHA, 'tests/base', 'success')
    assert green in _watch_until_deadline(forge), 'PLANTED CONTROL: every required context ended in success'


# ------------------------------------------------- a branch row closes with its PR, or because none can come


def test_a_branch_row_whose_pr_merged_unseen_closes_and_is_no_open_pr() -> None:
    """A break-glass merge closed the PR before any watch resolved the pushed branch to it."""
    forge = StateForge()
    sessionprs.record_push('s1', FORGE, 'pr/z', SHA)
    number = forge.add_pull('pr/z', 'main', sha=SHA)
    _merge(forge, number)
    code, said = _watch(forge)
    assert code == 0
    assert said == [f'{FORGE.identity}#{number} merged', 'session s1: no open PR left']
    assert not sessionprs.open_rows('s1')
    other = forge.add_pull('pr/w', 'main', sha=NEWER)
    sessionprs.record_pr('s1', FORGE, other, branch='pr/w', sha=NEWER)
    assert sessionprs.open_rows('s1'), 'PLANTED CONTROL: a recorded open PR is open'


def test_a_branch_row_of_a_protected_branch_closes_with_its_reason() -> None:
    """A push to the integration branch itself, recorded before such a push stopped being recorded."""
    forge = StateForge()
    forge.branches['integrate/main'] = True
    sessionprs.record_push('s1', FORGE, 'integrate/main', SHA)
    code, said = _watch(forge)
    assert code == 0
    key = f'{FORGE.identity}@integrate/main'
    assert said[0].startswith(f'{key} closed: ')
    (row,) = sessionprs.rows('s1').values()
    assert row.done == 'closed'
    assert 'protected' in row.reason
    assert not sessionprs.open_rows('s1')


def test_a_branch_row_whose_branch_is_gone_closes_and_a_live_one_waits_as_no_open_pr() -> None:
    forge = StateForge()
    forge.branches['pr/live'] = False
    sessionprs.record_push('s1', FORGE, 'pr/gone', SHA)
    sessionprs.record_push('s1', FORGE, 'pr/live', SHA)
    code, said = _watch(forge)
    assert code == 0
    assert said[0].startswith(f'{FORGE.identity}@pr/gone closed: ')
    table = sessionprs.rows('s1')
    assert table[f'{FORGE.identity}@pr/gone'].done == 'closed'
    assert table[f'{FORGE.identity}@pr/live'].done == '', 'PLANTED CONTROL: a live branch may still get its PR'
    assert not sessionprs.open_rows('s1'), 'a branch with no PR is no open PR'
