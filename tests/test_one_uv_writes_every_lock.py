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

from dev_lab.dev import _dep_project, dep, toolrelease, uvrelease
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


def _no_download(monkeypatch: pytest.MonkeyPatch, base: Path) -> list[str]:
    """Every pinned uv lands in *base*; the "download" writes a stub and records the version it was asked for."""
    asked: list[str] = []

    def install(release, *, directory: Path, key: str) -> Path:
        asked.append(release.version)
        exe = directory / release.exe(windows=key.startswith('windows-'))
        exe.parent.mkdir(parents=True, exist_ok=True)
        exe.write_text('stub', encoding='utf-8')
        return exe

    monkeypatch.setattr(toolrelease, 'tool_dir', lambda **_kw: base)
    monkeypatch.setattr(toolrelease, 'install_release', install)
    return asked


@pytest.mark.parametrize('argv', [['--lock-upgrade'], ['--sync'], ['--upgrade-package', 'peer']])
def test_another_path_uv_never_writes_the_lock_the_pinned_one_does(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, argv: list[str]
) -> None:
    """The PATH uv is another version: the pinned one is installed BESIDE it and writes the lock; PATH untouched."""
    _project(tmp_path)
    monkeypatch.setattr(_dep_project, 'installed_uv_version', lambda _uv: _OTHER)
    asked = _no_download(monkeypatch, tmp_path / 'tools')
    calls, run = _recording()
    assert dep.main(argv, cwd=tmp_path, run=run) == 0
    assert asked == [uv_version()]
    writers = {call[0] for call in calls if len(call) > 1 and call[1] in {'lock', 'sync'} and '--frozen' not in call}
    assert writers
    assert all(Path(writer).parent.name == uv_version() for writer in writers)


def test_a_pinned_uv_that_cannot_be_had_is_refused_by_name_and_nothing_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _project(tmp_path)
    monkeypatch.setattr(_dep_project, 'installed_uv_version', lambda _uv: _OTHER)
    monkeypatch.setattr(toolrelease, 'tool_dir', lambda **_kw: tmp_path / 'tools')

    def unreachable(*_args: object, **_kwargs: object) -> Path:
        msg = 'HTTP 503'
        raise toolrelease.DownloadRefused(msg)

    monkeypatch.setattr(toolrelease, 'install_release', unreachable)
    calls, run = _recording()
    assert dep.main(['--lock-upgrade'], cwd=tmp_path, run=run) == 1
    assert calls == []
    out = capsys.readouterr().out
    assert 'REFUSED' in out
    assert uv_version() in out
    assert '--lock-upgrade' in out


@pytest.mark.parametrize('argv', [['--lock-upgrade'], ['--sync']])
def test_the_declared_uv_writes_the_lock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, argv: list[str]) -> None:
    """PLANTED CONTROL: a PATH uv that IS the pinned version writes the lock itself; nothing is installed."""
    _project(tmp_path)
    monkeypatch.setattr(_dep_project, 'installed_uv_version', lambda _uv: uv_version())
    asked = _no_download(monkeypatch, tmp_path / 'tools')
    calls, run = _recording()
    assert dep.main(argv, cwd=tmp_path, run=run) == 0
    assert calls
    assert asked == []


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

    The old uv on PATH stays; the new release is installed beside it, writes the lock, and the pin moves with its
    digests. PLANTED control: a release whose digests cannot be read writes nothing and the pin stays.
    """
    _project(tmp_path)
    pin = tmp_path / UV_PIN
    pin.parent.mkdir(parents=True)
    pin.write_text('version = "0.13.7"\n', encoding='utf-8')
    calls, run = _recording()
    upgrade = _dep_project.lock_upgrade
    monkeypatch.setattr(_dep_project, 'installed_uv_version', lambda _uv: '0.13.7')
    asked = _no_download(monkeypatch, tmp_path / 'tools')

    def unreadable(version: str, *, read: object = None) -> dict[str, str]:
        msg = f'uv {version}: unreachable ({read})'
        raise OSError(msg)

    monkeypatch.setattr(uvrelease, 'digests', unreadable)
    assert upgrade(tmp_path, 'py', run=run, dry_run=False, environment={}, newest=lambda: '0.13.8') == 1
    assert calls == []
    assert pin.read_text(encoding='utf-8') == 'version = "0.13.7"\n'
    monkeypatch.setattr(uvrelease, 'digests', lambda _version, **_kw: dict.fromkeys(uvrelease.ASSETS, 'c' * 64))
    assert upgrade(tmp_path, 'py', run=run, dry_run=False, environment={}, newest=lambda: '0.13.8') == 0
    assert asked == ['0.13.8']
    assert Path(calls[0][0]).parent.name == '0.13.8'
    text = pin.read_text(encoding='utf-8')
    assert text.startswith('version = "0.13.8"\n')
    assert text.count('c' * 64) == len(uvrelease.ASSETS)
