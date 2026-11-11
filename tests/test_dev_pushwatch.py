"""PUSHED-HEAD-IS-WATCHED: a pushed head is watched to its verdict -- armed as a Monitor, advised, never blocked."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
from _branch_repos import clone_pair
from _forge_fake import git_out, run_git
from _forge_state import StateForge

from dev_lab.dev import forgecli, netverb, pushstop, pushwatch
from dev_lab.dev.forgestatus import status_post
from dev_lab.dev.forgewatch import watch
from dev_lab.dev.pushwatch import RULE, pushed_ref, reminder, watch_command, watched


def _work(tmp_path: Path) -> tuple[Path, str]:
    _, work = clone_pair(tmp_path)
    return work, git_out(work, 'rev-parse', 'HEAD')


def _post(forge: StateForge, sha: str, context: str, state: str) -> None:
    status_post(forge, sha, context=context, state=state, description=f'{context} {state}')


class _Clock:
    """A clock that advances one second per read, and a sleep that posts the next scripted status."""

    def __init__(self, forge: StateForge, sha: str, script: list[tuple[str, str]]) -> None:
        self.now, self.forge, self.sha, self.script = 0.0, forge, sha, script

    def __call__(self) -> float:
        self.now += 1.0
        return self.now

    def sleep(self, _seconds: float) -> None:
        if self.script:
            _post(self.forge, self.sha, *self.script.pop(0))


@pytest.mark.parametrize(
    ('script', 'code', 'last'),
    [
        ([('tests/base', 'success')], 0, 'green'),
        ([('tests/base', 'failure')], 1, 'red'),
        ([], 3, 'deadline'),
    ],
)
def test_the_stream_prints_one_line_per_status_change_and_exits_0_green_1_red_3_deadline(
    script: list[tuple[str, str]], code: int, last: str
) -> None:
    """PLANTED CONTROL: a repeated reading prints nothing; each change, review's included, is one line."""
    forge, sha = StateForge(), 'a' * 40
    _post(forge, sha, 'tests/base', 'pending')
    _post(forge, sha, 'tests/review', 'pending')
    clock = _Clock(forge, sha, [('tests/review', 'success'), ('tests/review', 'success'), *script])
    said: list[str] = []
    done = watch(forge, (sha,), deadline_s=6, every_s=5, say=said.append, clock=clock, sleep=clock.sleep, stream=True)
    assert done == code
    assert said[:3] == [
        f'{sha[:12]} tests/base pending',
        f'{sha[:12]} tests/review pending',
        f'{sha[:12]} tests/review success',
    ]
    assert said[-1].startswith(f'{sha[:12]} {last}')
    assert len(said) == 3 + len(script) + 1, said


def test_the_watch_command_is_the_stream_door_and_a_live_one_counts_by_a_7_hex_prefix() -> None:
    sha = 'b' * 40
    assert watch_command(sha).endswith(f'-m dev_lab.dev.forge watch {sha} --stream')
    assert watched(sha, [f'python -m dev_lab.dev.forge watch {sha[:7]} --stream'])
    assert not watched(sha, [f'python -m dev_lab.dev.forge watch {sha[:6]}'])  # PLANTED: too short a prefix
    assert not watched(sha, [f'python -m dev_lab.dev.forge status show {sha}'])


@pytest.mark.parametrize(
    ('words', 'ref'),
    [
        ([], 'HEAD'),
        (['origin'], 'HEAD'),
        (['-u', 'origin', 'pr/x'], 'pr/x'),
        (['origin', '+HEAD:refs/heads/pr/x'], 'HEAD'),
        (['origin', ':pr/x'], None),
        (['origin', '-d', 'pr/x'], None),
    ],
)
def test_the_pushed_ref_is_the_last_refspec_s_source_and_a_deletion_pushes_none(
    words: list[str], ref: str | None
) -> None:
    assert pushed_ref(words) == ref


