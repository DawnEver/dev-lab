"""SESSION-HEARS-ITS-PRS: a session hears every red, green, merge and close on its own PRs, in any repository.

User ruling 2026-11-11: lab-commons #158 went red and nothing told the session, because the push journal lived
in another checkout. Each test plants its control: the same red on a PR that is NOT the session's.
"""

from __future__ import annotations

import io
import json
from typing import TYPE_CHECKING

import pytest
from _branch_repos import clone_pair
from _forge_fake import git_out
from _forge_state import FORGE, StateForge

from dev_lab.dev import forgewatch, pushstop, pushwatch, sessionprs
from dev_lab.dev.forgestatus import status_post

if TYPE_CHECKING:
    from pathlib import Path

SHA = 'a' * 40
NEWER = 'b' * 40


def _post(forge: StateForge, sha: str, context: str, state: str) -> None:
    status_post(forge, sha, context=context, state=state, description=f'{context} {state}')


def _opened(forge: StateForge, capsys: pytest.CaptureFixture[str], session: str = 's1', *, sha: str = SHA) -> int:
    """A PR the session opened through ``forge pr create``, recorded by the PostToolUse hook from its output."""
    number = forge.add_pull('pr/x', 'main', sha=sha)
    url = forge.pulls[number]['html_url']
    payload = {
        'hook_event_name': 'PostToolUse',
        'session_id': session,
        'tool_input': {'command': 'py -m dev_lab.dev.forge pr create --title t --head pr/x --base main'},
        'tool_response': {'stdout': f'#{number} [open] t  {url}\n', 'stderr': ''},
    }
    capsys.readouterr()
    assert sessionprs.main([], stdin=io.StringIO(json.dumps(payload))) == 0
    said = json.loads(capsys.readouterr().out)['hookSpecificOutput']['additionalContext']
    assert sessionprs.watch_session_command(session) in said, 'the opened PR names the one watch to arm'
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


def _stop(forge: StateForge, tmp_path: Path, *, session: str = 's1', again: bool = False) -> dict | None:
    payload = {'hook_event_name': 'Stop', 'cwd': str(tmp_path), 'session_id': session, 'stop_hook_active': again}
    out = io.StringIO()
    code = pushstop.main(
        [], stdin=io.StringIO(json.dumps(payload)), processes=lambda: (), client=lambda _r: forge,
        clients=lambda _f: forge, out=out,
    )  # fmt: skip
    assert code == 0
    return json.loads(out.getvalue()) if out.getvalue().strip() else None


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


def test_a_closed_pr_is_reported_closed_and_another_session_hears_nothing(
    capsys: pytest.CaptureFixture[str],
) -> None:
    forge = StateForge()
    number = _opened(forge, capsys)
    _watch(forge, 'other')
    assert _watch(forge, 'other')[1] == ['session other: no open PR left'], 'PLANTED CONTROL: not its PR'
    forge.pulls[number]['state'] = 'closed'
    assert _watch(forge)[1][0] == f'{FORGE.identity}#{number} closed'


def test_a_red_session_pr_blocks_every_stop_until_acknowledged_or_a_newer_head(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    forge = StateForge()
    number = _opened(forge, capsys)
    _post(forge, SHA, 'tests/base', 'error')
    block = _stop(forge, tmp_path)
    assert block is not None
    assert block['decision'] == 'block'
    assert forge.pulls[number]['html_url'] in block['reason']
    assert 'tests/base error' in block['reason']
    assert _stop(forge, tmp_path, again=True) is not None, 'a red blocks until it is answered, not once'
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
    assert _stop(forge, tmp_path) is None, 'an acknowledged red head lets the turn end'
    forge.pulls[number]['head']['sha'] = NEWER
    _post(forge, NEWER, 'tests/base', 'failure')
    assert _stop(forge, tmp_path) is not None, 'a newer head is judged afresh: the old reason does not cover it'
    _post(forge, NEWER, 'tests/base', 'success')
    assert _stop(forge, tmp_path) is None
    capsys.readouterr()


def test_a_red_head_that_is_no_session_pr_is_not_blocked_on(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """The integrate/main head a session pushed, and a red PR another session opened, never hold this turn."""
    _, work = clone_pair(tmp_path)
    head = git_out(work, 'rev-parse', 'HEAD')
    pushwatch.record(work, 's1', 'refs/heads/integrate/main', head)
    forge = StateForge()
    _post(forge, head, 'tests/base', 'failure')
    foreign = _opened(forge, capsys, 'other')
    _post(forge, SHA, 'tests/base', 'failure')
    payload = {'hook_event_name': 'Stop', 'cwd': str(work), 'session_id': 's1'}
    out = io.StringIO()
    pushstop.main([], stdin=io.StringIO(json.dumps(payload)), processes=lambda: (), client=lambda _r: forge,
                  clients=lambda _f: forge, out=out)  # fmt: skip
    assert out.getvalue() == ''
    assert _stop(forge, tmp_path, session='other') is not None, f'PLANTED CONTROL: #{foreign} is red for its owner'


def test_a_pushed_branch_becomes_its_open_pr_and_is_watched() -> None:
    forge = StateForge()
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
