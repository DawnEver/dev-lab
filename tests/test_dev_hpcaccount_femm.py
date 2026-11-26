"""The deploy's ``femm`` phase: an account declaring ``[capabilities.femm]`` gets the pinned FEMM 5 from source.

User ruling 2026-11-25 ("install it through the deploy"). The shell is a fake run through :data:`sys.executable`:
it answers ``<tool> --version`` probes, and a build writes what a femm-qt build stages (``femm_headless`` and the
build stamp ``version.env``) into ``$FEMM_STAGE`` -- at the version the test names, so a build that does not
verify can be planted.

PLANTED CONTROLS: the undeclared account beside a declared one; a built install stating another version beside
one stating the pin; a failed build beside a kept old install.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Final

import pytest
from lab_commons.compute.toolchecks import FEMM_VERSION_FILE

from dev_lab.dev.hpcaccount import femm
from dev_lab.dev.hpcaccount.steps import Step, Tools
from dev_lab.dev.toolrelease import FEMM_QT

FAKE_SH: Final = r"""
import os, pathlib, sys
command = sys.argv[2]
with pathlib.Path(sys.argv[1]).open('a') as f: f.write(command.replace('\n', ' ') + '\n')
if command.endswith(' --version'):
    tool = command.rsplit(' ', 2)[-2].strip("'")
    if tool.endswith('femm_headless'):
        sys.exit(0 if pathlib.Path(tool).is_file() and not os.environ.get('FAKE_FEMM_DEAD') else 127)
    sys.exit(1 if tool in os.environ.get('FAKE_MISSING', '').split(',') else 0)
if 'cmake --build' in command:
    if os.environ.get('FAKE_BUILD_FAIL'):
        print('ninja: build stopped: subcommand failed.'); sys.exit(1)
    stage = pathlib.Path(os.environ['FEMM_STAGE'], 'bin')
    stage.mkdir(parents=True)
    for exe in ('femm_headless', 'fkn'):
        (stage / exe).write_text('#!/bin/sh\n')
        (stage / exe).chmod(0o755)
    (stage / 'version.env').write_text('# GENERATED\nFEMM_VERSION=' + os.environ['FAKE_BUILT'] + '\nFEMM_BUILD=1757\n')
    print('[100%] Built target femm_headless')
