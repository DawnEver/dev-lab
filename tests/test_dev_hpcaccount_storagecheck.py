"""``hpcaccount storage-check``: an account's placed storage secret proved in ITS kit, no secret and no consent code.

Measured 2026-11-23: a placed secret whose check refused (a doubled ``[hpc]``, since repaired) could only be re-checked
by ``secretplace distribute`` again -- a consent code and a re-write for a read.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from dev_lab.dev import hpcaccount
from dev_lab.dev.hpcaccount import storagecheck
from dev_lab.dev.hpcaccount.fleet import Target

ROOT = '/scratch/u1/lab'


def _fleet(monkeypatch: pytest.MonkeyPatch, ran: list[str], answer: str | Exception) -> None:
    grant = SimpleNamespace(user='u1')
    monkeypatch.setattr(storagecheck, 'reached_machine', lambda _users: SimpleNamespace(grants=[grant]))
    monkeypatch.setattr(storagecheck, 'declared_target', lambda _g, _shell: Target('login1', ROOT))

    def runner(command: str, _stdin: str | None) -> str:
        ran.append(command)
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(storagecheck, 'grant_runner', lambda _g, **_kw: runner)


def test_the_check_runs_in_the_account_kit_and_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    ran: list[str] = []
    said: list[str] = []
    _fleet(monkeypatch, ran, 'rendering\nresults: reached (3 top-level entr(y/ies)) through /x\n')
    assert storagecheck.storage_check('u1', 'results', say=said.append) == 0
    assert len(ran) == 1
    assert 'dev_lab.dev.storage check results' in ran[0]
    assert said == ['u1: results: reached (3 top-level entr(y/ies)) through /x']


def test_planted_control_a_refused_check_exits_2_naming_why(monkeypatch: pytest.MonkeyPatch) -> None:
    ran: list[str] = []
    said: list[str] = []
    _fleet(monkeypatch, ran, RuntimeError("Cannot declare ('hpc',) twice"))
    assert storagecheck.storage_check('u1', 'results', say=said.append) == 2
    assert "Cannot declare ('hpc',) twice" in said[0]
    assert 'redeploy' in said[0]


def test_a_remote_that_is_not_a_name_reaches_no_account(monkeypatch: pytest.MonkeyPatch) -> None:
    ran: list[str] = []
    said: list[str] = []
    _fleet(monkeypatch, ran, 'results: reached (1)')
    assert storagecheck.storage_check('u1', 'a;rm -rf ~', say=said.append) == 2
    assert ran == []


def test_the_verb_is_dispatched(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[tuple[str, str]] = []
    monkeypatch.setattr(storagecheck, 'storage_check', lambda user, remote: seen.append((user, remote)) or 0)
    assert hpcaccount.main(['storage-check', '--account', 'u1', 'results']) == 0
    assert seen == [('u1', 'results')]
