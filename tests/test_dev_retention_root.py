"""``python -m dev_lab.dev.retention --cluster`` with no declared root is a named refusal, never a traceback.

MEASURED 2026-11-22, a deadlock on an account whose FILE quota was full: the retention run died in
``local_root()`` -- ``LAB_ROOT is unset ... run deploy-fleet`` -- while the deploy could not finish BECAUSE the
quota was full (the login file never got its ``export LAB_ROOT``). The one verb that frees space needed the
deploy that needs space. The fleet verb now passes the root it already reads (``tests/test_dev_hpcaccount_storage``);
here the account's own entry point names the cause and that door. PLANTED CONTROL: with the root declared the same
call plans and exits 0.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from lab_commons.hpc.layout import ROOT_VAR

from dev_lab.dev import retention
from dev_lab.dev.retentionplan import Plan


def _quiet(monkeypatch: pytest.MonkeyPatch, said: list[str]) -> None:
    monkeypatch.setattr(retention, 'section', lambda _name: {})
    monkeypatch.setattr(retention, '_live_shas', set)
    monkeypatch.setattr(retention, 'read_usage', lambda *_a, **_k: None)
    monkeypatch.setattr(retention, '_plan_for', lambda *_a, **_k: Plan(()))
    monkeypatch.setattr(retention, 'emit', lambda line, **_k: said.append(line))


def test_no_declared_root_is_refused_naming_the_cause_and_the_door(monkeypatch: pytest.MonkeyPatch) -> None:
    said: list[str] = []
    _quiet(monkeypatch, said)
    monkeypatch.delenv(ROOT_VAR, raising=False)
    assert retention.main(['--cluster', '--apply']) == 2
    (line,) = said
    assert line.startswith(f'[retention] refused: {ROOT_VAR} is unset')
    assert 'python -m dev_lab.dev.hpcaccount retention --account <user>' in line, 'the door that passes the root'


def test_the_declared_root_is_planned(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    said: list[str] = []
    _quiet(monkeypatch, said)
    monkeypatch.setenv(ROOT_VAR, tmp_path.as_posix())
    assert retention.main(['--cluster']) == 0
    assert not any('refused' in line for line in said)
