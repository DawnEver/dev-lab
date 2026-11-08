"""ONE uv writes every lock: ``uv.lock``'s ``revision`` line is the writer's format.

Two uv releases relocking the same pins churn it and conflict (integrator gap 10, 2026-10-26: revision 5
on one host, 3 on another).

The declared version is :func:`dev_lab.dev.lockcheck.uv_version`; the door refuses to write a lock with any other
uv, by name and with the remedy, and every installer this family ships installs exactly that one.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from dev_lab.dev import _dep_project, dep
from dev_lab.dev.hpcaccount.checks import INSTALLERS
from dev_lab.dev.lockcheck import UV_PIN, uv_version

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
    assert uv_version() in out
    assert f'uv self update {uv_version()}' in out


@pytest.mark.parametrize('argv', [['--lock-upgrade'], ['--sync']])
def test_the_declared_uv_writes_the_lock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, argv: list[str]) -> None:
    """PLANTED CONTROL for the refusal above: the same call on the declared uv runs."""
    _project(tmp_path)
    monkeypatch.setattr(_dep_project, 'installed_uv_version', lambda _uv: uv_version())
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
    assert f'astral.sh/uv/{uv_version()}/install.sh' in INSTALLERS['uv']


def test_the_lock_upgrade_of_a_tree_carrying_the_uv_pin_raises_it_and_is_written_by_the_new_uv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """User directive 2026-11-05: the door moves dev-lab's uv pin to the newest release, written BY that uv.

    PLANTED control: the old uv on PATH is refused and the pin stays where it was.
    """
    _project(tmp_path)
    pin = tmp_path / UV_PIN
    pin.parent.mkdir(parents=True)
    pin.write_text('version = "0.13.7"\n', encoding='utf-8')
    calls, run = _recording()
    upgrade = _dep_project.lock_upgrade
    monkeypatch.setattr(_dep_project, 'installed_uv_version', lambda _uv: '0.13.7')
    assert upgrade(tmp_path, 'py', run=run, dry_run=False, environment={}, newest=lambda: '0.13.8') == 1
    assert calls == []
    assert pin.read_text(encoding='utf-8') == 'version = "0.13.7"\n'
    monkeypatch.setattr(_dep_project, 'installed_uv_version', lambda _uv: '0.13.8')
    assert upgrade(tmp_path, 'py', run=run, dry_run=False, environment={}, newest=lambda: '0.13.8') == 0
    assert calls
    assert pin.read_text(encoding='utf-8') == 'version = "0.13.8"\n'
