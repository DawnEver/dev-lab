"""``forge breakglass`` / ``forge pr breakglass``: open sends the user's credential; a merge sends a pinned head."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

import pytest
from _ops_fixtures import git

from dev_lab.dev import remote
from dev_lab.dev._forge_records import PullRequest
from dev_lab.dev.consentguard import state_dir
from dev_lab.dev.forgebreakglass import merge_main, ssh_send, wave_main
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


def test_open_sends_the_granted_credential(tmp_path: Path) -> None:
    held = state_dir(tmp_path) / 'c0ffee.json'
    held.parent.mkdir(parents=True)
    held.write_text(json.dumps({'id': 'c0ffee', 'sig': 's'}), encoding='utf-8')
    send = _Recorder()
    assert wave_main(['open', '--credential', 'c0ffee'], table=_TABLE, send=send, home=tmp_path) == 0
    assert send.sent == [{'action': 'open', 'credential': {'id': 'c0ffee', 'sig': 's'}}]


def test_open_without_a_granted_credential_is_refused_and_sends_nothing(tmp_path: Path) -> None:
    send = _Recorder()
    assert wave_main(['open', '--credential', 'missing'], table=_TABLE, send=send, home=tmp_path) == 2
    assert wave_main(['open'], table=_TABLE, send=send, home=tmp_path) == 2
    assert send.sent == []


def test_close_and_status_send_no_credential() -> None:
    send = _Recorder()
    for action in ('close', 'status'):
        wave_main([action], table=_TABLE, send=send)
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
        {
            'action': 'merge',
            'repo': 'forge.example/owner/alpha',
            'pr': 7,
            'head': 'c' * 40,
            'reason': 'review-bot is down',
        }
    ]


def test_no_endpoint_refuses_and_a_server_refusal_is_exit_2() -> None:
    assert wave_main(['status'], table={}, send=_Recorder()) == 2
    assert wave_main(['status'], table=_TABLE, send=_Recorder(status=2)) == 2
    assert wave_main(['status'], table=_TABLE, send=_Recorder(status=255)) == 1


def test_they_are_forge_verbs() -> None:
    assert PR_VERBS['breakglass'] is merge_main
    assert NOUNS['breakglass'] is wave_main


def test_ssh_send_goes_through_the_one_remote_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    """One transport: the consent/breakglass JSON line rides :func:`dev_lab.dev.remote.piped`, never its own ssh."""
    seen: list[tuple[str, str, str | None]] = []

    def piped(target: str, line: str, *, identity: str | None, timeout_s: float) -> tuple[int, str]:
        seen.append((target, line, identity))
        assert timeout_s > 0
        return 0, 'ok'

    monkeypatch.setattr(remote, 'piped', piped)
    assert ssh_send({'endpoint': 'c@h', 'identity': 'k'}, {'a': 1}) == (0, 'ok')
    assert seen == [('c@h', '{"a": 1}\n', 'k')]