def test_an_unwatched_push_gets_a_one_line_reminder_and_a_watched_one_none(tmp_path: Path) -> None:
    """PLANTED CONTROL: the same push with a live `forge watch <sha>` process is silent."""
    work, head = _work(tmp_path)
    said = reminder(work, 'sh scripts/hooks/with-retry.sh push origin HEAD', processes=lambda: ())
    assert said is not None
    assert said.startswith(f'{RULE}: ')
    assert '\n' not in said
    assert watch_command(head) in said
    live = [watch_command(head)]
    assert reminder(work, 'git push origin HEAD', processes=lambda: live) is None
    assert reminder(work, 'git status', processes=lambda: ()) is None


def test_the_hook_advises_through_additional_context_and_never_blocks(tmp_path: Path, capsys) -> None:
    work, head = _work(tmp_path)
    payload = {'hook_event_name': 'PostToolUse', 'cwd': str(work), 'tool_input': {'command': 'git push origin HEAD'}}
    assert pushwatch.main([], stdin=io.StringIO(json.dumps(payload)), processes=lambda: ()) == 0
    out = json.loads(capsys.readouterr().out)
    assert 'decision' not in out, 'advisory: never a block'
    assert out['hookSpecificOutput']['hookEventName'] == 'PostToolUse'
    assert head[:12] in out['hookSpecificOutput']['additionalContext']
    assert pushwatch.main([], stdin=io.StringIO('not json'), processes=lambda: ()) == 0


