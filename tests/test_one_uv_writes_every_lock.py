"""ONE uv writes every lock: ``uv.lock``'s ``revision`` line is the writer's format.

Two uv releases relocking the same pins churn it and conflict (integrator gap 10, 2026-10-26: revision 5
on one host, 3 on another).

The declared version is :data:`dev_lab.dev.lockcheck.UV_VERSION`; the door refuses to write a lock with any other
uv, by name and with the remedy, and every installer this family ships installs exactly that one.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from dev_lab.dev import _dep_project, dep
from dev_lab.dev.hpchost.checks import INSTALLERS
from dev_lab.dev.lockcheck import UV_VERSION

_OTHER = '0.0.1'


def _project(root: Path) -> None:
    (root / 'pyproject.toml').write_text(
        '[project]\nname="empty"\nversion="0"\n[project.optional-dependencies]\ndev=[]\n', encoding='utf-8'
    )


def _recording() -> tuple[list[tuple[str, ...]], object]:
    calls: list[tuple[str, ...]] = []

    def run(argv, **_kwargs: object) -> SimpleNamespace:
        calls.append(tuple(argv))
        return SimpleNamespace(returncode=0, stdout='', stderr='')

    return calls, run


@pytest.mark.parametrize('argv', [['--lock-upgrade'], ['--sync'], ['--upgrade-package', 'peer']])
def test_a_lock_writer_on_another_uv_is_refused_by_name_and_nothing_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], argv: list[str]
) -> None:
    _project(tmp_path)
    monkeypatch.setattr(_dep_project, 'installed_uv_version', lambda _uv: _OTHER)
    calls, run = _recording()
    assert dep.main(argv, cwd=tmp_path, run=run) == 1
    assert calls == []
    out = capsys.readouterr().out
    assert 'REFUSED' in out
    assert _OTHER in out
    assert UV_VERSION in out
    assert f'uv self update {UV_VERSION}' in out


@pytest.mark.parametrize('argv', [['--lock-upgrade'], ['--sync']])
def test_the_declared_uv_writes_the_lock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, argv: list[str]) -> None:
    """PLANTED CONTROL for the refusal above: the same call on the declared uv runs."""
    _project(tmp_path)
    monkeypatch.setattr(_dep_project, 'installed_uv_version', lambda _uv: UV_VERSION)
    calls, run = _recording()
    assert dep.main(argv, cwd=tmp_path, run=run) == 0
    assert calls


def test_a_frozen_bootstrap_writes_no_lock_so_any_uv_may_build_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _project(tmp_path)
    monkeypatch.setattr(_dep_project, 'installed_uv_version', lambda _uv: _OTHER)
    calls, run = _recording()
    assert dep.main(['--bootstrap', str(tmp_path)], cwd=tmp_path, run=run) == 0
    assert any(call[1] == 'sync' and '--frozen' in call for call in calls)


def test_the_version_is_read_from_uv_itself() -> None:
    """The probe parses ``uv --version``'s second word; a uv that cannot answer reads as no version at all."""
    assert _dep_project.parse_uv_version('uv 0.13.5 (x86_64-unknown-linux-gnu)\n') == '0.13.5'
    assert _dep_project.parse_uv_version('uv 0.12.5 (210d1f678 2026-08-14 x86_64-pc-windows-msvc)') == '0.12.5'
    assert _dep_project.parse_uv_version('') == ''


def test_the_cluster_installer_installs_the_declared_uv() -> None:
    """A workstation's missing-uv hint stays unversioned: the dependency door names the exact update when it refuses."""
    assert f'astral.sh/uv/{UV_VERSION}/install.sh' in INSTALLERS['uv']
