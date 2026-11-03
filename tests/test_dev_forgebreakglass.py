"""``forge breakglass`` / ``forge pr breakglass``: the human types the code; a merge sends a pinned head, no code."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

from _ops_fixtures import git

from dev_lab.dev._forge_records import PullRequest
from dev_lab.dev.forgebreakglass import merge_main, wave_main
from dev_lab.dev.forgecli import NOUNS, PR_VERBS
from dev_lab.dev.forgework import Client

_TABLE = {'endpoint': 'bg@host'}


class _Client:
    def pr_view(self, number: int) -> PullRequest:
        return PullRequest(number, 'fix', 'open', '', 'u', 'a', 'pr/fix', 'integrate/main', head_sha='c' * 40)


class _Recorder:
    def __init__(self, status: int = 0) -> None:
        self.sent: list[dict[str, Any]] = []
        self.status = status

    def __call__(self, table: Mapping[str, Any], request: dict[str, Any]) -> tuple[int, str]:
        del table
        self.sent.append(request)
        return self.status, 'said'


def test_open_sends_the_typed_code_and_the_asked_bounds() -> None:
    send = _Recorder()
    assert wave_main(['open', '--hours', '1'], table=_TABLE, ask=lambda _p: ' 123456 ', send=send) == 0
    assert send.sent == [{'action': 'open', 'hours': 1.0, 'code': '123456'}]


def test_close_and_status_ask_for_no_code() -> None:
    send = _Recorder()
    asked: list[str] = []
    for action in ('close', 'status'):
        wave_main([action], table=_TABLE, ask=lambda p: asked.append(p) or '', send=send)
    assert asked == []
    assert send.sent == [{'action': 'close'}, {'action': 'status'}]


def test_a_merge_sends_the_shown_head_and_no_code(tmp_path: Path) -> None:
    git(tmp_path, 'init', '-q')
    git(tmp_path, 'remote', 'add', 'origin', 'https://forge.example/owner/alpha.git')
    send = _Recorder()
    code = merge_main(
        ['7', '--reason', 'review-bot is down'], cwd=tmp_path, client=cast('Client', _Client()), table=_TABLE, send=send
    )
    assert code == 0
    assert send.sent == [
        {'action': 'merge', 'repo': 'alpha', 'pr': 7, 'head': 'c' * 40, 'reason': 'review-bot is down'}
    ]


def test_no_endpoint_refuses_and_a_server_refusal_is_exit_2() -> None:
    assert wave_main(['status'], table={}, send=_Recorder()) == 2
    assert wave_main(['status'], table=_TABLE, send=_Recorder(status=2)) == 2
    assert wave_main(['status'], table=_TABLE, send=_Recorder(status=255)) == 1


def test_they_are_forge_verbs() -> None:
    assert PR_VERBS['breakglass'] is merge_main
    assert NOUNS['breakglass'] is wave_main
