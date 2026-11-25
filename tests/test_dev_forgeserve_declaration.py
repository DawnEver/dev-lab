"""``forge serve`` -- a refused declaration is a named release, never a traceback.

MEASURED 2026-11-22: ``serve`` read ``section('schedule'|'serve'|'capabilities'|priority)``,
``forgeaffinity.declared(config_path())`` and ``spec.load(config_path())`` uncaught, so a machine file its layered
reader refuses was a ValueError traceback out of every tick -- the guard ``hpcaccount tick`` already had for its own
reads. PLANTED CONTROL: a ValueError that is NOT a declaration read is still a defect and still raises.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from lab_commons.config import CONFIG_ENV
from lab_commons.hpc.account import ClusterAccount

from dev_lab.dev import forgeserve, forgeservedeclared
from dev_lab.dev.hpcaccount.grantslice import REDEPLOY_DOOR
from dev_lab.dev.producer import ProducerExit

CAUSE = 'machine.toml restates [hpc] grant, which the family file holds'


def _refusing(name: str) -> object:
    def read(*_a: object, **_k: object) -> object:
        raise ValueError(CAUSE)

    read.__name__ = name
    return read


def _host(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv(CONFIG_ENV, str(tmp_path / 'home' / 'config.toml'))
    monkeypatch.setattr(forgeserve, 'origin_url', lambda _root: 'https://f/o/r.git')
    monkeypatch.setattr(forgeserve, 'host_failure', lambda *_a: None)


def _serve(tmp_path: Path, seat: ClusterAccount | None) -> object:
    return forgeserve.serve(
        tmp_path, client=lambda _root: None, machine='m', seat=seat, cluster=lambda: None, present=lambda _here: {},
        say=lambda _line: None, alarm=lambda _alarm: None,
    )  # fmt: skip


@pytest.mark.parametrize('reader', ['section', 'declared', 'load'])
def test_each_declaration_read_refused_is_a_named_release(
    reader: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _host(monkeypatch, tmp_path)
    monkeypatch.setattr(forgeservedeclared, reader, _refusing(reader))
    with pytest.raises(forgeservedeclared.DeclarationRefused) as refused:
        _serve(tmp_path, ClusterAccount('c1', 'alice'))
    assert str(refused.value).startswith(f'released, not served this tick: {CAUSE}')
    assert REDEPLOY_DOOR in str(refused.value), 'on an account the door is the re-render'


def test_the_cli_releases_the_tick_naming_the_cause_and_exits_two(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _host(monkeypatch, tmp_path)
    monkeypatch.setattr(forgeservedeclared, 'section', _refusing('section'))
    assert forgeserve.main([], cwd=tmp_path, seat_of=lambda: None) == ProducerExit.USAGE
    assert f'[serve] released, not served this tick: {CAUSE}' in capsys.readouterr().err


def test_a_value_error_that_is_no_declaration_read_is_still_a_defect(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _host(monkeypatch, tmp_path)
    monkeypatch.setattr(forgeserve, 'read_cards', _refusing('read_cards'))
    with pytest.raises(ValueError, match='restates') as defect:
        _serve(tmp_path, None)
    assert not isinstance(defect.value, forgeservedeclared.DeclarationRefused)
