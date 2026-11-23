"""``hpcaccount look``: a READ-ONLY look at a key-only account, a closed set of reads, no free-form command.

Measured 2026-11-23: a hung tick on a key-only account could not be seen at all.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from dev_lab.dev.hpcaccount import look
from dev_lab.dev.hpcaccount.fleet import Target

ROOT = '/scratch/u1/lab'


@pytest.mark.parametrize(('what', 'repo', 'wanted'), [
    ('processes', '', 'ps -u "$(id -un)"'),
    ('ticks', '', f'cd {ROOT}/serve'),
    ('log', 'alpha', f'tail -n {look.LOG_LINES} {ROOT}/serve/alpha.log'),
    ('crontab', '', 'crontab -l'),
])  # fmt: skip
def test_each_read_is_a_fixed_line(what: str, repo: str, wanted: str) -> None:
    assert wanted in look.command_of(what, repo, ROOT)


@pytest.mark.parametrize(('what', 'repo'), [
    ('rm', ''), ('run', ''), ('kill', ''), ('crontab -r', ''), ('log', '../../.ssh/authorized_keys'),
    ('log', 'a;rm -rf ~'), ('log', ''), ('ticks', 'alpha'),
])  # fmt: skip
def test_a_write_shaped_request_is_refused_naming_the_reads(what: str, repo: str) -> None:
    with pytest.raises(ValueError, match=r'^look: '):
        look.command_of(what, repo, ROOT)


def _fleet(monkeypatch: pytest.MonkeyPatch, ran: list[str]) -> dict[str, object]:
    grant = SimpleNamespace(user='u1')
    monkeypatch.setattr(look, 'reached_machine', lambda _users: SimpleNamespace(grants=[grant]))
    monkeypatch.setattr(look, 'declared_target', lambda _g, _shell: Target('login1', ROOT))

    def runner(command: str, _stdin: str | None) -> str:
        ran.append(command)
        return '== alpha.lock\n{"pid": 4242}\n'

    return {'connect': lambda _g: runner, 'pin': lambda _g, _host: runner}


def test_a_read_returns_what_the_account_printed(monkeypatch: pytest.MonkeyPatch) -> None:
    ran: list[str] = []
    said: list[str] = []
    assert look.look('u1', 'ticks', say=said.append, **_fleet(monkeypatch, ran)) == 0
    assert ran == [look.command_of('ticks', '', ROOT)]
    assert said == ['u1@login1: ticks', '== alpha.lock', '{"pid": 4242}']


def test_planted_control_a_refused_read_reaches_no_account(monkeypatch: pytest.MonkeyPatch) -> None:
    ran: list[str] = []
    said: list[str] = []
    assert look.look('u1', 'rm', say=said.append, **_fleet(monkeypatch, ran)) == 2
    assert ran == []
    assert 'there is no free-form command' in said[0]
