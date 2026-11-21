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
from dev_lab.dev.forgebreakglass import merge_main, wave_main
from dev_lab.dev.forgecli import NOUNS, PR_VERBS
from dev_lab.dev.forgework import Client
from dev_lab.ops.consent import door as consent_door
from dev_lab.ops.consent.credential import ConsentRefused
from dev_lab.ops.consent.door import ssh_send

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


def test_the_open_refusal_names_both_doors_and_the_window(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert wave_main(['open'], table=_TABLE, send=_Recorder(), home=tmp_path) == 2
    said = capsys.readouterr().err
    assert '--code <code>' in said
    assert 'python -m dev_lab.ops.consent grant <request.json> --code <code>' in said
    assert '"action": "breakglass.wave"' in said
    assert '30 s' in said


class _Grant:
    def __init__(self, refusal: str = '') -> None:
        self.calls: list[tuple[dict[str, Any], str]] = []
        self.refusal = refusal

    def __call__(self, request: Path, *, code: str, home: Path | None) -> Path:
        self.calls.append((json.loads(request.read_text(encoding='utf-8')), code))
        if self.refusal:
            raise ConsentRefused(self.refusal)
        written = state_dir(home) / 'g1.json'
        written.write_text(json.dumps({'id': 'g1'}), encoding='utf-8')
        return written


def test_open_with_a_code_grants_then_opens_once_each(tmp_path: Path) -> None:
    send, grant_ = _Recorder(), _Grant()
    argv = ['open', '--code', '123456', '--hours', '2', '--max-merges', '3']
    assert wave_main(argv, table=_TABLE, send=send, home=tmp_path, grant_=grant_) == 0
    [(request, code)] = grant_.calls
    assert code == '123456'
    assert request['action'] == 'breakglass.wave'
    assert request['subject']
    assert request['params'] == {'max_merges': 3, 'hours': 2.0}
    assert send.sent == [{'action': 'open', 'credential': {'id': 'g1'}}]


def test_an_expired_code_is_refused_before_anything_opens(tmp_path: Path) -> None:
    send, grant_ = _Recorder(), _Grant('the code is wrong or outside its 30-second window')
    argv = ['open', '--code', '000000', '--hours', '1', '--max-merges', '1']
    assert wave_main(argv, table=_TABLE, send=send, home=tmp_path, grant_=grant_) == 2
    assert len(grant_.calls) == 1
    assert send.sent == []


def test_open_with_a_code_needs_its_bounds_and_spends_nothing(tmp_path: Path) -> None:
    send, grant_ = _Recorder(), _Grant()
    assert wave_main(['open', '--code', '123456'], table=_TABLE, send=send, home=tmp_path, grant_=grant_) == 2
    assert grant_.calls == []
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


class _Shut:
    """A fake forge holding PR 7 merged by someone else, and PR 8 closed unmerged."""

    def pr_view(self, number: int) -> PullRequest:
        merged = number == 7
        return PullRequest(
            number, 'fix', 'closed', '', 'u', 'a', 'pr/fix', 'integrate/main',
            head_sha='c' * 40, merged=merged, merge_sha='d' * 40 if merged else '',
        )  # fmt: skip


def test_a_pr_already_merged_is_done_with_its_merge_sha_and_sends_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    git(tmp_path, 'init', '-q')
    git(tmp_path, 'remote', 'add', 'origin', 'https://forge.example/owner/alpha.git')
    send = _Recorder()
    code = merge_main(['7', '--reason', 'r'], cwd=tmp_path, client=cast('Client', _Shut()), table=_TABLE, send=send)
    assert code == 0
    assert send.sent == []
    said = capsys.readouterr()
    assert 'already merged' in said.out
    assert 'd' * 40 in said.out
    assert 'refused' not in said.out + said.err


def test_a_pr_closed_unmerged_is_refused_naming_the_door(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    git(tmp_path, 'init', '-q')
    git(tmp_path, 'remote', 'add', 'origin', 'https://forge.example/owner/alpha.git')
    send = _Recorder()
    code = merge_main(['8', '--reason', 'r'], cwd=tmp_path, client=cast('Client', _Shut()), table=_TABLE, send=send)
    assert code == 2
    assert send.sent == []
    err = capsys.readouterr().err
    assert 'closed unmerged' in err
    assert 'python -m dev_lab.dev.forge pr create --head pr/fix --base integrate/main' in err


def test_no_endpoint_refuses_and_a_server_refusal_is_exit_2() -> None:
    assert wave_main(['status'], table={}, send=_Recorder()) == 2
    assert wave_main(['status'], table=_TABLE, send=_Recorder(status=2)) == 2
    assert wave_main(['status'], table=_TABLE, send=_Recorder(status=255)) == 1


def test_they_are_forge_verbs() -> None:
    assert PR_VERBS['breakglass'] is merge_main
    assert NOUNS['breakglass'] is wave_main


def test_ssh_send_goes_through_the_one_remote_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    """One transport: the consent/breakglass JSON line rides :func:`dev_lab.dev.remote.piped`, never its own ssh."""
    seen: list[tuple[str, str, str | None, str | None]] = []

    def piped(
        target: str, line: str, *, identity: str | None, known_hosts: str | None, timeout_s: float
    ) -> tuple[int, str]:
        seen.append((target, line, identity, known_hosts))
        assert timeout_s > 0
        return 0, 'ok'

    monkeypatch.setattr(remote, 'piped', piped)
    monkeypatch.setattr(consent_door, 'section', lambda _name: {'host_keys': {'h': 'ssh-ed25519 AAAAkey'}})
    assert ssh_send({'endpoint': 'c@h', 'identity': 'k'}, {'a': 1}) == (0, 'ok')
    assert ssh_send({'endpoint': 'c@h', 'known_hosts': 'kh'}, {'a': 1}) == (0, 'ok')
    assert [row[:3] for row in seen] == [('c@h', '{"a": 1}\n', 'k'), ('c@h', '{"a": 1}\n', None)]
    assert seen[0][3]  # SSH-HOST-KEY-DECLARED: the declared key's known_hosts, never ssh's own default
    assert seen[1][3] == 'kh'
