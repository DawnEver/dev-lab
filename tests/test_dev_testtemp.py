"""Controls for :mod:`dev_lab.dev.testtemp`: a test temp dir is an owned system-temp entry, never output/."""

from __future__ import annotations

import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from lab_commons.temp import TEMP_PREFIX

from dev_lab.dev import testtemp
from dev_lab.dev.writeroots import owned_globs

pytest_plugins = ['pytester']


def _config(root: Path, basetemp: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(option=SimpleNamespace(basetemp=basetemp), rootpath=root)


def _owned_temp_entry(path: Path, kind: str) -> bool:
    system = Path(tempfile.gettempdir()).resolve()
    entry = path.resolve()
    return entry.parent == system and entry.name.startswith(f'{TEMP_PREFIX}{kind}-')


def test_this_sessions_tmp_path_lives_in_an_owned_system_temp_entry(tmp_path: Path) -> None:
    """D104: the session's base temp is a direct, prefixed entry of system temp -- the sweep's to age out."""
    system = Path(tempfile.gettempdir()).resolve()
    base = next(p for p in tmp_path.resolve().parents if p.parent == system)
    assert _owned_temp_entry(base, testtemp.KIND)


def test_an_unset_basetemp_becomes_a_fresh_owned_temp_entry(tmp_path: Path) -> None:
    config = _config(tmp_path)
    testtemp.configure(config)
    chosen = Path(config.option.basetemp)
    assert chosen.is_dir()
    assert _owned_temp_entry(chosen, testtemp.KIND)
    assert any(Path(chosen.name).match(glob) for glob in owned_globs({})), 'tmpsweep must own it'


def test_two_sessions_never_share_a_base_temp(tmp_path: Path) -> None:
    first, second = _config(tmp_path), _config(tmp_path)
    testtemp.configure(first)
    testtemp.configure(second)
    assert first.option.basetemp != second.option.basetemp


@pytest.mark.parametrize('under', ['output/logs/26/11/20/pytest/x', 'output/x', 'out/logs/x'])
def test_planted_a_basetemp_under_output_is_refused(tmp_path: Path, under: str) -> None:
    """PLANTED (OUTPUT-HOLDS-NO-CODE, D104): a test-temp root under output/ holds planted code; refused by name."""
    (tmp_path / 'pyproject.toml').write_text('[tool.dev_lab.parts]\noutput = "out/logs"\n', encoding='utf-8')
    with pytest.raises(pytest.UsageError, match=r'OUTPUT-HOLDS-NO-CODE.*dev_lab\.dev\.testtemp'):
        testtemp.configure(_config(tmp_path, basetemp=str(tmp_path / under)))


def test_a_basetemp_outside_output_is_kept(tmp_path: Path) -> None:
    """The control beside the refusal: the same call with a path outside every output tree passes."""
    (tmp_path / 'pyproject.toml').write_text('[tool.dev_lab.parts]\noutput = "out/logs"\n', encoding='utf-8')
    config = _config(tmp_path, basetemp=str(tmp_path / 'inner'))
    testtemp.configure(config)
    assert config.option.basetemp == str(tmp_path / 'inner')


def test_a_script_suite_s_temp_env_points_every_temp_variable_at_one_owned_entry() -> None:
    """``os.tmpdir()`` reads TMPDIR (POSIX) or TEMP/TMP (Windows), so all three name one fresh owned entry."""
    env = testtemp.script_temp_env({'PATH': 'p', 'TEMP': 'C:/elsewhere'})
    temp = Path(env['TMPDIR'])
    assert env['TEMP'] == env['TMP'] == env['TMPDIR']
    assert temp.is_dir()
    assert _owned_temp_entry(temp, testtemp.SCRIPT_KIND)
    assert env['PATH'] == 'p', 'the rest of the environment is kept'


def test_a_pytester_run_roots_at_its_sandbox(pytester: pytest.Pytester) -> None:
    """PLANTED: without the sandbox bound, the inner run would root at whatever config sits above system temp."""
    pytester.makepyfile('def test_x():\n    pass\n')
    result = pytester.runpytest_subprocess()
    result.assert_outcomes(passed=1)
    result.stdout.fnmatch_lines([f'rootdir: {pytester.path}'])