def test_a_successful_push_through_the_family_door_prints_the_monitor_command(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    work, head = _work(tmp_path)
    monkeypatch.chdir(work)
    assert netverb.main(['--attempts', '1', '--', 'git', 'push', 'origin', 'HEAD:refs/heads/pr/w']) == 0
    assert watch_command(head) in capsys.readouterr().err
    assert netverb.main(['--attempts', '1', '--', 'git', 'fetch', 'origin']) == 0
    assert 'forge watch' not in capsys.readouterr().err, 'PLANTED CONTROL: a fetch pushed nothing'


def test_forge_pr_create_prints_the_monitor_command_for_the_pr_head(tmp_path: Path, monkeypatch, capsys) -> None:
    work, head = _work(tmp_path)
    run_git(work, 'push', '-q', '--no-verify', 'origin', 'HEAD:refs/heads/pr/w')
    forge = StateForge()
    monkeypatch.setattr(forgecli, 'client_for', lambda *_a, **_k: forge)
    monkeypatch.setattr(forgecli.pradmit, 'create_advice', lambda *_a, **_k: ())
    monkeypatch.setattr(forgecli.forgemerge, 'auto_merge', lambda *_a: 'auto-merge enabled')
    monkeypatch.setattr(forgecli.branchnotices, 'report', lambda *_a, **_k: '')
    argv = ['pr', 'create', '--title', 't', '--head', 'pr/w', '--base', 'integrate/main']
    assert forgecli.issue_and_pr(argv, cwd=work, env={}) == 0
    assert watch_command(head) in capsys.readouterr().err


# --------------------------------------------------------------------------------------------
# A PUSHED PR IS WATCHED (user ruling 2026-11-04): the session's pushes are journalled, and a Stop is refused while one
# is pending with no live watcher, or red.


def _hook(work: Path, command: str, session: str = 's1') -> None:
    payload = {'hook_event_name': 'PostToolUse', 'cwd': str(work), 'session_id': session,
               'tool_input': {'command': command}}  # fmt: skip
    assert pushwatch.main([], stdin=io.StringIO(json.dumps(payload)), processes=lambda: ()) == 0


def _stop(work: Path, forge: StateForge, live: list[str], *, again: bool = False, session: str = 's1') -> dict | None:
    payload = {'hook_event_name': 'Stop', 'cwd': str(work), 'session_id': session, 'stop_hook_active': again}
    out = io.StringIO()
    code = pushstop.main(
        [], stdin=io.StringIO(json.dumps(payload)), processes=lambda: live, client=lambda _r: forge, out=out
    )
    assert code == 0, 'a hook never exits nonzero'
    return json.loads(out.getvalue()) if out.getvalue().strip() else None


def test_a_push_is_journalled_per_session_and_a_later_push_of_the_same_ref_replaces_it(tmp_path: Path, capsys) -> None:
    work, head = _work(tmp_path)
    _hook(work, 'git push origin HEAD')
    assert set(pushwatch.pushed_by(work, 's1').values()) == {head}
    run_git(work, 'commit', '-q', '--allow-empty', '-m', 'next')
    newer = git_out(work, 'rev-parse', 'HEAD')
    _hook(work, 'git push origin HEAD')
    assert set(pushwatch.pushed_by(work, 's1').values()) == {newer}, "the superseded head is no longer the session's"
    assert pushwatch.pushed_by(work, 'other') == {}, 'PLANTED CONTROL: another session pushed nothing'
    capsys.readouterr()


def test_a_stop_is_refused_while_a_pushed_head_is_pending_and_unwatched_naming_the_watch_command(
    tmp_path: Path,
) -> None:
    """PLANTED CONTROL: the same pending head with a live watcher lets the turn end; so does a green one."""
    work, head = _work(tmp_path)
    _hook(work, 'git push origin HEAD')
    forge = StateForge()
    _post(forge, head, 'tests/base', 'pending')
    block = _stop(work, forge, [])
    assert block is not None
    assert block['decision'] == 'block'
    assert RULE in block['reason']
    assert watch_command(head) in block['reason']
    assert _stop(work, forge, [], again=True) is not None, (
        'an unwatched pending head blocks every time: arming is cheap'
    )
    assert _stop(work, forge, [watch_command(head)]) is None
    _post(forge, head, 'tests/base', 'success')
    assert _stop(work, forge, []) is None


def test_a_red_pushed_head_that_is_no_session_pr_does_not_refuse_the_stop(tmp_path: Path) -> None:
    """A red blocks only on a PR of the session (SESSION-HEARS-ITS-PRS, tests/test_dev_sessionwatch.py)."""
    work, head = _work(tmp_path)
    _hook(work, 'git push origin HEAD')
    forge = StateForge()
    _post(forge, head, 'tests/base', 'pending')
    assert _stop(work, forge, []) is not None, 'PLANTED CONTROL: the same head pending and unwatched is refused'
    _post(forge, head, 'tests/base', 'failure')
    assert _stop(work, forge, []) is None


def test_a_session_that_pushed_nothing_or_a_forge_that_cannot_answer_ends_the_turn(tmp_path: Path) -> None:
    work, head = _work(tmp_path)
    assert _stop(work, StateForge(), []) is None
    _hook(work, 'git push origin HEAD')

    def boom(_root: Path) -> StateForge:
        msg = 'no forge'
        raise ValueError(msg)

    payload = {'hook_event_name': 'Stop', 'cwd': str(work), 'session_id': 's1'}
    out = io.StringIO()
    assert pushstop.main([], stdin=io.StringIO(json.dumps(payload)), processes=lambda: (), client=boom, out=out) == 0
    assert out.getvalue() == '', 'an unreadable fact is silence'
    assert head in pushwatch.pushed_by(work, 's1').values()


def test_one_watch_takes_many_heads_and_ends_on_the_first_that_settles() -> None:
    forge, first, second = StateForge(), 'd' * 40, 'e' * 40
    _post(forge, first, 'tests/base', 'pending')
    _post(forge, second, 'tests/base', 'pending')
    clock = _Clock(forge, second, [('tests/base', 'failure')])
    said: list[str] = []
    assert watch(forge, (first, second), deadline_s=9, every_s=5, say=said.append, clock=clock, sleep=clock.sleep,
                 stream=True) == 1  # fmt: skip
    assert said[-1] == f'{second[:12]} red'
    assert watched(second, [f'python -m dev_lab.dev.forge watch {first} {second[:8]} --stream'])
