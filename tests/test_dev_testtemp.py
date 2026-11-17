"""Controls for :mod:`dev_lab.dev.testtemp`: a test's temp dir lives in the dated tree, system temp is refused."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from dev_lab.dev import testtemp
from dev_lab.dev.datedlog import date_parts

pytest_plugins = ['pytester']

_ROOT = Path(__file__).resolve().parents[1]


def _dated(root: Path) -> Path:
    return root.joinpath('output', 'logs', *date_parts(), testtemp.KIND)


def _config(root: Path, basetemp: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(option=SimpleNamespace(basetemp=basetemp), rootpath=root)


def test_this_sessions_tmp_path_lives_in_the_dated_pytest_dir(tmp_path: Path) -> None:
    assert tmp_path.resolve().is_relative_to(_dated(_ROOT).resolve())


def test_an_unset_basetemp_becomes_a_fresh_dated_session_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('GIT_CEILING_DIRECTORIES', '')
    (tmp_path / 'pyproject.toml').write_text('[tool.dev_lab.parts]\noutput = "output/logs"\n', encoding='utf-8')
    config = _config(tmp_path)
    testtemp.configure(config)
    chosen = Path(config.option.basetemp)
    assert chosen.parent == _dated(tmp_path)
    assert chosen.is_dir()
    assert os.environ['GIT_CEILING_DIRECTORIES'] == str(tmp_path / 'output' / 'logs')


def test_a_basetemp_under_system_temp_is_refused(tmp_path: Path) -> None:
    """PLANTED: the system temp dir is exactly what D27 forbids; the refusal names the door."""
    with pytest.raises(pytest.UsageError, match=r'system temp dir.*dev_lab\.dev\.testtemp'):
        testtemp.configure(_config(tmp_path, basetemp=str(Path(tempfile.gettempdir()) / 'pytest-x')))


def test_a_basetemp_inside_the_tree_is_kept(tmp_path: Path) -> None:
    config = _config(tmp_path, basetemp=str(tmp_path / 'inner'))
    testtemp.configure(config)
    assert config.option.basetemp == str(tmp_path / 'inner')


def test_a_root_without_a_declared_output_is_refused_by_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(testtemp.HOME_ENV, raising=False)
    with pytest.raises(pytest.UsageError, match=r'tool\.dev_lab\.parts'):
        testtemp.configure(_config(tmp_path))


def test_a_nested_run_in_an_undeclared_sandbox_inherits_the_enclosing_dated_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PLANTED beside the refusal above: the same undeclared root is admitted once a session exported its dir."""
    home = tmp_path / 'home'
    monkeypatch.setenv(testtemp.HOME_ENV, str(home))
    config = _config(tmp_path / 'sandbox')
    testtemp.configure(config)
    assert Path(config.option.basetemp).parent == home


def test_a_spawned_controller_under_an_xdist_worker_still_gets_a_dated_basetemp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PLANTED: the worker marker a spawned pytest inherits must not make it skip choosing its basetemp."""
    monkeypatch.setenv('PYTEST_XDIST_WORKER', 'gw0')
    monkeypatch.setenv('GIT_CEILING_DIRECTORIES', '')
    (tmp_path / 'pyproject.toml').write_text('[tool.dev_lab.parts]\noutput = "output/logs"\n', encoding='utf-8')
    config = _config(tmp_path)
    testtemp.configure(config)
    assert Path(config.option.basetemp).parent == _dated(tmp_path)


def test_a_pytester_run_roots_at_its_sandbox_not_the_checkout(pytester: pytest.Pytester) -> None:
    """PLANTED: without the sandbox bound, the inner run would root at this checkout and read its config."""
    pytester.makepyfile('def test_x():\n    pass\n')
    result = pytester.runpytest_subprocess()
    result.assert_outcomes(passed=1)
    result.stdout.fnmatch_lines([f'rootdir: {pytester.path}'])
