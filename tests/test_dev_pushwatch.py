"""PUSHED-HEAD-IS-WATCHED: a push door names who hears the pushed head -- the machine PR watcher, never a Monitor.

dev-lab #640 left the machine forge hearer (``forgefeed``) the one hearer of a session's PRs; the push journal, its
``PostToolUse`` reminder and the ``Stop`` gate that read it are deleted, and each deletion is pinned absent here.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from _arch_corpus import module_names
from _branch_repos import clone_pair, commit
from _forge_fake import run_git
from _forge_state import StateForge

from dev_lab.dev import forgecli, netverb, pushwatch
from dev_lab.dev.forgestatus import status_post
from dev_lab.dev.forgewatch import watch
from dev_lab.dev.pushwatch import RULE, heard_line, pushed_ref


def _work(tmp_path: Path) -> tuple[Path, str]:
    _, work = clone_pair(tmp_path)
    return work, commit(work, 'pr.txt', 'a head not on the integration branch\n')


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


def test_the_heard_line_names_the_machine_watcher_and_no_monitor() -> None:
    sha = 'b' * 40
    said = heard_line(sha)
    assert said.startswith(f'{RULE}: {sha[:12]} ')
    assert len(said.splitlines()) == 1
    assert said.endswith('-m dev_lab.dev.forgefeed start'), 'the one door that starts the hearer'
    assert 'forge watch' not in said, 'PLANTED CONTROL: no Monitor is armed -- forgefeed alone hears PRs'


def test_the_push_journal_hook_is_gone() -> None:
    """dev-lab #640 unwired it; it is deleted (the Stop gate too: ``test_arch_retired_spellings``)."""
    assert 'main' not in module_names(pushwatch), 'the PostToolUse journal-and-remind hook is deleted'
    assert 'heard_line' in module_names(pushwatch), 'PLANTED CONTROL: the module and its live line stay'


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


def test_a_successful_push_through_the_family_door_prints_the_heard_line(tmp_path: Path, monkeypatch, capsys) -> None:
    work, head = _work(tmp_path)
    monkeypatch.chdir(work)
    assert netverb.main(['--attempts', '1', '--', 'git', 'push', 'origin', 'HEAD:refs/heads/pr/w']) == 0
    assert heard_line(head) in capsys.readouterr().err
    assert netverb.main(['--attempts', '1', '--', 'git', 'fetch', 'origin']) == 0
    assert RULE not in capsys.readouterr().err, 'PLANTED CONTROL: a fetch pushed nothing'


def test_forge_pr_create_prints_the_heard_line_for_the_pr_head(tmp_path: Path, monkeypatch, capsys) -> None:
    work, head = _work(tmp_path)
    run_git(work, 'push', '-q', '--no-verify', 'origin', 'HEAD:refs/heads/pr/w')
    forge = StateForge()
    monkeypatch.setattr(forgecli, 'client_for', lambda *_a, **_k: forge)
    monkeypatch.setattr(forgecli.pradmit, 'create_advice', lambda *_a, **_k: ())
    monkeypatch.setattr(forgecli.forgemergecall, 'auto_merge', lambda *_a: 'auto-merge enabled')
    monkeypatch.setattr(forgecli.branchnotices, 'report', lambda *_a, **_k: '')
    argv = ['pr', 'create', '--title', 't', '--head', 'pr/w', '--base', 'integrate/main']
    assert forgecli.issue_and_pr(argv, cwd=work, env={}) == 0
    assert heard_line(head) in capsys.readouterr().err


def test_one_watch_takes_many_heads_and_ends_on_the_first_that_settles() -> None:
    forge, first, second = StateForge(), 'd' * 40, 'e' * 40
    _post(forge, first, 'tests/base', 'pending')
    _post(forge, second, 'tests/base', 'pending')
    clock = _Clock(forge, second, [('tests/base', 'failure')])
    said: list[str] = []
    assert watch(forge, (first, second), deadline_s=9, every_s=5, say=said.append, clock=clock, sleep=clock.sleep,
                 stream=True) == 1  # fmt: skip
    assert said[-1] == f'{second[:12]} red'