"""

ENVIRONMENT: Final = 'PATH=/x; export LAB_ROOT=/r'
DECLARED: Final = {'capabilities': {'femm': {}}}


@pytest.fixture
def calls(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv('FAKE_BUILT', FEMM_QT.version)
    return tmp_path / 'calls.log'


def _step(tmp_path: Path, calls: Path, *, dry: bool = False) -> Step:
    script = tmp_path / 'sh.py'
    script.write_text(FAKE_SH, encoding='utf-8')
    return Step(Tools(sh=(sys.executable, str(script), str(calls))), dry=dry)


def _install(tmp_path: Path, calls: Path, machine: dict[str, object] = DECLARED, *, dry: bool = False) -> int:
    return femm.install(
        _step(tmp_path, calls, dry=dry),
        machine,
        environment=ENVIRONMENT,
        tools_root=tmp_path / 'tools',
        home=tmp_path / 'home',
    )


def _final(tmp_path: Path) -> Path:
    return tmp_path / 'tools' / 'femm' / FEMM_QT.version


def _builds(calls: Path) -> int:
    return calls.read_text(encoding='utf-8').count('cmake --build') if calls.exists() else 0


def test_an_account_without_the_capability_gets_nothing(tmp_path: Path, calls: Path) -> None:
    assert _install(tmp_path, calls, {'capabilities': {'jmag': {}}}) == 0
    assert not calls.exists(), 'nothing is probed, nothing built'
    assert not (tmp_path / 'tools').exists()
    assert _install(tmp_path, calls) == 0, 'PLANTED CONTROL: the declared account builds'
    assert _builds(calls) == 1


def test_a_declared_account_builds_the_pin_into_its_versioned_home_with_the_version_file(
    tmp_path: Path, calls: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _install(tmp_path, calls) == 0
    bin_dir = _final(tmp_path) / 'bin'
    assert (bin_dir / 'femm_headless').is_file()
    assert (bin_dir / 'fkn').is_file(), 'the solvers femm_headless spawns sit beside it'
    assert f'FEMM_VERSION={FEMM_QT.version}' in (bin_dir / FEMM_VERSION_FILE).read_text(encoding='utf-8')
    build = next(line for line in calls.read_text(encoding='utf-8').splitlines() if 'cmake --build' in line)
    assert build.startswith(ENVIRONMENT), "the build runs in the tick's environment: the grant setup loads the compiler"
    for pinned in (FEMM_QT.url, FEMM_QT.tag, FEMM_QT.commit, 'CMAKE_DISABLE_FIND_PACKAGE_Qt6=ON', 'femm_headless'):
        assert pinned in build
    assert sorted(p.name for p in _final(tmp_path).parent.iterdir()) == [FEMM_QT.version], 'no scratch, no stage left'
    out = capsys.readouterr().out
    assert f'installed {FEMM_QT.version}' in out
    logs = list((tmp_path / 'home').rglob('build.log'))
    assert len(logs) == 1, 'every build keeps its log'
    assert 'Built target femm_headless' in logs[0].read_text(encoding='utf-8')


def test_an_install_already_at_the_pin_is_skipped_by_name(
    tmp_path: Path, calls: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _install(tmp_path, calls) == 0
    capsys.readouterr()
    assert _install(tmp_path, calls) == 0
    assert _builds(calls) == 1, 'the second deploy builds nothing'
    assert f'femm {FEMM_QT.version}: current at {_final(tmp_path)}; skipped' in capsys.readouterr().out


def test_an_install_without_its_version_file_is_rebuilt(tmp_path: Path, calls: Path) -> None:
    """A hand-built install carries no ``version.env``: lab_commons reads it ABSENT, so the deploy replaces it."""
    assert _install(tmp_path, calls) == 0
    (_final(tmp_path) / 'bin' / FEMM_VERSION_FILE).unlink()
    assert _install(tmp_path, calls) == 0
    assert _builds(calls) == 2
    assert (_final(tmp_path) / 'bin' / FEMM_VERSION_FILE).is_file()


def test_a_failed_build_is_refused_with_its_log_and_the_old_install_is_kept(
    tmp_path: Path, calls: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    old = _final(tmp_path) / 'bin'
    old.mkdir(parents=True)
    (old / 'femm_headless').write_text('the hand-built one', encoding='utf-8')  # no version file: not current
    monkeypatch.setenv('FAKE_BUILD_FAIL', '1')
    assert _install(tmp_path, calls) == 2
    err = capsys.readouterr().err
    log = next((tmp_path / 'home').rglob('build.log'))
    assert f'its log: {log}' in err
    assert 'subcommand failed' in log.read_text(encoding='utf-8')
    assert (old / 'femm_headless').read_text(encoding='utf-8') == 'the hand-built one', 'the old install is kept'
    assert sorted(p.name for p in _final(tmp_path).parent.iterdir()) == [FEMM_QT.version], 'no half install left'


def test_a_build_that_does_not_read_back_the_pin_is_refused_and_never_published(
    tmp_path: Path, calls: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv('FAKE_BUILT', '5.0.20261021')
    assert _install(tmp_path, calls) == 2
    err = capsys.readouterr().err
    assert f'5.0.20261021, not the pinned {FEMM_QT.version}' in err
    assert not _final(tmp_path).exists()
    assert list(_final(tmp_path).parent.iterdir()) == []
    monkeypatch.setenv('FAKE_BUILT', FEMM_QT.version)
    assert _install(tmp_path, calls) == 0, 'PLANTED CONTROL: the same build stating the pin is published'


def test_a_binary_that_does_not_run_in_the_tick_environment_is_refused(
    tmp_path: Path, calls: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A build against a module's libstdc++ that the tick's environment does not load runs nowhere a job runs."""
    monkeypatch.setenv('FAKE_FEMM_DEAD', '1')
    assert _install(tmp_path, calls) == 2
    assert "does not run in the tick's environment" in capsys.readouterr().err
    assert not _final(tmp_path).exists()


def test_a_missing_compiler_is_refused_by_name_before_anything_is_fetched(
    tmp_path: Path, calls: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv('FAKE_MISSING', 'g++')
    assert _install(tmp_path, calls) == 2
    err = capsys.readouterr().err
    assert 'g++' in err
    assert '[[hpc.grant]] setup' in err, 'the door: the grant setup that loads a compiler'
    assert _builds(calls) == 0
    assert 'git clone' not in calls.read_text(encoding='utf-8')


def test_a_missing_cmake_is_installed_through_its_one_installer(
    tmp_path: Path, calls: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv('FAKE_MISSING', 'cmake')
    assert _install(tmp_path, calls) == 0
    assert 'uv tool install cmake' in calls.read_text(encoding='utf-8')


def test_dry_run_builds_nothing_and_prints_the_build(
    tmp_path: Path, calls: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _install(tmp_path, calls, dry=True) == 0
    assert _builds(calls) == 0
    assert not (tmp_path / 'tools').exists()
    assert not (tmp_path / 'home').exists()
    out = capsys.readouterr().out
    assert '[dry-run]' in out
    assert FEMM_QT.tag in out


def test_a_verified_install_supersedes_every_other_version_and_nothing_else(tmp_path: Path, calls: Path) -> None:
    older = _final(tmp_path).parent / '5.0.20261021' / 'bin'
    older.mkdir(parents=True)
    (older / 'femm_headless').write_text('older', encoding='utf-8')
    kept = _final(tmp_path).parent / 'notes'
    kept.mkdir()
    assert _install(tmp_path, calls) == 0
    assert sorted(p.name for p in _final(tmp_path).parent.iterdir()) == [FEMM_QT.version, 'notes'], (
        'the older version goes once the pin verifies; PLANTED CONTROL: a directory that is no version stays'
    )
